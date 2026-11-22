from __future__ import annotations

import codecs
import hashlib
import re
from datetime import datetime
from html.parser import HTMLParser
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from product_support_agent.catalog import ProductReference, validate_source_url

DOCUMENT_SCHEMA_VERSION = "1"
HTML_PARSER_VERSION = "html-v1"
MAX_DOCUMENT_BYTES = 4_194_304
DEFAULT_CHUNK_SIZE_CHARS = 1_200
DEFAULT_CHUNK_OVERLAP_CHARS = 150
MAX_EXCERPT_CHARS = 240


class DocumentNormalizationError(ValueError):
    pass


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stable_document_id(product_id: str, source_url: str) -> str:
    if not product_id.strip() or not validate_source_url(source_url):
        raise ValueError("a product ID and allowlisted HTTPS source URL are required")
    material = f"{product_id.strip()}\0{source_url}"
    return f"doc_{_sha256(material)}"


def stable_chunk_id(document_id: str, chunk_index: int) -> str:
    if not document_id.strip() or chunk_index < 0:
        raise ValueError("a document ID and non-negative chunk index are required")
    material = f"{document_id}\0{chunk_index}"
    return f"chunk_{_sha256(material)}"


class CanonicalDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_id: str
    source_id: str
    product_id: str
    product_name: str = Field(min_length=1, max_length=512)
    source_url: HttpUrl
    title: str = Field(min_length=1, max_length=512)
    content: str = Field(min_length=1)
    content_hash: str
    schema_version: str = DOCUMENT_SCHEMA_VERSION
    parser_version: str = HTML_PARSER_VERSION
    fetched_at: datetime | None = None

    @model_validator(mode="after")
    def validate_identity_and_hash(self) -> Self:
        source_url = str(self.source_url)
        if not validate_source_url(source_url):
            raise ValueError("source URL is not allowlisted")
        if self.document_id != stable_document_id(self.product_id, source_url):
            raise ValueError("document ID does not match its canonical source")
        if self.source_id != self.product_id:
            raise ValueError("source ID must preserve the catalog product ID")
        if self.content_hash != _sha256(self.content):
            raise ValueError("content hash does not match canonical content")
        if not self.content.strip():
            raise ValueError("canonical content cannot be empty")
        return self


class CanonicalChunk(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk_id: str
    document_id: str
    source_id: str
    product_id: str
    source_url: HttpUrl
    title: str = Field(min_length=1, max_length=512)
    content: str = Field(min_length=1)
    excerpt: str = Field(min_length=1, max_length=MAX_EXCERPT_CHARS)
    content_hash: str
    chunk_index: int = Field(ge=0)
    schema_version: str = DOCUMENT_SCHEMA_VERSION
    parser_version: str = HTML_PARSER_VERSION

    @model_validator(mode="after")
    def validate_identity_and_hash(self) -> Self:
        if not validate_source_url(str(self.source_url)):
            raise ValueError("source URL is not allowlisted")
        if self.source_id != self.product_id:
            raise ValueError("source ID must preserve the catalog product ID")
        if self.document_id != stable_document_id(self.product_id, str(self.source_url)):
            raise ValueError("document ID does not match its canonical source")
        if self.chunk_id != stable_chunk_id(self.document_id, self.chunk_index):
            raise ValueError("chunk ID does not match its document and index")
        if self.content_hash != _sha256(self.content):
            raise ValueError("content hash does not match chunk content")
        if not self.content.strip() or not self.excerpt.strip():
            raise ValueError("chunk content and excerpt cannot be empty")
        return self


class _VisibleTextParser(HTMLParser):
    _BLOCK_TAGS = {
        "article",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "ol",
        "p",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }
    _IGNORED_TAGS = {"script", "style", "noscript", "svg", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.content_parts: list[str] = []
        self.title_parts: list[str] = []
        self._ignored_tags: list[str] = []
        self._title_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        normalized_tag = tag.lower()
        if normalized_tag in self._IGNORED_TAGS:
            self._ignored_tags.append(normalized_tag)
        if normalized_tag == "title":
            self._title_depth += 1
        if not self._ignored_tags and normalized_tag in self._BLOCK_TAGS:
            self.content_parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        if normalized_tag == "title" and self._title_depth:
            self._title_depth -= 1
        if normalized_tag in self._IGNORED_TAGS:
            for index in range(len(self._ignored_tags) - 1, -1, -1):
                if self._ignored_tags[index] == normalized_tag:
                    del self._ignored_tags[index:]
                    break
        if not self._ignored_tags and normalized_tag in self._BLOCK_TAGS:
            self.content_parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self._title_depth:
            self.title_parts.append(data)
        elif not self._ignored_tags:
            self.content_parts.append(data)


def _decode_html(body: bytes, content_type: str) -> str:
    charset_match = re.search(r"(?:^|;)\s*charset\s*=\s*['\"]?([^;'\"]+)", content_type, re.I)
    charset = charset_match.group(1).strip() if charset_match else "utf-8"
    try:
        encoding = codecs.lookup(charset).name
    except LookupError as error:
        raise DocumentNormalizationError("unsupported HTML character encoding") from error
    return body.decode(encoding, errors="replace")


def normalize_html(
    source: ProductReference,
    body: bytes,
    content_type: str,
    *,
    max_bytes: int = MAX_DOCUMENT_BYTES,
    fetched_at: datetime | None = None,
) -> CanonicalDocument:
    if not validate_source_url(str(source.source_url)):
        raise DocumentNormalizationError("source URL is not allowlisted")
    if max_bytes <= 0:
        raise DocumentNormalizationError("max_bytes must be positive")
    if not isinstance(body, bytes):
        raise TypeError("HTML body must be bytes")
    if len(body) > max_bytes:
        raise DocumentNormalizationError("HTML document exceeds the configured size limit")
    if content_type.split(";", maxsplit=1)[0].strip().lower() != "text/html":
        raise DocumentNormalizationError("unsupported source content type")
    if not body:
        raise DocumentNormalizationError("HTML document cannot be empty")

    parser = _VisibleTextParser()
    parser.feed(_decode_html(body, content_type))
    parser.close()
    content = " ".join("".join(parser.content_parts).split())
    title = (" ".join("".join(parser.title_parts).split()) or source.name)[:512]
    if not content:
        raise DocumentNormalizationError("HTML document contains no extractable text")

    source_url = str(source.source_url)
    return CanonicalDocument(
        document_id=stable_document_id(source.product_id, source_url),
        source_id=source.product_id,
        product_id=source.product_id,
        product_name=source.name,
        source_url=source.source_url,
        title=title,
        content=content,
        content_hash=_sha256(content),
        fetched_at=fetched_at,
    )


def _split_text(
    content: str,
    *,
    max_chars: int,
    overlap_chars: int,
) -> list[str]:
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be between zero and max_chars")

    normalized = " ".join(content.split())
    if not normalized:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + max_chars, len(normalized))
        split_inside_word = False
        if end < len(normalized) and not normalized[end].isspace():
            boundary = normalized.rfind(" ", start, end)
            if boundary > start:
                end = boundary
            else:
                split_inside_word = True

        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(normalized):
            break

        next_start = end
        if overlap_chars:
            next_start = max(start + 1, end - overlap_chars)
            if not split_inside_word:
                previous_space = normalized.rfind(" ", start, next_start)
                if previous_space >= start:
                    next_start = previous_space + 1
                else:
                    next_start = end
        else:
            next_start = end

        while next_start < len(normalized) and normalized[next_start].isspace():
            next_start += 1

        if next_start <= start:
            next_start = end
        start = next_start

    return chunks


def chunk_document(
    document: CanonicalDocument,
    *,
    max_chars: int = DEFAULT_CHUNK_SIZE_CHARS,
    overlap_chars: int = DEFAULT_CHUNK_OVERLAP_CHARS,
) -> list[CanonicalChunk]:
    return [
        CanonicalChunk(
            chunk_id=stable_chunk_id(document.document_id, index),
            document_id=document.document_id,
            source_id=document.source_id,
            product_id=document.product_id,
            source_url=document.source_url,
            title=document.title,
            content=content,
            excerpt=content[:MAX_EXCERPT_CHARS].rstrip(),
            content_hash=_sha256(content),
            chunk_index=index,
            schema_version=document.schema_version,
            parser_version=document.parser_version,
        )
        for index, content in enumerate(
            _split_text(
                document.content,
                max_chars=max_chars,
                overlap_chars=overlap_chars,
            )
        )
    ]
