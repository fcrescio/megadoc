"""Configuration for knowledge classifier service."""

import os
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Knowledge classifier settings."""

    model_config = SettingsConfigDict(env_prefix="KN_", env_file=".env", extra="ignore")

    # LLM Configuration
    llm_endpoint: str = Field(
        default="http://10.89.0.3:8080/v1",
        description="LLM API endpoint (OpenAI-compatible)"
    )
    llm_model: str = Field(default="qwen3.5-27B", description="LLM model name")
    llm_api_key: str | None = Field(default=None, description="LLM API key (optional)")
    llm_timeout: int = Field(default=120, description="LLM request timeout in seconds")
    llm_temperature: float = Field(default=0.1, description="LLM temperature (low for deterministic)")
    llm_max_retries: int = Field(default=3, description="Max retries for LLM requests")

    # Prompt versions
    prompt_version_segmentation: str = Field(default="v1", description="Segmentation prompt version")
    prompt_version_classification: str = Field(default="v1", description="Classification prompt version")
    prompt_version_entity_extraction: str = Field(default="v1", description="Entity extraction prompt version")
    prompt_version_topic_assignment: str = Field(default="v1", description="Topic assignment prompt version")

    # Confidence thresholds
    confidence_threshold_segmentation: float = Field(default=0.7, description="Min confidence for segmentation")
    confidence_threshold_classification: float = Field(default=0.7, description="Min confidence for classification")
    confidence_threshold_topic: float = Field(default=0.6, description="Min confidence for topic assignment")

    # Processing limits
    max_pages_per_segment: int = Field(default=20, description="Max pages per document segment")
    max_topics_to_retrieve: int = Field(default=10, description="Max topics to retrieve as candidates")

    # Celery queue
    celery_queue: str = Field(default="knowledge", description="Celery queue name")

    @property
    def use_mock_llm(self) -> bool:
        """Check if we should use mock LLM provider."""
        return os.getenv("KN_LLM_ENDPOINT", self.llm_endpoint).startswith("mock://")


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
