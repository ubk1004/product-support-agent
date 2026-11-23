"""Demo product catalog exposed to the chat agent: names, support pages, and searchability."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from product_support_agent.catalog import Manifest
from product_support_agent.sources import SourceMap

MAX_PRODUCT_MATCHES = 15
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_STOP_WORDS = frozenset(
    {"and", "for", "focus", "micro", "of", "opentext", "product", "products", "software", "the"}
)


@dataclass(frozen=True)
class CatalogProduct:
    product_id: str
    name: str
    support_url: str
    searchable: bool


class ProductCatalog:
    """The fixed demo manifest joined with the approved source map.

    A product is searchable when the source map enables a documentation source for it.
    Every product has a public support page from the manifest.
    """

    def __init__(self, products: Sequence[CatalogProduct]) -> None:
        self._products = tuple(sorted(products, key=lambda item: item.name.casefold()))
        self._by_id = {product.product_id: product for product in self._products}

    @classmethod
    def from_manifest(cls, manifest: Manifest, source_map: SourceMap) -> ProductCatalog:
        searchable = {source.product_id for source in source_map.enabled_sources()}
        return cls(
            [
                CatalogProduct(
                    product_id=product.product_id,
                    name=product.name,
                    support_url=str(product.source_url),
                    searchable=product.product_id in searchable,
                )
                for product in manifest.selected_products
            ]
        )

    @property
    def products(self) -> tuple[CatalogProduct, ...]:
        return self._products

    @property
    def searchable_products(self) -> tuple[CatalogProduct, ...]:
        return tuple(product for product in self._products if product.searchable)

    @property
    def searchable_ids(self) -> tuple[str, ...]:
        return tuple(product.product_id for product in self.searchable_products)

    def get(self, product_id: str) -> CatalogProduct | None:
        return self._by_id.get(product_id)

    def find(self, name: str) -> list[CatalogProduct]:
        """Products whose names best match the query terms, searchable products first."""
        terms = [term for term in _tokens(name) if len(term) >= 2 and term not in _STOP_WORDS]
        if not terms:
            return []
        scored: list[tuple[int, CatalogProduct]] = []
        for product in self._products:
            name_terms = _tokens(product.name)
            score = sum(
                any(
                    word == term or (len(term) >= 4 and word.startswith(term))
                    for word in name_terms
                )
                for term in terms
            )
            if score:
                scored.append((score, product))
        if not scored:
            return []
        best = max(score for score, _ in scored)
        matches = [product for score, product in scored if score == best]
        matches.sort(key=lambda item: (not item.searchable, item.name.casefold()))
        return matches[:MAX_PRODUCT_MATCHES]

    def instructions_section(self) -> str:
        lines = [
            f"The demo catalog has {len(self._products)} products. Documentation is "
            f"searchable for these {len(self.searchable_products)} (product ID: name):"
        ]
        lines.extend(
            f"- {product.product_id}: {product.name}" for product in self.searchable_products
        )
        return "\n".join(lines)


def _tokens(value: str) -> list[str]:
    return _TOKEN_PATTERN.findall(value.casefold())
