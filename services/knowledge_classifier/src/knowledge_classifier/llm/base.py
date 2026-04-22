"""Base LLM provider interface."""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class ChatMessage(BaseModel):
    """A chat message for LLM."""
    role: str  # system, user, assistant
    content: str


class LLMResponse(BaseModel):
    """Response from LLM."""
    content: str
    model: str
    usage: dict[str, int] | None = None


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def chat(
        self,
        messages: list[ChatMessage],
        temperature: float = 0.1,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """Send chat messages and get response."""
        pass

    @abstractmethod
    async def chat_with_json(
        self,
        messages: list[ChatMessage],
        schema: type[BaseModel],
        temperature: float = 0.1,
        max_retries: int = 3,
    ) -> tuple[BaseModel, str]:
        """Send chat messages and get structured JSON response.
        
        Returns:
            Tuple of (parsed model, raw response content)
        """
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Get the model name."""
        pass

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Get the provider name."""
        pass
