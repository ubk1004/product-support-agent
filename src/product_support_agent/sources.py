from __future__ import annotations

import html
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote, urljoin, urlparse

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import ParseError
from defusedxml.ElementTree import fromstring as parse_xml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from product_support_agent.catalog import validate_source_url

SOURCE_MAP_SCHEMA_VERSION = "1"
DOCS_PORTAL_HOST = "docs.microfocus.com"
SITEMAP_NAMESPACE = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
MAX_PAGES_PER_PRODUCT = 200

SourceKind = Literal["docs_portal_toc", "sitemap"]


class ProductSource(BaseModel):
    """One approved, explicitly listed documentation source for a manifest product."""

    model_config = ConfigDict(frozen=True)

    product_id: str = Field(min_length=1)
    product_name: str = Field(min_length=1, max_length=512)
    kind: SourceKind
    seed_url: str
    path_prefix: str | None = None
    include_path_patterns: tuple[str, ...] = ()
    exclude_path_patterns: tuple[str, ...] = ()
    priority_path_patterns: tuple[str, ...] = ()
    max_toc_level: int | None = Field(default=None, ge=1)
    max_pages: int = Field(default=30, ge=1, le=MAX_PAGES_PER_PRODUCT)
    main_content_id: str | None = Field(default=None, pattern=r"^[A-Za-z][A-Za-z0-9_\-:.]*$")
    enabled: bool = True
    notes: str | None = None

    @field_validator("seed_url")
    @classmethod
    def seed_is_allowlisted(cls, value: str) -> str:
        if not validate_source_url(value):
            raise ValueError("seed URL must be an allowlisted HTTPS URL")
        return value

    @model_validator(mode="after")
    def kind_matches_seed(self) -> ProductSource:
        parsed = urlparse(self.seed_url)
        if self.kind == "docs_portal_toc" and (
            parsed.hostname != DOCS_PORTAL_HOST or not parsed.path.endswith("/tocflat.json")
        ):
            raise ValueError("docs_portal_toc seeds must be docs portal tocflat.json URLs")
        if self.kind == "sitemap" and not parsed.path.lower().endswith(".xml"):
            raise ValueError("sitemap seeds must be XML sitemap URLs")
        for pattern in (
            *self.include_path_patterns,
            *self.exclude_path_patterns,
            *self.priority_path_patterns,
        ):
            try:
                re.compile(pattern)
            except re.error as error:
                raise ValueError(f"invalid path pattern: {pattern!r}") from error
        return self


class SourceMap(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: str
    source_map_version: str = Field(min_length=1)
    manifest_version: str = Field(min_length=1)
    sources: tuple[ProductSource, ...]

    @model_validator(mode="after")
    def unique_products(self) -> SourceMap:
        if self.schema_version != SOURCE_MAP_SCHEMA_VERSION:
            raise ValueError("unsupported source map schema version")
        product_ids = [source.product_id for source in self.sources]
        if len(product_ids) != len(set(product_ids)):
            raise ValueError("each product may appear only once in a source map")
        return self

    def enabled_sources(self) -> list[ProductSource]:
        return [source for source in self.sources if source.enabled]


def load_source_map(path: Path) -> SourceMap:
    return SourceMap.model_validate_json(path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class PageCandidate:
    """A page to fetch. `fetch_url` is requested; `citation_url` is what users see."""

    fetch_url: str
    citation_url: str
    title: str | None = None
    revision: str | None = None


class DiscoveryError(ValueError):
    pass


def _path_selected(path: str, source: ProductSource) -> bool:
    if source.path_prefix and not path.startswith(source.path_prefix):
        return False
    if source.include_path_patterns and not any(
        re.search(pattern, path) for pattern in source.include_path_patterns
    ):
        return False
    return not any(re.search(pattern, path) for pattern in source.exclude_path_patterns)


def parse_docs_portal_toc(body: bytes, source: ProductSource) -> list[PageCandidate]:
    try:
        payload = json.loads(body.decode("utf-8-sig"))
        entries = payload["Toc"]["tocFlat"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise DiscoveryError("docs portal TOC is malformed") from error
    if not isinstance(entries, list):
        raise DiscoveryError("docs portal TOC is malformed")

    origin = f"https://{DOCS_PORTAL_HOST}"
    candidates: list[PageCandidate] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        href = str(entry.get("href") or "").strip().strip("/")
        revision = str(entry.get("revisionId") or "").strip()
        level = entry.get("level")
        if not href or not revision or href in seen or href.endswith("/home"):
            continue
        if not re.fullmatch(r"[A-Za-z0-9_.()\- %/]+", href) or ".." in href.split("/"):
            continue
        if not re.fullmatch(r"[A-Za-z0-9]+", revision):
            continue
        if source.max_toc_level is not None and isinstance(level, int):
            if level > source.max_toc_level:
                continue
        citation_path = "/doc/" + quote(href, safe="/()")
        if not _path_selected(citation_path, source):
            continue
        fetch_url = f"{origin}/{quote(href, safe='/()')}/default-{revision}.json"
        citation_url = origin + citation_path
        if not validate_source_url(fetch_url) or not validate_source_url(citation_url):
            continue
        seen.add(href)
        candidates.append(
            PageCandidate(
                fetch_url=fetch_url,
                citation_url=citation_url,
                title=str(entry.get("text") or "").strip() or None,
                revision=revision,
            )
        )
    return candidates


def parse_sitemap(body: bytes, source: ProductSource) -> list[PageCandidate]:
    try:
        root = parse_xml(body, forbid_dtd=True)
    except (ParseError, DefusedXmlException) as error:
        raise DiscoveryError("sitemap is malformed or declares a DTD") from error
    if root.tag not in (f"{SITEMAP_NAMESPACE}urlset", "urlset"):
        raise DiscoveryError("sitemap indexes are not followed; list a urlset sitemap")

    seed_host = urlparse(source.seed_url).hostname
    candidates: list[PageCandidate] = []
    seen: set[str] = set()
    for element in root.iter():
        if element.tag not in (f"{SITEMAP_NAMESPACE}loc", "loc") or not element.text:
            continue
        url = element.text.strip()
        parsed = urlparse(url)
        if (
            url in seen
            or parsed.hostname != seed_host
            or not parsed.path.lower().endswith((".htm", ".html"))
            or not validate_source_url(url)
            or not _path_selected(parsed.path, source)
        ):
            continue
        seen.add(url)
        candidates.append(PageCandidate(fetch_url=url, citation_url=url))
    return candidates


def discover_pages(body: bytes, source: ProductSource) -> list[PageCandidate]:
    if source.kind == "docs_portal_toc":
        return parse_docs_portal_toc(body, source)
    return parse_sitemap(body, source)


def select_pages(
    candidates: Sequence[PageCandidate],
    source: ProductSource,
) -> list[PageCandidate]:
    """Deterministic cap. Priority patterns rank first; otherwise publisher order is kept."""
    patterns = source.priority_path_patterns

    def rank(item: tuple[int, PageCandidate]) -> tuple[int, int]:
        index, candidate = item
        path = urlparse(candidate.citation_url).path
        for position, pattern in enumerate(patterns):
            if re.search(pattern, path):
                return position, index
        return len(patterns), index

    ordered = sorted(enumerate(candidates), key=rank)
    return [candidate for _, candidate in ordered[: source.max_pages]]


@dataclass(frozen=True)
class ExtractedPage:
    body: bytes
    content_type: str


class _ElementByIdExtractor(HTMLParser):
    """Re-emit the title and the subtree of one element ID so page chrome is not indexed."""

    _VOID_TAGS = frozenset(
        {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source"}
    )

    def __init__(self, element_id: str) -> None:
        super().__init__(convert_charrefs=True)
        self.element_id = element_id
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.found = False
        self._target_tag: str | None = None
        self._depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
        if self._target_tag is None:
            if not self.found and dict(attrs).get("id") == self.element_id:
                self.found = True
                self._target_tag = tag
                self._depth = 1
            return
        if tag == self._target_tag:
            self._depth += 1
        self.parts.append(f"<{tag}>" if tag not in self._VOID_TAGS else f"<{tag}/>")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if self._target_tag is None:
            return
        if tag == self._target_tag:
            self._depth -= 1
            if self._depth == 0:
                self._target_tag = None
                return
        self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        elif self._target_tag is not None:
            self.parts.append(html.escape(data))


def _main_content_html(body: bytes, content_type: str, element_id: str) -> bytes | None:
    match = re.search(r"charset\s*=\s*['\"]?([A-Za-z0-9_\-]+)", content_type, re.I)
    try:
        text = body.decode(match.group(1) if match else "utf-8", errors="replace")
    except LookupError:
        return None
    extractor = _ElementByIdExtractor(element_id)
    extractor.feed(text)
    extractor.close()
    if not extractor.found:
        return None
    title = html.escape(" ".join("".join(extractor.title_parts).split()))
    content = "".join(extractor.parts)
    return f"<html><head><title>{title}</title></head><body>{content}</body></html>".encode()


def _docs_portal_html(payload: Any) -> tuple[str, str]:
    try:
        parse = payload["parse"]
        fragment = parse["text"]["*"]
    except (KeyError, TypeError) as error:
        raise DiscoveryError("docs portal page JSON is malformed") from error
    if not isinstance(fragment, str) or not fragment.strip():
        raise DiscoveryError("docs portal page JSON has no content")
    title = str(parse.get("displaytitle") or "").strip()
    return fragment, title


def extract_page(
    source: ProductSource,
    candidate: PageCandidate,
    body: bytes,
    content_type: str,
) -> ExtractedPage:
    """Convert a fetched page into HTML for the shared normalizer."""
    if source.kind != "docs_portal_toc":
        if source.main_content_id:
            focused = _main_content_html(body, content_type, source.main_content_id)
            if focused is not None:
                return ExtractedPage(focused, "text/html; charset=utf-8")
        return ExtractedPage(body, content_type or "text/html")
    try:
        payload = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DiscoveryError("docs portal page JSON is malformed") from error
    fragment, title = _docs_portal_html(payload)
    page_title = html.escape(title or candidate.title or source.product_name)
    document = f"<html><head><title>{page_title}</title></head><body>{fragment}</body></html>"
    return ExtractedPage(document.encode("utf-8"), "text/html; charset=utf-8")


def robots_url_for(url: str) -> str:
    return urljoin(url, "/robots.txt")
