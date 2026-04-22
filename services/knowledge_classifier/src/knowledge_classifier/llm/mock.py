"""Mock deterministic LLM provider for testing."""

import logging
import re
from typing import Any

from pydantic import BaseModel

from knowledge_classifier.llm.base import ChatMessage, LLMProvider, LLMResponse

logger = logging.getLogger(__name__)


class MockDeterministicProvider(LLMProvider):
    """Deterministic mock LLM provider for testing."""

    def __init__(self, model: str = "mock-model"):
        self._model = model

    async def chat(
        self,
        messages: list[ChatMessage],
        temperature: float = 0.1,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """Return deterministic mock response."""
        # Extract user message
        user_messages = [m.content for m in messages if m.role == "user"]
        if not user_messages:
            return LLMResponse(content="{}", model=self._model)
        
        user_text = " ".join(user_messages)
        
        # Generate deterministic response based on input
        response = self._generate_mock_response(user_text, response_format)
        
        return LLMResponse(
            content=response,
            model=self._model,
            usage={"prompt_tokens": len(user_text) // 4, "completion_tokens": len(response) // 4},
        )

    async def chat_with_json(
        self,
        messages: list[ChatMessage],
        schema: type[BaseModel],
        temperature: float = 0.1,
        max_retries: int = 3,
    ) -> tuple[BaseModel, str]:
        """Return deterministic mock JSON response."""
        user_messages = [m.content for m in messages if m.role == "user"]
        if not user_messages:
            user_text = ""
        else:
            user_text = " ".join(user_messages)
        
        # Generate mock response based on schema and input
        mock_data = self._generate_mock_json(schema, user_text)
        json_str = schema(**mock_data).model_dump_json()
        
        return schema(**mock_data), json_str

    def _generate_mock_response(self, user_text: str, response_format: dict | None) -> str:
        """Generate a mock response based on input."""
        if response_format and response_format.get("type") == "json_schema":
            return self._generate_mock_json_from_text(user_text)
        
        # Default text response
        return f"Mock response for: {user_text[:100]}"

    def _generate_mock_json(self, schema: type[BaseModel], user_text: str) -> dict[str, Any]:
        """Generate mock JSON data matching schema."""
        mock_data: dict[str, Any] = {}
        
        for field_name, field_info in schema.model_fields.items():
            field_type = field_info.annotation
            
            # Handle different types
            if field_type == str:
                mock_data[field_name] = f"mock_{field_name}"
            elif field_type == int:
                mock_data[field_name] = 42
            elif field_type == float:
                mock_data[field_name] = 0.85
            elif field_type == bool:
                mock_data[field_name] = True
            elif field_type == list:
                mock_data[field_name] = [f"item_{i}" for i in range(2)]
            elif field_type == dict:
                mock_data[field_name] = {"key": "value"}
            elif hasattr(field_type, "__origin__") and field_type.__origin__ is list:
                # Generic list type
                mock_data[field_name] = [f"item_{i}" for i in range(2)]
            elif hasattr(field_type, "__origin__") and field_type.__origin__ is dict:
                mock_data[field_name] = {"key": "value"}
            elif hasattr(field_type, "model_construct"):
                # Nested Pydantic model
                mock_data[field_name] = self._generate_nested_mock(field_type)
            elif field_name.endswith("_id"):
                mock_data[field_name] = "550e8400-e29b-41d4-a716-446655440000"
            elif field_name == "confidence" or field_name == "score":
                mock_data[field_name] = 0.85
            elif field_name == "status":
                mock_data[field_name] = "pending"
            elif field_name == "action":
                mock_data[field_name] = "assign_existing"
            else:
                mock_data[field_name] = None

        return mock_data

    def _generate_nested_mock(self, schema: type) -> dict[str, Any]:
        """Generate mock data for nested model."""
        mock_data = {}
        for field_name in dir(schema):
            if not field_name.startswith("_"):
                mock_data[field_name] = f"mock_{field_name}"
        return mock_data

    def _generate_mock_json_from_text(self, user_text: str) -> str:
        """Generate mock JSON based on text content."""
        # Detect intent from text
        if "segment" in user_text.lower() or "boundary" in user_text.lower():
            return '{"segments": [{"start_page": 1, "end_page": 3, "confidence": 0.9, "rationale": "Clear document boundary"}], "overall_confidence": 0.9, "boundaries": []}'
        elif "classify" in user_text.lower() or "type" in user_text.lower():
            return '{"primary_type": {"type_code": "verbale_assemblea", "confidence": 0.95, "salient_features": ["verbale", "assemblea"]}, "alternatives": [], "rationale": "Clear meeting minutes"}'
        elif "entity" in user_text.lower() or "extract" in user_text.lower():
            return '{"entities": [{"entity_type": "condominio", "entity_value": "Condominio Via Roma", "confidence": 0.9}], "summary": "Document about condominium"}'
        elif "topic" in user_text.lower():
            return '{"action": "assign_existing", "topic_ids": ["550e8400-e29b-41d4-a716-446655440000"], "assignment_roles": ["primary"], "confidence": 0.85, "rationale": "Matches existing topic"}'
        
        return "{}"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return "mock-deterministic"
