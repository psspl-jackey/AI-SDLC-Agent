"""Ask a model for JSON and get back data of the shape the agent expects.

Small local models often reply with broken JSON, or with the right content in the wrong shape:
a bare list instead of {"tasks": [...]}, "REQ-001, REQ-002" instead of ["REQ-001", "REQ-002"],
or plain strings where objects were asked for. Iterating a string id character by character, or
calling .get() on a string, would crash a whole stage. complete_json() retries once on invalid
JSON (telling the model what was wrong) and coerces the reply to a declared shape, so agents only
ever see well-formed data.

A shape maps each top-level key to:
    "str"                  a string ("" when missing)
    "strs"                 a list of strings; a single string is split on commas
    "bool"                 a boolean; "false", "no", "0" and "" are False (bool("false") would be True)
    "any"                  passed through unchanged
    Dicts(sub, text_key)   a list of objects; each object's keys are coerced by `sub`;
                           with text_key, a bare string item becomes {text_key: item}
Keys not in the shape are passed through unchanged.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .base import LLMClient, parse_json


@dataclass(frozen=True)
class Dicts:
    sub: dict[str, Any] = field(default_factory=dict)
    text_key: str | None = None


def _strs(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if v is not None and not isinstance(v, (dict, list)) and str(v).strip()]
    return [str(value)]


def _bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "y", "1", "included", "include")
    return bool(value)


def _dicts(value: Any, spec: Dicts) -> list[dict]:
    if value is None:
        return []
    if isinstance(value, dict):  # one object instead of a list of them
        value = [value]
    if not isinstance(value, list):
        value = [value]
    out = []
    for item in value:
        if isinstance(item, str) and spec.text_key and item.strip():
            item = {spec.text_key: item.strip()}
        if isinstance(item, dict):
            out.append(coerce(item, spec.sub))
    return out


def coerce(data: dict, shape: dict[str, Any]) -> dict:
    out = dict(data)
    for key, spec in shape.items():
        value = data.get(key)
        if spec == "str":
            out[key] = "" if value is None else value if isinstance(value, str) else (
                json.dumps(value) if isinstance(value, (dict, list)) else str(value))
        elif spec == "strs":
            out[key] = _strs(value)
        elif spec == "bool":
            out[key] = _bool(value)
        elif isinstance(spec, Dicts):
            out[key] = _dicts(value, spec)
    return out


def _to_dict(data: Any, shape: dict[str, Any]) -> dict | None:
    if isinstance(data, dict):
        return data
    list_keys = [k for k, v in shape.items() if isinstance(v, Dicts)]
    if isinstance(data, list) and len(list_keys) == 1:  # bare list for a one-list reply
        return {list_keys[0]: data}
    return None


def complete_json(llm: LLMClient, system: str, prompt: str, shape: dict[str, Any], *, retries: int = 1) -> dict:
    attempt_prompt = prompt
    last_error = ""
    for _ in range(retries + 1):
        text = llm.complete(system, attempt_prompt, json_mode=True).text
        try:
            data = _to_dict(parse_json(text), shape)
            if data is not None:
                return coerce(data, shape)
            last_error = f"expected a JSON object with keys {', '.join(shape)}, got {type(parse_json(text)).__name__}"
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = f"invalid JSON ({exc})"
        attempt_prompt = (f"{prompt}\n\nYour previous reply could not be used: {last_error}. "
                          "Reply again with only the JSON object, no other text.")
    raise ValueError(f"Model reply unusable after {retries + 1} attempt(s): {last_error}. Reply began: {text[:200]!r}")
