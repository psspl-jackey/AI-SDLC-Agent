"""Eval runner: score Stage 0-1 output against a sample's answer key.

An answer key (samples/*.answers.yaml) lists the gaps planted in a sample input and the
requirements a senior analyst would extract. Each item carries match terms; matching is plain
code (no LLM judge), so scores are reproducible and comparable across models and prompt versions.

Match rule: `match` is a list of term groups. An item matches a text when every group has at
least one term that appears in the text at the start of a word (case-insensitive), so "notif"
matches "notifications" and "fast" does not match "breakfast".

Usage:
    python -m sdlc_agent.evals samples/ecommerce_brief.answers.yaml [more keys...]
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .state.models import Gap, Project, RawInput

# ---------- answer keys ----------


@dataclass(frozen=True)
class KeyItem:
    id: str
    text: str
    match: tuple[tuple[str, ...], ...]
    type: str = ""

    def matches(self, haystack: str) -> bool:
        return all(any(_has_term(haystack, t) for t in group) for group in self.match)


@dataclass(frozen=True)
class AnswerKey:
    name: str
    input: RawInput
    intake_answers: dict[str, str]
    gaps: tuple[KeyItem, ...]
    requirements: tuple[KeyItem, ...]
    also_valid: tuple[KeyItem, ...] = ()
    path: Path | None = None


def _has_term(haystack: str, term: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(term.lower()), haystack.lower()) is not None


def _items(raw: list | None, section: str, path: Path) -> tuple[KeyItem, ...]:
    items = []
    for i, entry in enumerate(raw or [], start=1):
        groups = entry.get("match")
        if not groups or not all(isinstance(g, list) and g for g in groups):
            raise ValueError(f"{path}: {section} item {i} needs 'match' as a list of non-empty term lists")
        items.append(KeyItem(
            id=str(entry.get("id") or f"{section[:3].upper()}-{i}"),
            text=str(entry.get("text", "")),
            type=str(entry.get("type", "")),
            match=tuple(tuple(str(t) for t in g) for g in groups),
        ))
    ids = [it.id for it in items]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path}: duplicate ids in {section}")
    return tuple(items)


def load_key(path: Path) -> AnswerKey:
    path = Path(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    inp = data.get("input") or {}
    kind, value = inp.get("kind"), inp.get("value")
    if kind not in ("text", "file", "url") or not value:
        raise ValueError(f"{path}: 'input' needs kind (text, file or url) and value")
    if kind == "file":
        value = str((path.parent / value).resolve())
    return AnswerKey(
        name=str(data.get("name") or path.stem),
        input=RawInput(kind=kind, value=value),
        intake_answers={str(k): str(v) for k, v in (data.get("intake_answers") or {}).items() if v is not None},
        gaps=_items(data.get("gaps"), "gaps", path),
        requirements=_items(data.get("requirements"), "requirements", path),
        also_valid=_items(data.get("also_valid"), "also_valid", path),
        path=path,
    )


# ---------- scoring ----------


@dataclass
class EvalResult:
    key: str
    found: dict[str, list[str]] = field(default_factory=dict)  # planted gap id -> matching GAP ids
    missed: list[str] = field(default_factory=list)  # planted gap ids
    req_found: dict[str, list[str]] = field(default_factory=dict)  # expected requirement id -> REQ ids
    req_missed: list[str] = field(default_factory=list)
    also_valid_gaps: list[str] = field(default_factory=list)  # GAP ids not planted but known-valid
    unmatched_gaps: list[str] = field(default_factory=list)  # GAP ids to review: real or false?
    total_gaps: int = 0
    total_requirements: int = 0
    coverage_passed: bool = False
    run: dict = field(default_factory=dict)  # model, calls, tokens, cost, seconds

    @property
    def gap_recall(self) -> float:
        n = len(self.found) + len(self.missed)
        return len(self.found) / n if n else 0.0

    @property
    def requirement_recall(self) -> float:
        n = len(self.req_found) + len(self.req_missed)
        return len(self.req_found) / n if n else 0.0


def _gap_text(project: Project, gap: Gap) -> str:
    """A gap's description plus its client question, so either wording can match."""
    questions = [q.text for q in project.questions if q.related_gap_id == gap.id]
    return " ".join([gap.description, *questions])


def score(project: Project, key: AnswerKey) -> EvalResult:
    from .gaps.register import coverage_check

    result = EvalResult(key=key.name, total_gaps=len(project.gaps), total_requirements=len(project.requirements))
    gap_texts = {g.id: _gap_text(project, g) for g in project.gaps}

    matched_gap_ids: set[str] = set()
    for item in key.gaps:
        hits = [gid for gid, text in gap_texts.items() if item.matches(text)]
        if hits:
            result.found[item.id] = hits
            matched_gap_ids.update(hits)
        else:
            result.missed.append(item.id)

    for item in key.requirements:
        hits = [r.id for r in project.requirements if item.matches(r.text)]
        if hits:
            result.req_found[item.id] = hits
        else:
            result.req_missed.append(item.id)

    for gid, text in gap_texts.items():
        if gid in matched_gap_ids:
            continue
        if any(item.matches(text) for item in key.also_valid):
            result.also_valid_gaps.append(gid)
        else:
            result.unmatched_gaps.append(gid)

    result.coverage_passed = coverage_check(project).passed
    return result


# ---------- running ----------


def run_sample(deps, key: AnswerKey) -> tuple[Project, EvalResult]:
    """Run Stage 0 and Stage 1 on the key's input, answering intake from the key, then score."""
    from .orchestrator import finish_intake, run_stage1, start_intake

    started = time.perf_counter()
    project = deps.store.create(f"eval: {key.name}")
    start_intake(deps, project, [key.input.model_copy()])
    finish_intake(deps, project, key.intake_answers)
    project = run_stage1(deps, project.id)
    result = score(project, key)
    result.run = {
        "project_id": project.id,
        "model": deps.llm.name if hasattr(deps.llm, "name") else "",
        "seconds": round(time.perf_counter() - started, 1),
        **deps.tracer.totals(project.id),
    }
    return project, result


def report_markdown(project: Project, key: AnswerKey, result: EvalResult) -> str:
    gaps = {g.id: g for g in project.gaps}
    reqs = {r.id: r for r in project.requirements}
    run = result.run
    lines = [
        f"# Eval: {key.name}",
        "",
        f"- Model: {run.get('model', '')}; {run.get('calls', 0)} calls, "
        f"{run.get('input_tokens', 0)} in / {run.get('output_tokens', 0)} out tokens, "
        f"${run.get('cost_usd', 0)}; {run.get('seconds', 0)} s",
        f"- Project: {run.get('project_id', project.id)}",
        f"- Planted gaps found: **{len(result.found)} / {len(key.gaps)}** ({result.gap_recall:.0%})",
        f"- Expected requirements found: **{len(result.req_found)} / {len(key.requirements)}** "
        f"({result.requirement_recall:.0%})",
        f"- Gaps raised: {result.total_gaps} (matched a planted gap: {result.total_gaps - len(result.also_valid_gaps) - len(result.unmatched_gaps)}, "
        f"known-valid extra: {len(result.also_valid_gaps)}, to review: {len(result.unmatched_gaps)})",
        f"- Gate 1 coverage check: {'passed' if result.coverage_passed else 'FAILED'}",
        "",
        "## Planted gaps",
        "",
        "| | Planted gap | Matched by |",
        "| --- | --- | --- |",
    ]
    for item in key.gaps:
        hits = result.found.get(item.id, [])
        mark = "found" if hits else "**missed**"
        lines.append(f"| {mark} | {item.id}: {item.text} | " + "<br>".join(
            f"{gid}: {gaps[gid].description}" for gid in hits) + " |")
    lines += ["", "## Expected requirements", "", "| | Requirement | Matched by |", "| --- | --- | --- |"]
    for item in key.requirements:
        hits = result.req_found.get(item.id, [])
        mark = "found" if hits else "**missed**"
        lines.append(f"| {mark} | {item.id}: {item.text} | " + "<br>".join(
            f"{rid}: {reqs[rid].text}" for rid in hits) + " |")
    lines += ["", "## Gaps not in the answer key (review: real gap or false gap?)", ""]
    lines += [f"- {gid} [{gaps[gid].source.value}]: {gaps[gid].description}" for gid in result.unmatched_gaps] or ["- none"]
    lines += ["", "## Known-valid extra gaps", ""]
    lines += [f"- {gid} [{gaps[gid].source.value}]: {gaps[gid].description}" for gid in result.also_valid_gaps] or ["- none"]
    return "\n".join(lines) + "\n"


def summary_line(key: AnswerKey, result: EvalResult) -> str:
    return (
        f"{key.name}: gaps {len(result.found)}/{len(key.gaps)} ({result.gap_recall:.0%}), "
        f"requirements {len(result.req_found)}/{len(key.requirements)} ({result.requirement_recall:.0%}), "
        f"to review {len(result.unmatched_gaps)}, coverage {'ok' if result.coverage_passed else 'FAILED'}, "
        f"{result.run.get('calls', 0)} calls, ${result.run.get('cost_usd', 0)}, {result.run.get('seconds', 0)} s"
    )


def main(argv: list[str] | None = None, deps=None) -> int:
    from .config import get_settings
    from .orchestrator import Deps

    parser = argparse.ArgumentParser(description="Score Stage 0-1 output against sample answer keys.")
    parser.add_argument("keys", nargs="+", type=Path, help="answer key files (samples/*.answers.yaml)")
    args = parser.parse_args(argv)

    if deps is None:
        settings = get_settings()
        # Eval projects live apart from dashboard projects.
        deps = Deps(settings=dataclasses.replace(settings, data_dir=settings.data_dir / "evals"))
    out_dir = deps.settings.data_dir / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")

    failed = 0
    for key_path in args.keys:
        key = load_key(key_path)
        try:
            project, result = run_sample(deps, key)
        except Exception as exc:  # keep going so one bad sample does not hide the others
            failed += 1
            print(f"{key.name}: run failed: {exc!r}", file=sys.stderr)
            continue
        base = out_dir / f"{stamp}-{key.name}"
        base.with_suffix(".md").write_text(report_markdown(project, key, result), encoding="utf-8")
        base.with_suffix(".json").write_text(json.dumps({
            **dataclasses.asdict(result),
            "gap_recall": result.gap_recall,
            "requirement_recall": result.requirement_recall,
        }, indent=2), encoding="utf-8")
        print(summary_line(key, result))
        print(f"  report: {base.with_suffix('.md')}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
