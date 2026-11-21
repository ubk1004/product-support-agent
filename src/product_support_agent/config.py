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
    catalog_listing_url: str = "https://my.opentext.com/support/products/"
    catalog_search_url: str = "https://my.opentext.com/api/web/support/search-results"
    catalog_feed_url: str = "https://my.opentext.com/api/web/feed/product"
    catalog_max_pages: int = Field(default=20, gt=0)
    catalog_timeout_seconds: float = Field(default=10.0, gt=0)
    catalog_max_response_bytes: int = Field(default=4_194_304, gt=0)
    max_demo_products: int = Field(default=100, gt=0, le=100)
    manifest_seed: str = "approved-demo-v1"
    azurite_queue_connection_string: str | None = None
    ingestion_queue_name: str = "product-ingestion"
    poison_dequeue_count: int = Field(default=5, gt=0)
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
