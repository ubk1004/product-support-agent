import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import httpx
import pytest

from product_support_agent import catalog as catalog_module

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "create_manifest.py"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("create_manifest", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def feed_only_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/products/"):
            return httpx.Response(200, text="<html></html>")
        if request.url.path.endswith("search-results"):
            return httpx.Response(401)
        items = [{"id": f"p{n:03}", "name": f"Product {n}", "slug": f"p{n:03}"} for n in range(5)]
        return httpx.Response(200, json=items)

    return httpx.MockTransport(handler)


@pytest.fixture
def use_transport(monkeypatch: pytest.MonkeyPatch):
    def install(transport: httpx.MockTransport) -> None:
        original = catalog_module.CatalogClient

        def factory(**kwargs):
            return original(client=transport, **kwargs)

        monkeypatch.setattr(catalog_module, "CatalogClient", factory)

    return install


def test_manifest_is_built_from_the_feed_when_search_is_protected(
    tmp_path: Path, use_transport, capsys: pytest.CaptureFixture[str]
) -> None:
    use_transport(feed_only_transport())
    module = load_script()
    output = tmp_path / "manifest.json"

    code = module.main(
        ["--output", str(output), "--manifest-version", "test-v1", "--max-products", "3"]
    )

    manifest = json.loads(output.read_text(encoding="utf-8"))
    assert code == 0
    assert manifest["manifest_version"] == "test-v1"
    assert len(manifest["selected_products"]) == 3
    assert "skipped: search: protected" in capsys.readouterr().out


def test_existing_manifest_is_not_replaced_without_the_flag(tmp_path: Path, use_transport) -> None:
    use_transport(feed_only_transport())
    module = load_script()
    output = tmp_path / "manifest.json"
    output.write_text("approved", encoding="utf-8")

    code = module.main(["--output", str(output), "--manifest-version", "test-v2"])

    assert code == 2
    assert output.read_text(encoding="utf-8") == "approved"


def test_empty_catalog_writes_no_manifest(tmp_path: Path, use_transport) -> None:
    use_transport(httpx.MockTransport(lambda request: httpx.Response(401)))
    module = load_script()
    output = tmp_path / "manifest.json"

    code = module.main(["--output", str(output), "--manifest-version", "test-v3"])

    assert code == 1
    assert not output.exists()
