import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "sanitize_chat_sessions.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sanitize_chat_sessions", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sanitizer = _load()

IDENTITIES = {
    "Jane Roe": "Dev User",
    "jroe": "devuser",
    "jane.roe@corp.test": "devuser@example.com",
}

# Random-looking values assembled at runtime so no literal credential sits in the repository.
GITHUB_TOKEN = "gh" + "o_" + "aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3zA5"
STORAGE_KEY = "q7Xk2PzR9vLm4Tn8WbYc3HdJ6sFg1AeU5oIiZ0xCvBnMqWeRtYuIoPaSdFgHjKlZ=="
SEARCH_KEY = "7Hq2LzXw9RmT4vBn8KcY3dJf6SgA1eUo5iPz0xCbVnMq"
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r"


def redact(text: str, identities: dict[str, str] | None = None) -> str:
    return sanitizer.Redactor(IDENTITIES if identities is None else identities).sanitize(text)


@pytest.mark.parametrize(
    ("secret", "template"),
    [
        (GITHUB_TOKEN, "Token: {}"),
        (JWT, "jwt {}"),
        (STORAGE_KEY, "AccountKey={}"),
        (STORAGE_KEY, "DefaultEndpointsProtocol=https;AccountName=acct;AccountKey={};Suffix=x"),
        (SEARCH_KEY, "PRODUCT_SUPPORT_SEARCH_ADMIN_KEY={}"),
        (SEARCH_KEY, "AZURE_OPENAI_API_KEY: {}"),
        (SEARCH_KEY, '"api-key": "{}"'),
        (SEARCH_KEY, "curl -H 'api-key: {}' https://x"),
        (SEARCH_KEY, "Authorization: Bearer {}"),
        (SEARCH_KEY, "https://acct.blob.core.windows.net/c/b?sv=1&sig={}&se=2"),
        (STORAGE_KEY, "Authorization: SharedKey acct:{}"),
        (SEARCH_KEY, "https://svc:{}@host.test/path"),
    ],
)
def test_credentials_are_redacted(secret: str, template: str) -> None:
    assert secret not in redact(template.format(secret))


def test_private_key_block_is_redacted() -> None:
    body = "A" * 20 + "b1" * 20
    pem = f"-----BEGIN RSA PRIVATE KEY-----\n{body}\n-----END RSA PRIVATE KEY-----"
    assert body not in redact(f"key:\n{pem}\nafter")


@pytest.mark.parametrize(
    "text",
    [
        "AZURE_OPENAI_API_KEY=YOUR_API_KEY_HERE",
        "AZURE_AI_SEARCH_API_KEY=${KEY}",
        "PRODUCT_SUPPORT_SEARCH_ADMIN_KEY=",
        "password=hunter2",
        "https://user:password@my.opentext.com/a",
        "Authorization: Bearer abcdefghijklmnop",
        "AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==",
        "SharedKey myaccount:ctzMq410TV3wS7upTBcunJTDLEJwMAZuFPfr0mrrA08=",
        "https://your-foundry-service.services.ai.azure.com/api/projects/p",
        "https://contosorest.blob.core.windows.net/",
        "mailto:person@example.com and git@github.com:org/repo.git",
        "C:\\Users\\Public\\Documents and /home/runner/work",
        "subscription_id: 00000000-0000-0000-0000-000000000000",
        "model gpt-5 and text-embedding-3-small at 127.0.0.1:27017",
        "sha256:8f0ce0794784c2315089e8692d17cf49c1ed5bc15a854e5e81da6d51c75ce526",
    ],
)
def test_placeholders_and_public_values_are_kept(text: str) -> None:
    assert redact(text) == text


def test_identities_use_one_consistent_alias() -> None:
    text = "Jane Roe / JROE / jroe pushed from C:\\Users\\jroe and jane.roe@corp.test"
    result = redact(text)
    expected = "Dev User / devuser / devuser pushed from C:\\Users\\devuser and devuser@example.com"
    assert result == expected
    assert redact(result) == result


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("C:\\Users\\jsmith\\AppData\\x", "C:\\Users\\devuser\\AppData\\x"),
        ("C:\\\\Users\\\\jsmith\\\\x", "C:\\\\Users\\\\devuser\\\\x"),
        ("file:///c%3A/Users/jsmith/AppData", "file:///c%3A/Users/devuser/AppData"),
        ("/Users/jsmith/.copilot/x", "/Users/devuser/.copilot/x"),
        ("/home/jsmith/work/", "/home/devuser/work/"),
    ],
)
def test_other_user_profile_paths_are_aliased(path: str, expected: str) -> None:
    assert redact(path, {}) == expected


def test_azure_resources_get_stable_aliases() -> None:
    first = redact("https://acmeprod.search.windows.net/indexes and acmeprod.search.windows.net")
    again = redact("acmeprod.search.windows.net")
    assert "acmeprod" not in first
    assert first.count(again) == 2
    assert redact("other.search.windows.net") != again


def test_azure_ids_are_aliased_consistently() -> None:
    real = "3f2b1c9e-7a44-4d0e-9b15-6c8e2d1a0f77"
    first = redact(f"/subscriptions/{real}/resourceGroups/rg")
    again = redact(f'"subscriptionId": "{real}"')
    assert real not in first + again
    assert first.split("/")[2] in again
    other = "1e2d3c4b-5a69-4788-9a0b-c1d2e3f40516"
    assert other not in redact(f"tenant_id={other}")
    assert redact("an unrelated id 3f2b1c9e-7a44-4d0e-9b15-6c8e2d1a0f77") != ""
    assert real in redact("request 3f2b1c9e-7a44-4d0e-9b15-6c8e2d1a0f77 finished")


def test_real_email_is_aliased_and_noreply_kept() -> None:
    assert "someone@corp.test" not in redact("cc someone@corp.test", {})
    assert redact("57718712+user@users.noreply.github.com", {}) == (
        "57718712+user@users.noreply.github.com"
    )


def test_json_layout_is_preserved_and_keys_are_sanitised(tmp_path: Path) -> None:
    document = {"jroe": ["C:\\Users\\jroe\\x", 3, None, True], "k": {"token": SEARCH_KEY}}
    path = tmp_path / "chat.json"
    original = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    path.write_text(original, encoding="utf-8", newline="")
    redactor = sanitizer.Redactor(IDENTITIES)
    result = sanitizer.sanitize_file_text(original, redactor)
    loaded = json.loads(result)
    assert "jroe" not in result
    assert SEARCH_KEY not in result
    assert loaded["devuser"][0] == "C:\\Users\\devuser\\x"
    assert loaded["devuser"][1:] == [3, None, True]
    assert result.endswith("}\n")
    assert sanitizer.sanitize_file_text(result, sanitizer.Redactor(IDENTITIES)) == result


def test_unusual_json_layout_falls_back_to_text_edit() -> None:
    compact = '{"a":"jroe"}'
    assert sanitizer.sanitize_file_text(compact, sanitizer.Redactor(IDENTITIES)) == (
        '{"a":"devuser"}'
    )


def test_main_check_reports_without_values_and_does_not_write(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "chat.json"
    original = json.dumps({"t": f"AZURE_OPENAI_API_KEY={SEARCH_KEY}"}, indent=2) + "\n"
    path.write_text(original, encoding="utf-8", newline="")
    assert sanitizer.main([str(path), "--check", "--no-auto-detect", "--config", "none"]) == 1
    output = capsys.readouterr().out
    assert "secret-assignment=1" in output
    assert SEARCH_KEY not in output
    assert path.read_text(encoding="utf-8") == original


def test_main_rewrites_then_check_passes(tmp_path: Path) -> None:
    path = tmp_path / "chat.json"
    path.write_text(
        json.dumps({"t": f"PRODUCT_SUPPORT_SEARCH_ADMIN_KEY={SEARCH_KEY}"}, indent=2) + "\n",
        encoding="utf-8",
        newline="",
    )
    args = [str(tmp_path), "--no-auto-detect", "--config", "none"]
    assert sanitizer.main(args) == 0
    assert SEARCH_KEY not in path.read_text(encoding="utf-8")
    assert sanitizer.main([*args, "--check"]) == 0


def test_config_file_is_validated(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text('{"identities": ["x"]}', encoding="utf-8")
    with pytest.raises(ValueError, match="identities"):
        sanitizer.load_config(config)
    config.write_text('{"identities": {"Real Name": "alias"}}', encoding="utf-8")
    assert sanitizer.load_config(config) == {"Real Name": "alias"}
    assert sanitizer.load_config(tmp_path / "missing.json") == {}
