import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from product_support_agent.catalog import ProductReference, is_login_content
from product_support_agent.documents import normalize_html
from product_support_agent.robots import RobotsPolicy, policy_for_status
from product_support_agent.sources import (
    DiscoveryError,
    PageCandidate,
    ProductSource,
    SourceMap,
    discover_pages,
    extract_page,
    load_source_map,
    select_pages,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_MAP_PATH = REPO_ROOT / "docs" / "operations" / "phase-3-source-map-v1.json"
MANIFEST_PATH = REPO_ROOT / "docs" / "operations" / "phase-2-product-manifest-v1.json"


def toc_source(**overrides) -> ProductSource:
    values = {
        "product_id": "1167",
        "product_name": "iPrint",
        "kind": "docs_portal_toc",
        "seed_url": "https://docs.microfocus.com/27/26.4/tocflat.json",
    }
    values.update(overrides)
    return ProductSource(**values)


def sitemap_source(**overrides) -> ProductSource:
    values = {
        "product_id": "1185",
        "product_name": "LoadRunner Professional",
        "kind": "sitemap",
        "seed_url": "https://admhelp.microfocus.com/lr/sitemaps/LR_sitemap.xml",
        "path_prefix": "/lr/en/26.1-26.3/",
    }
    values.update(overrides)
    return ProductSource(**values)


def toc_body(*entries: dict) -> bytes:
    return json.dumps({"Toc": {"tocFlat": list(entries)}}).encode()


def entry(href: str, revision: str = "101", level: int = 2, text: str = "Topic") -> dict:
    return {"href": href, "revisionId": revision, "level": level, "text": text}


# --- robots -----------------------------------------------------------------------------


ROBOTS = """﻿User-agent: *
Disallow: */beta/*
Disallow: /lre/en/25.1/
Disallow： /uft/en/23.4/
Disallow: documents/ppm/
Disallow: *&action=*
Allow: /lre/en/25.1/public/
Disallow: /exact.htm$
"""


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://h.example/lr/en/26.1/help.htm", True),
        ("https://h.example/doc/27/beta/page", False),
        ("https://h.example/lre/en/25.1/page.htm", False),
        ("https://h.example/lre/en/25.1/public/page.htm", True),
        ("https://h.example/uft/en/23.4/page.htm", False),
        ("https://h.example/documents/ppm/a.pdf", False),
        ("https://h.example/doc/x?id=1&action=pagepdf", False),
        ("https://h.example/exact.htm", False),
        ("https://h.example/exact.html", True),
    ],
)
def test_robots_policy_supports_wildcards_anchors_and_longest_match(url, allowed) -> None:
    assert RobotsPolicy.parse(ROBOTS).is_allowed(url) is allowed


def test_robots_prefers_specific_user_agent_group() -> None:
    text = "User-agent: *\nDisallow: /\n\nUser-agent: product-support-agent\nDisallow: /private/\n"
    policy = RobotsPolicy.parse(text)
    assert policy.is_allowed("https://h.example/docs/page")
    assert not policy.is_allowed("https://h.example/private/page")


@pytest.mark.parametrize(
    ("status", "allowed"),
    [(200, True), (404, True), (410, True), (401, False), (403, False), (503, False)],
)
def test_robots_status_handling_fails_closed_except_missing(status, allowed) -> None:
    assert policy_for_status(status, "").is_allowed("https://h.example/page") is allowed


# --- login heuristic --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "protected"),
    [
        ("<form>Please sign in</form>", True),
        ("Please sign in: confidential form content", True),
        ("<html><input type='password' name='p'></html>", True),
        ('<form action="/idp/login">x</form>', True),
        ("<input name=SAMLRequest>", True),
        ("<p>Configure the login timeout for LDAP users. </p>" * 30, False),
        ("<p>Log in to APLS</p>" + "<p>License administration details. </p>" * 20, False),
        ('<form class="search" action="#"><input type="text"></form>' + "<p>Doc. </p>" * 90, False),
        ("<html><body>Indexed support content.</body></html>", False),
    ],
)
def test_login_heuristic_flags_login_walls_not_documentation(content, protected) -> None:
    assert is_login_content(content) is protected


# --- source map -------------------------------------------------------------------------


def test_repository_source_map_is_valid_and_maps_to_manifest_products() -> None:
    source_map = load_source_map(SOURCE_MAP_PATH)
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest_ids = {item["product_id"] for item in manifest["selected_products"]}

    assert source_map.manifest_version == manifest["manifest_version"]
    assert len(source_map.enabled_sources()) >= 10
    assert {source.product_id for source in source_map.sources} <= manifest_ids
    assert all(source.max_pages <= 30 for source in source_map.sources)


@pytest.mark.parametrize(
    "overrides",
    [
        {"seed_url": "https://evil.example/27/26.4/tocflat.json"},
        {"seed_url": "http://docs.microfocus.com/27/26.4/tocflat.json"},
        {"seed_url": "https://docs.microfocus.com/doc/27/26.4/home"},
        {"kind": "sitemap", "seed_url": "https://admhelp.microfocus.com/lr/page.htm"},
        {"max_pages": 0},
        {"max_pages": 201},
        {"include_path_patterns": ["("]},
        {"main_content_id": "bad id"},
    ],
)
def test_product_source_rejects_unsafe_or_inconsistent_entries(overrides) -> None:
    with pytest.raises(ValidationError):
        toc_source(**overrides)


def test_source_map_rejects_duplicate_products_and_unknown_schema() -> None:
    with pytest.raises(ValidationError):
        SourceMap(
            schema_version="1",
            source_map_version="v",
            manifest_version="m",
            sources=(toc_source(), toc_source()),
        )
    with pytest.raises(ValidationError):
        SourceMap(schema_version="2", source_map_version="v", manifest_version="m", sources=())


# --- discovery --------------------------------------------------------------------------


def test_docs_portal_toc_builds_fetch_and_citation_urls_and_filters_entries() -> None:
    body = toc_body(
        entry("27/26.4/home", "1", level=1),
        entry("27/26.4/whatsnew", "2602405922", level=2, text="What's new"),
        entry("27/26.4/whatsnew", "999", level=2),
        entry("27/26.4/deep", "3", level=4),
        entry("27/26.4/../escape", "4"),
        entry("27/26.4/bad-revision", "a/b"),
        entry("2302/26.2 (v3.2.8)/install", "abc123", level=2),
    )
    candidates = discover_pages(body, toc_source(max_toc_level=3))

    assert candidates[0] == PageCandidate(
        fetch_url="https://docs.microfocus.com/27/26.4/whatsnew/default-2602405922.json",
        citation_url="https://docs.microfocus.com/doc/27/26.4/whatsnew",
        title="What's new",
        revision="2602405922",
    )
    assert [candidate.citation_url for candidate in candidates] == [
        "https://docs.microfocus.com/doc/27/26.4/whatsnew",
        "https://docs.microfocus.com/doc/2302/26.2%20(v3.2.8)/install",
    ]


@pytest.mark.parametrize("body", [b"not json", b"{}", b'{"Toc": {"tocFlat": {}}}'])
def test_malformed_docs_portal_toc_raises(body) -> None:
    with pytest.raises(DiscoveryError):
        discover_pages(body, toc_source())


SITEMAP = b"""<?xml version="1.0" encoding="utf-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://admhelp.microfocus.com/lr/en/26.1-26.3/help/Install/a.htm</loc></url>
  <url><loc>
     https://admhelp.microfocus.com/lr/en/26.1-26.3/help/Analysis/b.htm
  </loc></url>
  <url><loc>https://admhelp.microfocus.com/lr/en/26.1-26.3/help/Install/a.htm</loc></url>
  <url><loc>https://admhelp.microfocus.com/lr/en/26.1-26.3/help/Install/diagram.png</loc></url>
  <url><loc>https://admhelp.microfocus.com/lr/en/25.1/help/Install/old.htm</loc></url>
  <url><loc>https://evil.example/lr/en/26.1-26.3/help/Install/x.htm</loc></url>
  <url><loc>https://admhelp.microfocus.com/lr/en/26.1-26.3/help/Resources/r.htm</loc></url>
</urlset>"""


def test_sitemap_discovery_applies_host_prefix_patterns_and_html_only() -> None:
    source = sitemap_source(exclude_path_patterns=["/Resources/"])
    candidates = discover_pages(SITEMAP, source)

    assert [candidate.fetch_url for candidate in candidates] == [
        "https://admhelp.microfocus.com/lr/en/26.1-26.3/help/Install/a.htm",
        "https://admhelp.microfocus.com/lr/en/26.1-26.3/help/Analysis/b.htm",
    ]
    assert all(candidate.fetch_url == candidate.citation_url for candidate in candidates)
    assert [
        candidate.fetch_url
        for candidate in discover_pages(
            SITEMAP, sitemap_source(include_path_patterns=["/Install/"])
        )
    ] == ["https://admhelp.microfocus.com/lr/en/26.1-26.3/help/Install/a.htm"]


@pytest.mark.parametrize(
    "body",
    [
        b"<urlset",
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><urlset/>',
        b'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></sitemapindex>',
    ],
)
def test_sitemap_rejects_malformed_dtd_and_index_documents(body) -> None:
    with pytest.raises(DiscoveryError):
        discover_pages(body, sitemap_source())


def test_select_pages_ranks_priority_patterns_then_keeps_publisher_order() -> None:
    candidates = [
        PageCandidate(f"https://admhelp.microfocus.com/p/{name}.htm", f"https://x/{name}")
        for name in ("a", "install-1", "b", "troubleshoot", "install-2")
    ]
    source = sitemap_source(max_pages=3, priority_path_patterns=["troubleshoot", "install"])
    assert [page.citation_url.rsplit("/", 1)[-1] for page in select_pages(candidates, source)] == [
        "troubleshoot",
        "install-1",
        "install-2",
    ]
    assert len(select_pages(candidates, sitemap_source(max_pages=2))) == 2


# --- extraction -------------------------------------------------------------------------


def test_docs_portal_page_json_becomes_html_with_title_and_citation_url() -> None:
    page = PageCandidate(
        "https://docs.microfocus.com/27/26.2/whatsnew/default-1.json",
        "https://docs.microfocus.com/doc/27/26.2/whatsnew",
        "Fallback",
        "1",
    )
    body = json.dumps(
        {
            "parse": {
                "displaytitle": "What's new <&>",
                "text": {"*": "<style>a{}</style><p>Upgraded the iPrint Map Tool.</p>"},
            }
        }
    ).encode()
    extracted = extract_page(toc_source(), page, body, "binary/octet-stream")
    document = normalize_html(
        ProductReference(
            product_id="1167", name="iPrint", slug="whatsnew", source_url=page.citation_url
        ),
        extracted.body,
        extracted.content_type,
    )
    assert document.title == "What's new <&>"
    assert document.content == "Upgraded the iPrint Map Tool."
    assert str(document.source_url) == page.citation_url


@pytest.mark.parametrize(
    "body",
    [b"nope", b"{}", b'{"parse": {"text": {"*": "  "}}}', b'{"parse": {"text": "x"}}'],
)
def test_malformed_docs_portal_page_raises(body) -> None:
    page = PageCandidate("https://docs.microfocus.com/a/default-1.json", "https://x", None, "1")
    with pytest.raises(DiscoveryError):
        extract_page(toc_source(), page, body, "application/json")


def test_main_content_id_drops_page_chrome_and_falls_back_when_missing() -> None:
    html = (
        b"<html><head><title> Get started</title></head><body>"
        b"<nav>Account Settings Logout</nav>"
        b'<div role="main" id="mc-main-content"><h1>Get started</h1>'
        b"<div><p>Load testing &amp; more.</p></div></div>"
        b"<footer>Terms of Use</footer></body></html>"
    )
    page = PageCandidate(
        "https://admhelp.microfocus.com/a.htm", "https://admhelp.microfocus.com/a.htm"
    )
    reference = ProductReference(
        product_id="1185", name="LR", slug="a", source_url="https://admhelp.microfocus.com/a.htm"
    )
    focused = extract_page(
        sitemap_source(main_content_id="mc-main-content"), page, html, "text/html"
    )
    document = normalize_html(reference, focused.body, focused.content_type)
    assert document.title == "Get started"
    assert document.content == "Get started Load testing & more."

    fallback = extract_page(sitemap_source(main_content_id="missing"), page, html, "text/html")
    assert fallback.body == html
