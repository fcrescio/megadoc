"""OpenAI-compatible LLM provider."""

import json
import logging
import re
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
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
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

        response: httpx.Response | None = None
        try:
            logger.debug("LLM request payload prepared with %s messages", len(payload["messages"]))
            response = client.post("/chat/completions", json=payload)
            logger.debug("LLM response status: %s", response.status_code)
            response.raise_for_status()

            data = response.json()
            choice = data["choices"][0]

            return LLMResponse(
                content=choice["message"]["content"],
                model=data.get("model", self._model),
                usage=self._normalize_usage(data.get("usage")),
            )
        except httpx.HTTPError as e:
            logger.error(
                "LLM request failed: %s, response: %s",
                e,
                response.text[:500] if response is not None else "N/A",
            )
            raise

    def chat_with_json(
        self,
        messages: list[ChatMessage],
        schema: type[BaseModel],
        temperature: float = 0.1,
        max_retries: int = 3,
    ) -> tuple[BaseModel, str]:
        """Send chat messages and get structured JSON response."""
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": schema.__name__,
                "schema": schema.model_json_schema(),
            },
        }
        base_messages = list(messages)
        use_response_format = True
        retry_messages = list(base_messages)

        for attempt in range(max_retries):
            try:
                response = self.chat(
                    retry_messages,
                    temperature=temperature,
                    response_format=response_format if use_response_format else None,
                )
                content = self._extract_json_text(response.content)
                parsed = schema.model_validate_json(content)
                return parsed, response.content

            except httpx.HTTPStatusError as e:
                if (
                    use_response_format
                    and e.response is not None
                    and e.response.status_code >= 500
                    and attempt < max_retries - 1
                ):
                    logger.warning(
                        "Structured output failed with status %s, retrying without response_format",
                        e.response.status_code,
                    )
                    use_response_format = False
                    retry_messages = self._build_json_retry_messages(base_messages, schema)
                    continue
                raise

            except (ValidationError, json.JSONDecodeError, ValueError) as e:
                logger.warning("JSON validation failed on attempt %s: %s", attempt + 1, e)
                if attempt < max_retries - 1:
                    use_response_format = False
                    retry_messages = self._build_json_retry_messages(base_messages, schema)
                    continue
                raise

        raise RuntimeError(f"Failed to get valid JSON after {max_retries} attempts")

    def _normalize_usage(self, usage: Any) -> dict[str, Any] | None:
        """Normalize usage metadata from OpenAI-compatible providers."""
        if usage is None:
            return None
        if isinstance(usage, dict):
            return dict(usage)
        return {"raw": usage}

    def _extract_json_text(self, content: str) -> str:
        """Extract the JSON object from a model response."""
        cleaned = content.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        if cleaned.startswith("{") or cleaned.startswith("["):
            return cleaned

        match = re.search(r"(\{.*\}|\[.*\])", cleaned, re.DOTALL)
        if match:
            return match.group(1).strip()

        raise ValueError("No JSON object found in LLM response")

    def _build_json_retry_messages(
        self,
        messages: list[ChatMessage],
        schema: type[BaseModel],
    ) -> list[ChatMessage]:
        """Retry without structured output using an explicit JSON-only instruction."""
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=True)
        reminder = (
            "Return only valid JSON matching this JSON Schema. "
            f"Do not include markdown fences or prose.\nSchema:\n{schema_json}"
        )
        return [*messages, ChatMessage(role="user", content=reminder)]

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
