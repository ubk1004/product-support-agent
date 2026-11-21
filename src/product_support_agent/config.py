from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="PRODUCT_SUPPORT_",
        extra="ignore",
    )

    environment: Literal["local", "test", "production"] = "local"
    mongodb_uri: SecretStr | None = None
    query_response_retention_enabled: bool = False
    query_response_retention_days: int = Field(default=7, gt=0)
    query_reviewer_role: str | None = None

    @model_validator(mode="after")
    def require_reviewer_for_retention(self) -> "Settings":
        if self.query_response_retention_enabled and not (
            self.query_reviewer_role and self.query_reviewer_role.strip()
        ):
            raise ValueError(
                "PRODUCT_SUPPORT_QUERY_REVIEWER_ROLE is required when "
                "query/response retention is enabled"
            )
        return self
