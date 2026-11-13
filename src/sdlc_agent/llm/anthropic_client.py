"""Claude through the Anthropic API (paid). Reads ANTHROPIC_API_KEY from the environment."""
from __future__ import annotations

from .base import LLMResponse


class AnthropicClient:
    def __init__(self, model: str, max_tokens: int = 4096):
        from anthropic import Anthropic  # imported lazily so the local-only setup needs no key

        self.name = f"anthropic:{model}"
        self._client = Anthropic()
        self._model = model
        self._max_tokens = max_tokens

    def complete(self, system: str, prompt: str, *, json_mode: bool = False) -> LLMResponse:
        if json_mode:
            system = system + "\n\nRespond with a single valid JSON object only, no prose and no code fences."
        msg = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in msg.content if getattr(block, "type", "") == "text")
        return LLMResponse(
            text=text,
            model=self.name,
            input_tokens=msg.usage.input_tokens,
            output_tokens=msg.usage.output_tokens,
        )
