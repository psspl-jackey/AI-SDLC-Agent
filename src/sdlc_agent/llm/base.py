"""One model interface for every agent, so switching local model <-> Claude is a config change."""
from __future__ import annotations

import json
import re
from typing import Any, Protocol

from pydantic import BaseModel


class LLMResponse(BaseModel):
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


class LLMClient(Protocol):
    name: str

    def complete(self, system: str, prompt: str, *, json_mode: bool = False) -> LLMResponse: ...


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_json(text: str) -> Any:
    """Parse JSON from a model reply, tolerating code fences and leading prose."""
    cleaned = _FENCE.sub("", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        starts = [i for i in (cleaned.find("{"), cleaned.find("[")) if i != -1]
        if not starts:
            raise
        start = min(starts)
        closer = "}" if cleaned[start] == "{" else "]"
        end = cleaned.rfind(closer)
        return json.loads(cleaned[start : end + 1])
