"""Anonymise secrets and personal identifiers in exported Copilot chat sessions.

The sessions under ``docs/chat-sessions`` are committed as project evidence, so they must not
carry credentials or details that identify the author. This script rewrites them in place, or
with ``--check`` only reports what it would change (exit code 1) without touching any file.

What it does:

* Replaces the author's identities with one stable alias so the transcripts stay readable and
  consistent: the OS user name, the git ``user.name``/``user.email``, and anything listed in
  ``.local/chat-sanitizer.json`` (git-ignored, so real names never reach the repository).
* Replaces user-profile paths (``C:\\Users\\<name>``, ``/Users/<name>``) for any other user name.
* Redacts credentials: private keys, GitHub/OpenAI/AWS/Slack tokens, JWTs, storage account keys,
  SAS signatures, ``Bearer``/``Basic`` values, API-key headers, ``*_KEY=``/``*_SECRET=``
  assignments, and passwords in URLs. Values must look random (length, entropy, mixed
  characters), so placeholders, identifiers and the public Azurite key are left alone.
* Replaces Azure resource host names and subscription/tenant IDs, including the tenant ID in
  token-issuer URLs such as ``https://sts.windows.net/<id>/``. IDs become fabricated UUIDs
  from a random per-run key, so an alias cannot be recomputed from a known real ID; within one
  run the same real ID always gets the same alias.
* Replaces e-mail addresses other than documentation or no-reply ones.

Matched values are never printed; ``--check`` reports only the file and the rule.

Config (``.local/chat-sanitizer.json``)::

    {"identities": {"real value": "alias", "other value": "alias"}}

Usage::

    uv run python scripts/sanitize_chat_sessions.py               # rewrite docs/chat-sessions
    uv run python scripts/sanitize_chat_sessions.py --check       # report only; exit 1 if dirty
    uv run python scripts/sanitize_chat_sessions.py --no-auto-detect --check   # CI-safe
"""

from __future__ import annotations

import argparse
import configparser
import getpass
import hashlib
import hmac
import json
import math
import re
import secrets
import sys
import uuid
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

DEFAULT_PATHS = ("docs/chat-sessions",)
DEFAULT_CONFIG = Path(".local/chat-sanitizer.json")

USER_ALIAS = "devuser"
NAME_ALIAS = "Dev User"
EMAIL_ALIAS = "devuser@example.com"
REDACTED = "[REDACTED]"

MIN_SECRET_LENGTH = 24
MIN_SECRET_ENTROPY = 3.5
MIN_IDENTITY_LENGTH = 4

# Values that are public by design and therefore safe to keep in a transcript.
PUBLIC_VALUES = frozenset(
    {
        # Azurite's documented, well-known development account key.
        "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==",
    }
)

# Names that read as documentation placeholders rather than real resources or accounts.
PLACEHOLDER = re.compile(
    r"^(?:your|my|contoso|example|sample|test|fake|dummy|synthetic|demo|foo|bar|changeme"
    r"|placeholder|redacted|devstoreaccount|xxx)|^[x*.\-_]+$|[<>{}$]|^u00[0-9a-f]{2}",
    re.IGNORECASE,
)

AZURE_SUFFIXES = (
    "openai.azure.com",
    "services.ai.azure.com",
    "cognitiveservices.azure.com",
    "search.windows.net",
    "blob.core.windows.net",
    "queue.core.windows.net",
    "table.core.windows.net",
    "file.core.windows.net",
    "vault.azure.net",
    "azurewebsites.net",
    "azure-api.net",
    "azurecr.io",
    "azurecontainerapps.io",
    "documents.azure.com",
    "mongo.cosmos.azure.com",
    "servicebus.windows.net",
    "database.windows.net",
    "postgres.database.azure.com",
    "redis.cache.windows.net",
)
COMMON_AZURE_LABELS = frozenset({"management", "portal", "login", "scm", "www", "docs"})

BENIGN_EMAIL_DOMAINS = ("example.com", "example.org", "example.net", "noreply.github.com")
BENIGN_EMAIL_LOCALS = frozenset({"git", "noreply", "no-reply"})
BENIGN_PROFILE_NAMES = frozenset(
    {"public", "default", "defaultuser0", "all", "shared", "user", "username", "you", "name"}
)
BENIGN_HOME_NAMES = frozenset(
    {"user", "runner", "vscode", "node", "ubuntu", "app", "appuser", "root", "codespace"}
)
BENIGN_URL_PASSWORDS = frozenset({"password", "pass", "secret", "changeme", "example", "user"})

_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_SEP = r"(?:\\+|/|%5C|%2F)"
_NAME_CHARS = r"[^\\/\s\"'%:<>|*?{}$]+"

_TOKEN = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}"
    r"|xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}"
    r"|eyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{10,})"
)
_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"
)
_CONNECTION_STRING = re.compile(
    r"(?P<pre>\b(?:AccountKey|SharedAccessKey|SharedAccessSignature|Password|Pwd)\s*=\s*)"
    r"(?P<val>[^;\"'\s\\]+)",
    re.IGNORECASE,
)
_SIG_PARAM = re.compile(r"(?P<pre>[?&]sig=)(?P<val>[^&\s\"'\\]+)")
_SHARED_KEY = re.compile(
    r"(?P<pre>\bSharedKey(?:Lite)?\s+(?P<acct>[A-Za-z0-9]+):)"
    r"(?P<val>[A-Za-z0-9+/]{20,}={0,2})"
)
_AUTH_SCHEME = re.compile(
    r"(?P<pre>\b(?:Bearer|Basic)\s+)(?P<val>[A-Za-z0-9._~+/=-]{24,})", re.IGNORECASE
)
_API_KEY_HEADER = re.compile(
    r"(?P<pre>\b(?:x-)?api-key|ocp-apim-subscription-key)(?P<sep>[\\\"']*\s*[:=]\s*[\\\"']*)"
    r"(?P<val>[^\s\"'\\]+)",
    re.IGNORECASE,
)
_SECRET_KEY_NAME = re.compile(
    r"api[_-]?key|admin[_-]?key|access[_-]?key|secret|token|password|passwd|connection[_-]?string",
    re.IGNORECASE,
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?P<pre>\b[A-Z0-9_]*(?:API_?KEY|ADMIN_?KEY|ACCESS_?KEY|SECRET|TOKEN|PASSWORD|PASSWD"
    r"|CONNECTION_?STRING)[A-Z0-9_]*[\"']?\s*[=:]\s*\\?[\"']?)(?P<val>[^\s\"'\\;,]+)",
    re.IGNORECASE,
)
_URL_PASSWORD = re.compile(r"(?P<pre>://[^/\s:@\\\"']+:)(?P<val>[^/\s@\\\"']+)(?=@)")
_AZURE_HOST = re.compile(
    r"\b(?P<label>[a-z0-9][a-z0-9-]{1,62})\.(?P<suffix>"
    + "|".join(re.escape(s) for s in sorted(AZURE_SUFFIXES, key=len, reverse=True))
    + r")\b",
    re.IGNORECASE,
)
_AZURE_ID = re.compile(
    rf"(?P<pre>/subscriptions/"
    rf"|(?:sts\.windows\.net|login\.windows\.net|login\.microsoftonline\.com)/"
    rf"|\b(?:subscription|tenant)(?:[_ -]?id)?\b[\"'\\\s:=]{{1,8}})"
    rf"(?P<val>{_UUID})",
    re.IGNORECASE,
)
_EMAIL = re.compile(
    r"(?<![\\\w.%+\-:])(?P<local>[A-Za-z0-9._%+\-]*[A-Za-z0-9])"
    r"@(?P<domain>[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,})"
)
_WINDOWS_PROFILE = re.compile(
    rf"(?P<pre>(?:[A-Za-z]:|%3A){_SEP}Users{_SEP})(?P<name>{_NAME_CHARS})", re.IGNORECASE
)
_POSIX_PROFILE = re.compile(rf"(?P<pre>(?<![\w.%~\-])/Users/)(?P<name>{_NAME_CHARS})")
_POSIX_HOME = re.compile(r"(?P<pre>(?<![\w.%~\-])/home/)(?P<name>[A-Za-z0-9_.\-]+)(?=/)")


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.lower().encode("utf-8")).hexdigest()[:8]


def _entropy(value: str) -> float:
    counts = Counter(value)
    return -sum(n / len(value) * math.log2(n / len(value)) for n in counts.values())


def _looks_secret(value: str) -> bool:
    """Random-looking and long enough to be a credential, not an identifier or placeholder."""
    if len(value) < MIN_SECRET_LENGTH or value in PUBLIC_VALUES:
        return False
    if re.search(r"[<>{}$()]", value) or value.upper().startswith("YOUR"):
        return False
    classes = sum(bool(re.search(p, value)) for p in ("[a-z]", "[A-Z]", "[0-9]"))
    return classes >= 2 and bool(re.search(r"\d", value)) and _entropy(value) >= MIN_SECRET_ENTROPY


def _redact_token(_: re.Match[str]) -> str:
    return "[REDACTED_TOKEN]"


def _redact_private_key(_: re.Match[str]) -> str:
    return "[REDACTED_PRIVATE_KEY]"


def _redact_value(match: re.Match[str]) -> str:
    if not _looks_secret(match.group("val")):
        return match.group(0)
    return match.group("pre") + REDACTED


def _redact_header(match: re.Match[str]) -> str:
    if not _looks_secret(match.group("val")):
        return match.group(0)
    return match.group("pre") + match.group("sep") + REDACTED


def _redact_shared_key(match: re.Match[str]) -> str:
    if PLACEHOLDER.search(match.group("acct")) or not _looks_secret(match.group("val")):
        return match.group(0)
    return match.group("pre") + REDACTED


def _redact_url_password(match: re.Match[str]) -> str:
    value = match.group("val")
    if value.lower() in BENIGN_URL_PASSWORDS or re.fullmatch(r"[*<>{}$]+.*", value):
        return match.group(0)
    return match.group("pre") + REDACTED


def _alias_azure_host(match: re.Match[str]) -> str:
    label = match.group("label")
    if PLACEHOLDER.search(label) or label.lower() in COMMON_AZURE_LABELS:
        return match.group(0)
    if label.lower().startswith("azure-") and re.fullmatch(r"[0-9a-f]{8}", label[6:]):
        return match.group(0)
    return f"azure-{_short_hash(label)}.{match.group('suffix')}"


# Aliases for subscription and tenant IDs are fabricated, not derived from the real value: they
# come from a keyed hash whose random key lives only in this process and is never stored. The same
# real ID maps to the same alias within one run, nobody can recompute an alias from a known real
# ID, and a new run produces new aliases. Version 8 (custom) UUIDs mark an ID as already aliased,
# so running the script again leaves its own output alone.
_ALIAS_KEY = secrets.token_bytes(32)
_ALIAS_UUID_VERSION = 8


def _fabricated_uuid(value: str) -> uuid.UUID:
    digest = hmac.new(_ALIAS_KEY, value.encode("utf-8"), hashlib.sha256).digest()[:16]
    number = int.from_bytes(digest, "big")
    number = (number & ~(0xF << 76)) | (_ALIAS_UUID_VERSION << 76)  # version bits
    number = (number & ~(0x3 << 62)) | (0x2 << 62)  # RFC 4122 variant bits
    return uuid.UUID(int=number)


def _alias_azure_id(match: re.Match[str]) -> str:
    value = match.group("val").lower()
    if len(set(value.replace("-", ""))) <= 2:
        return match.group(0)  # 0000.../1111...: documentation placeholder
    if uuid.UUID(value).version == _ALIAS_UUID_VERSION:
        return match.group(0)  # already an alias, so reruns are stable
    return match.group("pre") + str(_fabricated_uuid(value))


def _alias_email(match: re.Match[str]) -> str:
    local, domain = match.group("local").lower(), match.group("domain").lower()
    if local in BENIGN_EMAIL_LOCALS or domain.endswith(BENIGN_EMAIL_DOMAINS):
        return match.group(0)
    if domain.endswith(".example") or domain == "example":
        return match.group(0)
    return f"user-{_short_hash(match.group(0))}@example.com"


def _profile_replacer(allowed: frozenset[str]) -> Callable[[re.Match[str]], str]:
    def replace(match: re.Match[str]) -> str:
        name = match.group("name")
        if name.lower() in allowed or name.lower() == USER_ALIAS:
            return match.group(0)
        return match.group("pre") + USER_ALIAS

    return replace


Rule = tuple[str, "re.Pattern[str]", Callable[["re.Match[str]"], str]]


class Redactor:
    """Applies the identity aliases and the redaction rules, counting what changed per rule."""

    def __init__(self, identities: Mapping[str, str]) -> None:
        self.counts: Counter[str] = Counter()
        self._aliases = {k.lower(): v for k, v in identities.items() if k}
        keys = sorted(self._aliases, key=len, reverse=True)
        self._identity_pattern = (
            re.compile("|".join(re.escape(k) for k in keys), re.IGNORECASE) if keys else None
        )
        self._rules: list[Rule] = [
            ("private-key", _PRIVATE_KEY, _redact_private_key),
            ("token", _TOKEN, _redact_token),
            ("connection-string", _CONNECTION_STRING, _redact_value),
            ("sas-signature", _SIG_PARAM, _redact_value),
            ("shared-key", _SHARED_KEY, _redact_shared_key),
            ("auth-scheme", _AUTH_SCHEME, _redact_value),
            ("api-key-header", _API_KEY_HEADER, _redact_header),
            ("secret-assignment", _SECRET_ASSIGNMENT, _redact_value),
            ("url-password", _URL_PASSWORD, _redact_url_password),
            ("azure-host", _AZURE_HOST, _alias_azure_host),
            ("azure-id", _AZURE_ID, _alias_azure_id),
            ("email", _EMAIL, _alias_email),
            ("profile-path", _WINDOWS_PROFILE, _profile_replacer(BENIGN_PROFILE_NAMES)),
            ("profile-path", _POSIX_PROFILE, _profile_replacer(BENIGN_PROFILE_NAMES)),
            ("profile-path", _POSIX_HOME, _profile_replacer(BENIGN_HOME_NAMES)),
        ]

    def sanitize(self, text: str) -> str:
        if self._identity_pattern is not None:
            text = self._identity_pattern.sub(self._alias_identity, text)
        for name, pattern, replace in self._rules:
            text = pattern.sub(self._counted(name, replace), text)
        return text

    def sanitize_json(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.sanitize(value)
        if isinstance(value, list):
            return [self.sanitize_json(item) for item in value]
        if isinstance(value, dict):
            return {self.sanitize(k): self._sanitize_member(k, v) for k, v in value.items()}
        return value

    def _sanitize_member(self, key: str, value: Any) -> Any:
        """A secret held under its own JSON key has no ``NAME=`` text around it to match."""
        if isinstance(value, str) and _SECRET_KEY_NAME.search(key) and _looks_secret(value):
            self.counts["secret-field"] += 1
            return REDACTED
        return self.sanitize_json(value)

    def _alias_identity(self, match: re.Match[str]) -> str:
        self.counts["identity"] += 1
        return self._aliases[match.group(0).lower()]

    def _counted(
        self, name: str, replace: Callable[[re.Match[str]], str]
    ) -> Callable[[re.Match[str]], str]:
        def apply(match: re.Match[str]) -> str:
            new = replace(match)
            if new != match.group(0):
                self.counts[name] += 1
            return new

        return apply


def _read_git_identity(root: Path) -> tuple[str, str]:
    parser = configparser.RawConfigParser(strict=False)
    for candidate in (Path.home() / ".gitconfig", root / ".git" / "config"):
        try:
            parser.read(candidate, encoding="utf-8")
        except (OSError, configparser.Error):
            continue
    return parser.get("user", "name", fallback=""), parser.get("user", "email", fallback="")


def detect_identities(root: Path) -> dict[str, str]:
    """Identities of whoever runs this script, so a fresh export needs no configuration."""
    found: dict[str, str] = {}

    def add(value: str, alias: str) -> None:
        value = value.strip().strip("\"'")
        if len(value) >= MIN_IDENTITY_LENGTH:
            found.setdefault(value, alias)

    try:
        user = getpass.getuser()
    except (OSError, KeyError):
        user = ""
    add(user, USER_ALIAS)
    if len(user) > 8:
        add(user[:6] + "~1", USER_ALIAS)  # Windows 8.3 short profile folder name

    name, email = _read_git_identity(root)
    add(name, NAME_ALIAS)
    for part in name.split():
        if len(part) > MIN_IDENTITY_LENGTH:
            add(part, USER_ALIAS)
    add(email, EMAIL_ALIAS)
    add(email.partition("@")[0], USER_ALIAS)
    return found


def load_config(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        identities = data["identities"]
        if not isinstance(identities, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in identities.items()
        ):
            raise TypeError
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError(f'{path} must be {{"identities": {{"real value": "alias"}}}}') from error
    return dict(identities)


def sanitize_file_text(text: str, redactor: Redactor) -> str:
    """Sanitise a JSON document keeping its layout, or raw text if it is not plain JSON."""
    try:
        data = json.loads(text)
    except ValueError:
        return redactor.sanitize(text)
    trailing = "\n" if text.endswith("\n") else ""
    if text != json.dumps(data, indent=2, ensure_ascii=False) + trailing:
        return redactor.sanitize(text)  # unknown layout: edit the raw text, do not reformat
    return json.dumps(redactor.sanitize_json(data), indent=2, ensure_ascii=False) + trailing


def iter_files(paths: Iterable[Path]) -> Iterable[Path]:
    for path in paths:
        if path.is_dir():
            yield from sorted(path.rglob("*.json"))
        else:
            yield path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("paths", nargs="*", type=Path, help="files or folders (default: sessions)")
    parser.add_argument("--check", action="store_true", help="report only; exit 1 if changes")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="identities file")
    parser.add_argument("--no-auto-detect", action="store_true", help="skip OS/git identities")
    args = parser.parse_args(argv)

    root = Path.cwd()
    try:
        identities = {} if args.no_auto_detect else detect_identities(root)
        identities.update(load_config(args.config))
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2

    files = list(iter_files(args.paths or [Path(p) for p in DEFAULT_PATHS]))
    if not files:
        print("No files to check.", file=sys.stderr)
        return 2

    dirty = 0
    for path in files:
        redactor = Redactor(identities)
        try:
            original = path.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError) as error:
            print(f"{path}: cannot read ({error.__class__.__name__})", file=sys.stderr)
            return 2
        updated = sanitize_file_text(original, redactor)
        if updated == original:
            continue
        dirty += 1
        summary = ", ".join(f"{rule}={n}" for rule, n in sorted(redactor.counts.items()))
        print(f"{path}: {summary}")
        if not args.check:
            temp = path.with_name(path.name + ".tmp")
            temp.write_bytes(updated.encode("utf-8"))
            temp.replace(path)

    verb = "need changes" if args.check else "rewritten"
    print(f"{dirty} of {len(files)} file(s) {verb}.")
    return 1 if args.check and dirty else 0


if __name__ == "__main__":
    raise SystemExit(main())
