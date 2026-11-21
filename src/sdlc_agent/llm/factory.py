from __future__ import annotations

from ..config import Settings, get_settings
from .base import LLMClient


def get_llm(settings: Settings | None = None) -> LLMClient:
    s = settings or get_settings()
    if s.model_provider == "anthropic":
        from .anthropic_client import AnthropicClient

        return AnthropicClient(s.anthropic_model, s.max_tokens)
    if s.model_provider == "ollama":
        from .ollama import OllamaClient

        return OllamaClient(s.ollama_url, s.ollama_model, s.max_tokens)
    raise ValueError(f"Unknown MODEL_PROVIDER '{s.model_provider}'. Use 'ollama' or 'anthropic'.")
