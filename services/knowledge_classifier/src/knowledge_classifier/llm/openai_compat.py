"""OpenAI-compatible LLM provider."""

import json
import logging
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from knowledge_classifier.llm.base import ChatMessage, LLMProvider, LLMResponse

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider(LLMProvider):
    """LLM provider for OpenAI-compatible APIs."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout: int = 120,
    ):
        self.base_url = base_url.rstrip("/")
        self._model = model
        self.api_key = api_key
        self.timeout = timeout
        self._client: httpx.Client | None = None

    def _get_client(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.Client(
                base_url=self.base_url,
                headers=headers,
                timeout=httpx.Timeout(self.timeout),
            )
        return self._client

    def chat(
        self,
        messages: list[ChatMessage],
        temperature: float = 0.1,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """Send chat messages and get response."""
        client = self._get_client()
        
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        
        if response_format:
            payload["response_format"] = response_format

        try:
            logger.debug(f"LLM request payload: {payload.get('messages', [])[:2]}")
            response = client.post("/chat/completions", json=payload)
            logger.debug(f"LLM response status: {response.status_code}, body: {response.text[:200]}")
            response.raise_for_status()
            
            data = response.json()
            choice = data["choices"][0]
            
            return LLMResponse(
                content=choice["message"]["content"],
                model=data.get("model", self._model),
                usage=dict(data.get("usage", {})),
            )
        except httpx.HTTPError as e:
            logger.error(f"LLM request failed: {e}, response: {response.text[:200] if 'response' in dir() else 'N/A'}")
            raise

    def chat_with_json(
        self,
        messages: list[ChatMessage],
        schema: type[BaseModel],
        temperature: float = 0.1,
        max_retries: int = 3,
    ) -> tuple[BaseModel, str]:
        """Send chat messages and get structured JSON response."""
        # Use json_schema without strict mode - qwen3.5-27B doesn't support strict or json_object
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": schema.__name__,
                "schema": schema.model_json_schema(),
            },
        }

        for attempt in range(max_retries):
            try:
                response = self.chat(messages, temperature=temperature, response_format=response_format)
                
                # Try to parse JSON
                content = response.content.strip()
                # Remove markdown code blocks if present
                if content.startswith("```json"):
                    content = content[7:]
                if content.startswith("```"):
                    content = content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()
                
                # Use model_validate with mode='lenient' to handle missing optional fields
                try:
                    parsed = schema.model_validate_json(content)
                except Exception as parse_error:
                    logger.error(f"JSON parse error: {parse_error}, content: {content[:200]}")
                    raise
                return parsed, response.content
                
            except ValidationError as e:
                logger.warning(f"Validation error on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    # Add a retry message
                    retry_messages = messages + [
                        ChatMessage(
                            role="system",
                            content=f"Previous response was invalid. Please ensure valid JSON matching the schema. Error: {str(e)[:200]}",
                        )
                    ]
                    messages = retry_messages
                    continue
                raise
            except json.JSONDecodeError as e:
                logger.warning(f"JSON decode error on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    retry_messages = messages + [
                        ChatMessage(
                            role="system",
                            content="Previous response was not valid JSON. Please output only valid JSON.",
                        )
                    ]
                    messages = retry_messages
                    continue
                raise

        raise RuntimeError(f"Failed to get valid JSON after {max_retries} attempts")

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return "openai-compatible"

    def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            self._client.close()
