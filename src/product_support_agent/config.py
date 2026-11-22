from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
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
    manifest_path: str = "docs/operations/phase-2-product-manifest-v1.json"
    source_map_path: str = "docs/operations/phase-3-source-map-v1.json"
    source_user_agent: str = "product-support-agent/0.1 (demo documentation indexer)"
    source_request_budget: int = Field(default=400, gt=0, le=2_000)
    source_min_request_interval_seconds: float = Field(default=1.0, ge=1.0)
    source_max_retry_after_seconds: float = Field(default=60.0, gt=0)
    source_success_freshness_hours: float = Field(default=24.0, gt=0)
    source_transient_failure_backoff_hours: float = Field(default=24.0, gt=0)
    source_permanent_failure_backoff_days: float = Field(default=30.0, gt=0)
    source_fail_fast_consecutive_failures: int = Field(default=3, gt=0)
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


class ModelAndSearchSettings(BaseSettings):
    """Foundry and Azure AI Search settings, using the variable names in `.env.example`.

    `embedding_base_url` points at Foundry now and at the LiteLLM gateway later; the
    embedding client only needs an OpenAI-compatible `/embeddings` endpoint.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    embedding_base_url: str = Field(
        validation_alias=AliasChoices(
            "PRODUCT_SUPPORT_EMBEDDING_BASE_URL", "AZURE_OPENAI_EMBEDDING_ENDPOINT"
        )
    )
    embedding_api_key: SecretStr = Field(
        validation_alias=AliasChoices("PRODUCT_SUPPORT_EMBEDDING_API_KEY", "AZURE_OPENAI_API_KEY")
    )
    embedding_deployment: str = Field(validation_alias="AZURE_OPENAI_EMBEDDING_DEPLOYMENT")
    embedding_model_version: str = Field(
        validation_alias="PRODUCT_SUPPORT_SEARCH_EMBEDDING_MODEL_VERSION"
    )
    embedding_dimensions: int = Field(
        gt=0, validation_alias="PRODUCT_SUPPORT_SEARCH_EMBEDDING_DIMENSIONS"
    )
    search_endpoint: str = Field(
        validation_alias=AliasChoices("PRODUCT_SUPPORT_SEARCH_ENDPOINT", "AZURE_AI_SEARCH_ENDPOINT")
    )
    search_key: SecretStr = Field(
        validation_alias=AliasChoices("PRODUCT_SUPPORT_SEARCH_ADMIN_KEY", "AZURE_AI_SEARCH_API_KEY")
    )
    demo_index_base: str = Field(
        default="product-support-demo", validation_alias="PRODUCT_SUPPORT_SEARCH_DEMO_INDEX_BASE"
    )
    test_index_base: str = Field(
        default="product-support-test", validation_alias="PRODUCT_SUPPORT_SEARCH_TEST_INDEX_BASE"
    )
