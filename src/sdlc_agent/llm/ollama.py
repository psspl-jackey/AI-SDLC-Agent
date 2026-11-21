"""Free local model through Ollama."""
from __future__ import annotations

import httpx

from .base import LLMResponse


class OllamaClient:
    def __init__(self, url: str, model: str, max_tokens: int = 4096, num_ctx: int = 16384):
        self.name = f"ollama:{model}"
        self._url = url.rstrip("/")
        self._model = model
        self._max_tokens = max_tokens
        self._num_ctx = num_ctx

    def complete(self, system: str, prompt: str, *, json_mode: bool = False) -> LLMResponse:
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "options": {"num_ctx": self._num_ctx, "num_predict": self._max_tokens, "temperature": 0.2},
        }
        if json_mode:
            body["format"] = "json"
        try:
            resp = httpx.post(f"{self._url}/api/chat", json=body, timeout=600)
        except httpx.ConnectError as exc:
            raise RuntimeError(f"Ollama is not running at {self._url}. Start it with: ollama serve") from exc
        if resp.status_code == 404:
            raise RuntimeError(f"Ollama model '{self._model}' is not pulled. Run: ollama pull {self._model}")
        resp.raise_for_status()
        data = resp.json()
        return LLMResponse(
            text=data["message"]["content"],
            model=self.name,
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
        )
