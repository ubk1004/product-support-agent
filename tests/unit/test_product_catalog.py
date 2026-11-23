from product_support_agent.product_catalog import CatalogProduct, ProductCatalog

CATALOG = ProductCatalog(
    [
        CatalogProduct("1185", "LoadRunner Professional", "https://x/1185", searchable=True),
        CatalogProduct("1184", "LoadRunner Enterprise", "https://x/1184", searchable=True),
        CatalogProduct("9", "LoadRunner Cloud", "https://x/9", searchable=False),
        CatalogProduct("22", "ValueEdge", "https://x/22", searchable=True),
        CatalogProduct("644", "AdLib eDocument Solutions", "https://x/644", searchable=False),
    ]
)


def test_find_prefers_best_name_match() -> None:
    assert [product.product_id for product in CATALOG.find("LoadRunner Professional")] == ["1185"]


def test_find_lists_searchable_matches_first() -> None:
    assert [product.product_id for product in CATALOG.find("loadrunner")] == ["1184", "1185", "9"]


def test_find_matches_prefixes_and_ignores_stop_words() -> None:
    assert [product.product_id for product in CATALOG.find("OpenText AdLib")] == ["644"]
    assert [product.product_id for product in CATALOG.find("value")] == ["22"]
    assert CATALOG.find("va") == []
    assert CATALOG.find("OpenText software") == []


def test_searchable_products_and_instructions() -> None:
    assert CATALOG.searchable_ids == ("1184", "1185", "22")
    section = CATALOG.instructions_section()
    assert "5 products" in section
    assert "- 22: ValueEdge" in section
    assert "AdLib" not in section
