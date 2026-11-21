import pytest
from pydantic import ValidationError

from product_support_agent.config import Settings


def test_query_response_retention_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "PRODUCT_SUPPORT_QUERY_RESPONSE_RETENTION_ENABLED",
        "PRODUCT_SUPPORT_QUERY_RESPONSE_RETENTION_DAYS",
        "PRODUCT_SUPPORT_QUERY_REVIEWER_ROLE",
    ):
        monkeypatch.delenv(key, raising=False)

    settings = Settings(_env_file=None)

    assert settings.query_response_retention_enabled is False
    assert settings.query_response_retention_days == 7


def test_retention_requires_a_reviewer_role() -> None:
    with pytest.raises(ValidationError, match="QUERY_REVIEWER_ROLE is required"):
        Settings(
            _env_file=None,
            query_response_retention_enabled=True,
            query_reviewer_role=" ",
        )


def test_retention_period_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, query_response_retention_days=0)
