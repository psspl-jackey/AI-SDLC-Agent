"""Tracing and cost meter: every model call is logged per project as one JSON line."""
from __future__ import annotations

import json
import time
from pathlib import Path

from .config import Settings
from .llm.base import LLMClient, LLMResponse
from .state.models import now


class Tracer:
    def __init__(self, settings: Settings):
        self.dir = settings.traces_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self._cin = settings.cost_input_per_mtok
        self._cout = settings.cost_output_per_mtok

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self._cin + output_tokens * self._cout) / 1_000_000

    def record(self, project_id: str, event: dict) -> None:
        event = {"at": now().isoformat(), **event}
        with (self.dir / f"{project_id}.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, default=str) + "\n")

    def read(self, project_id: str) -> list[dict]:
        path = self.dir / f"{project_id}.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def totals(self, project_id: str) -> dict:
        events = [e for e in self.read(project_id) if e.get("type") == "llm_call"]
        return {
            "calls": len(events),
            "input_tokens": sum(e.get("input_tokens", 0) for e in events),
            "output_tokens": sum(e.get("output_tokens", 0) for e in events),
            "cost_usd": round(sum(e.get("cost_usd", 0.0) for e in events), 4),
        }


class TracedLLM:
    """Wraps any LLMClient so each call is traced under a project and agent name."""

    def __init__(self, inner: LLMClient, tracer: Tracer, project_id: str, agent: str):
        self.inner, self.tracer, self.project_id, self.agent = inner, tracer, project_id, agent
        self.name = inner.name

    def complete(self, system: str, prompt: str, *, json_mode: bool = False) -> LLMResponse:
        started = time.perf_counter()
        try:
            resp = self.inner.complete(system, prompt, json_mode=json_mode)
        except Exception as exc:
            self.tracer.record(self.project_id, {
                "type": "llm_error", "agent": self.agent, "model": self.inner.name, "error": repr(exc),
            })
            raise
        self.tracer.record(self.project_id, {
            "type": "llm_call",
            "agent": self.agent,
            "model": resp.model,
            "ms": round((time.perf_counter() - started) * 1000),
            "input_tokens": resp.input_tokens,
            "output_tokens": resp.output_tokens,
            "cost_usd": self.tracer.cost(resp.input_tokens, resp.output_tokens),
            "prompt_preview": prompt[:400],
            "response_preview": resp.text[:400],
        })
        return resp
