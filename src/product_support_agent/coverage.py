from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol
from urllib.parse import urlparse

from pydantic import BaseModel

from product_support_agent.catalog import Manifest
from product_support_agent.fetch_state import FetchStateRecord
from product_support_agent.sources import ProductSource, SourceMap

CoverageStatus = Literal["indexed", "pending", "unavailable", "excluded", "no_public_source"]

COVERAGE_STATUS_ORDER: dict[CoverageStatus, int] = {
    "indexed": 0,
    "pending": 1,
    "unavailable": 2,
    "excluded": 3,
    "no_public_source": 4,
}


class CoverageStateReader(Protocol):
    def list_all(self) -> list[FetchStateRecord]: ...


class ProductCoverage(BaseModel):
    product_id: str
    product_name: str
    status: CoverageStatus
    reason_category: str | None = None
    source_host: str | None = None
    pages_indexed: int = 0
    last_indexed_at: datetime | None = None


class CoverageSummary(BaseModel):
    manifest_products: int
    products_with_sources: int
    products_indexed: int
    pages_indexed: int


class CoverageReport(BaseModel):
    """Product-level demo coverage. Metadata only: never page content or page URLs."""

    manifest_version: str
    source_map_version: str
    source_map_matches_manifest: bool
    state_available: bool
    retrieval_enabled: bool
    summary: CoverageSummary
    products: list[ProductCoverage]


def load_manifest(path: Path) -> Manifest:
    return Manifest.model_validate_json(path.read_text(encoding="utf-8"))


def _product_coverage(
    product_id: str,
    product_name: str,
    source: ProductSource | None,
    records: Iterable[FetchStateRecord],
) -> ProductCoverage:
    if source is None:
        return ProductCoverage(
            product_id=product_id,
            product_name=product_name,
            status="no_public_source",
        )
    host = urlparse(source.seed_url).hostname
    if not source.enabled:
        return ProductCoverage(
            product_id=product_id,
            product_name=product_name,
            status="excluded",
            source_host=host,
        )

    pages: list[FetchStateRecord] = []
    failing: FetchStateRecord | None = None
    for record in records:
        if record.kind == "page":
            if record.document_id and record.last_outcome != "removed":
                pages.append(record)
        elif record.last_outcome == "failed":
            failing = record

    if pages:
        last = max((page.last_success_at for page in pages if page.last_success_at), default=None)
        return ProductCoverage(
            product_id=product_id,
            product_name=product_name,
            status="indexed",
            source_host=host,
            pages_indexed=len(pages),
            last_indexed_at=last,
        )
    if failing is not None:
        return ProductCoverage(
            product_id=product_id,
            product_name=product_name,
            status="unavailable",
            reason_category=failing.reason_category,
            source_host=host,
        )
    return ProductCoverage(
        product_id=product_id,
        product_name=product_name,
        status="pending",
        source_host=host,
    )


def build_coverage_report(
    manifest: Manifest,
    source_map: SourceMap,
    records: Iterable[FetchStateRecord] | None,
    *,
    retrieval_enabled: bool = False,
) -> CoverageReport:
    """Combine the approved manifest, source map, and durable fetch state.

    `records=None` means the fetch-state store could not be read; sources are then reported
    as pending rather than as indexed.
    """
    sources = {source.product_id: source for source in source_map.sources}
    by_product: dict[str, list[FetchStateRecord]] = defaultdict(list)
    for record in records or ():
        by_product[record.product_id].append(record)

    products = [
        _product_coverage(
            product.product_id,
            product.name,
            sources.get(product.product_id),
            by_product.get(product.product_id, ()),
        )
        for product in manifest.selected_products
    ]
    products.sort(key=lambda item: (COVERAGE_STATUS_ORDER[item.status], item.product_name.lower()))
    return CoverageReport(
        manifest_version=manifest.manifest_version,
        source_map_version=source_map.source_map_version,
        source_map_matches_manifest=source_map.manifest_version == manifest.manifest_version,
        state_available=records is not None,
        retrieval_enabled=retrieval_enabled,
        summary=CoverageSummary(
            manifest_products=len(products),
            products_with_sources=sum(
                1 for item in products if item.status not in ("no_public_source", "excluded")
            ),
            products_indexed=sum(1 for item in products if item.status == "indexed"),
            pages_indexed=sum(item.pages_indexed for item in products),
        ),
        products=products,
    )
