"""Stage 8 QA and release: test cases, security scan, release checklist, and the Gate 4 check.

- Test cases are the model's job (QA agent): integration, end-to-end and security cases per
  requirement, written from the design. Code drops unknown requirement ids and numbers the cases.
  Until a sandbox runs them, people execute them and record results on the dashboard.
- The security scan is code, run on the merged code in develop: secrets, debuggable builds, insecure
  network settings, plain-HTTP endpoints, eval, disabled TLS verification, weak hashes.
- The release checklist is code, per included platform (store submission prep and go-live basics).
- The Gate 4 check is code: every case has a result (failures fixed or waived with a note), every
  functional requirement has a passing case, no high-severity finding, checklist complete.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..build.git_host import SECRET_PATTERNS
from ..llm.base import LLMClient
from ..llm.json_call import Dicts, complete_json
from ..state.models import ChecklistItem, Project, Release, SecurityFinding, TestCase
from ..state.store import next_id

NAME = "qa"
BATCH = 8

SYSTEM = """You are a QA engineer at a software company. For each requirement you get, write the test
cases a tester runs before release: end-to-end cases through the screens, integration cases against
the API, and security cases where the requirement touches login, personal data or payment. Each case
has short numbered steps and one expected result. Payment uses the dummy gateway with static
responses; test both its success and failure responses."""
SHAPE = {"test_cases": Dicts({"title": "str", "kind": "str", "platform": "str", "requirement_ids": "strs",
                              "steps": "strs", "expected": "str"}, text_key="title")}
SCHEMA = ('Return JSON: {"test_cases": [{"title": str, "kind": "integration" | "e2e" | "security", '
          '"platform": str, "requirement_ids": [str], "steps": [str], "expected": str}]}')


def run(llm: LLMClient, project: Project) -> dict:
    reqs = [r for r in project.active_requirements() if r.kind == "functional"]
    d = project.design
    platforms = ", ".join(x.platform for x in project.platform_matrix.included()) if project.platform_matrix else ""
    replies = []
    for i in range(0, len(reqs), BATCH):
        batch = reqs[i:i + BATCH]
        ids = {r.id for r in batch}
        lines = []
        for r in batch:
            screens = [s.name for s in d.screens if r.id in s.requirement_ids] if d else []
            apis = [f"{e.method} {e.path}" for e in d.endpoints if r.id in e.requirement_ids] if d else []
            lines.append(f"{r.id}: {r.text}" + (f" | screens: {', '.join(screens)}" if screens else "")
                         + (f" | API: {', '.join(apis)}" if apis else ""))
        nfrs = "\n".join(f"{r.id}: {r.text}" for r in project.active_requirements() if r.kind == "nfr") or "(none)"
        replies.append(complete_json(
            llm, SYSTEM,
            f"Platforms: {platforms}\n\nRequirements:\n" + "\n".join(lines)
            + f"\n\nNon-functional requirements:\n{nfrs}\n\n{SCHEMA}",
            SHAPE,
        ) | {"_ids": sorted(ids)})
    return {"batches": replies}


def build_test_cases(project: Project, result: dict) -> tuple[list[TestCase], list[str]]:
    notes: list[str] = []
    req_ids = {r.id for r in project.active_requirements()}
    cases: list[TestCase] = []
    for batch in result.get("batches", []):
        for tc in batch.get("test_cases", []):
            if not tc.get("title", "").strip():
                continue
            ids = [i for i in tc.get("requirement_ids", []) if i in req_ids]
            kind = tc.get("kind", "").lower().replace("-", "").replace(" ", "")
            kind = {"endtoend": "e2e"}.get(kind, kind)
            if kind not in ("integration", "e2e", "security"):
                notes.append(f"QA: case \"{tc['title']}\" had kind '{tc.get('kind')}'; filed as e2e")
                kind = "e2e"
            cases.append(TestCase(id=next_id("TC", (c.id for c in cases)), title=tc["title"].strip(), kind=kind,
                                  platform=tc.get("platform", ""), requirement_ids=ids, steps=tc.get("steps", []),
                                  expected=tc.get("expected", "")))
    return cases, notes


# ---------- security scan (code) ----------

_SCAN_RULES: list[tuple[str, str, re.Pattern, re.Pattern | None]] = [
    # (severity, rule, pattern, only for paths matching)
    ("high", "Android build is debuggable", re.compile(r'android:debuggable\s*=\s*"true"'), re.compile(r"\.xml$")),
    ("medium", "iOS allows arbitrary network loads", re.compile(r"NSAllowsArbitraryLoads</key>\s*<true\s*/>"), None),
    ("medium", "Plain HTTP endpoint", re.compile(r"http://(?!localhost|127\.0\.0\.1|10\.|0\.0\.0\.0|schemas\.|www\.w3\.org|xml\.)[\w.-]+"), None),
    ("medium", "TLS verification disabled", re.compile(r"verify\s*=\s*False|rejectUnauthorized\s*:\s*false|"
                                                       r"NODE_TLS_REJECT_UNAUTHORIZED|badCertificateCallback"), None),
    ("medium", "Dynamic code execution", re.compile(r"\beval\s*\("), re.compile(r"\.(js|ts|jsx|tsx|py)$")),
    ("low", "Weak hash (MD5/SHA-1)", re.compile(r"\b(md5|sha1)\b", re.IGNORECASE), re.compile(r"\.(js|ts|py|kt|java|swift|dart)$")),
]
_BINARY = re.compile(r"\.(png|jpg|jpeg|gif|webp|ico|pdf|zip|jar|aab|apk|ipa|ttf|otf|woff2?)$", re.IGNORECASE)


def security_scan(files: dict[str, str]) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []
    for path, content in sorted(files.items()):
        if _BINARY.search(path):
            continue
        for no, line in enumerate(content.splitlines(), start=1):
            for pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    findings.append(SecurityFinding(severity="high", rule="Possible secret in code", path=path,
                                                    line=no, excerpt=line.strip()[:20] + "..."))
            for severity, rule, pattern, only in _SCAN_RULES:
                if (only is None or only.search(path)) and pattern.search(line):
                    findings.append(SecurityFinding(severity=severity, rule=rule, path=path, line=no,
                                                    excerpt=line.strip()[:120]))
    return findings


# ---------- release checklist (code) ----------

CHECKLISTS = {
    "android": [
        "Signed release App Bundle (.aab) built in CI with the upload key from the CI secret store",
        "Play Console listing: title, descriptions, screenshots, feature graphic, category",
        "Privacy policy URL and the Data safety form completed",
        "Target SDK meets the current Play requirement; release notes added",
        "Internal testing track release checked before production rollout",
    ],
    "ios": [
        "Archive built and uploaded to App Store Connect from CI",
        "App Store listing: name, subtitle, description, keywords, screenshots for required device sizes",
        "App privacy (nutrition label) answers and privacy policy URL",
        "TestFlight build checked by QA before submission for review",
    ],
    "web": [
        "Production domain with HTTPS and security headers (CSP, HSTS)",
        "Analytics and error monitoring configured; cookie consent where required",
        "Performance checked on a mid-range mobile device and a slow network",
    ],
    "admin_panel": [
        "Admin accounts created with least-privilege roles; default credentials removed",
        "Admin panel reachable only over HTTPS; access restricted where possible",
    ],
    "backend": [
        "Production environment variables and secrets set in the secret manager, not in the repository",
        "Database migrations applied on staging and backed up before production",
        "Monitoring, logs and alerts in place; backups scheduled and restore tested",
        "Payment runs against the dummy gateway (real payment is out of scope for this release)",
    ],
}
COMMON = [
    "All test cases executed and results recorded",
    "Release notes reviewed by the delivery head",
    "Rollback plan written for this release",
]


def build_checklist(project: Project) -> list[ChecklistItem]:
    items: list[ChecklistItem] = []
    platforms = [x.platform for x in project.platform_matrix.included()] if project.platform_matrix else []
    for p in platforms:
        for text in CHECKLISTS.get(p, []):
            items.append(ChecklistItem(id=next_id("RC", (i.id for i in items)), platform=p, text=text))
    for text in COMMON:
        items.append(ChecklistItem(id=next_id("RC", (i.id for i in items)), platform="all", text=text))
    return items


def build_release(project: Project, result: dict, files: dict[str, str], version: str = "1.0.0") -> tuple[Release, list[str]]:
    cases, notes = build_test_cases(project, result)
    return Release(version=version, test_cases=cases, findings=security_scan(files),
                   checklist=build_checklist(project), scanned_files=len(files)), notes


# ---------- Gate 4 check ----------

@dataclass
class ReleaseReport:
    passed: bool
    failures: list[str] = field(default_factory=list)


def release_check(project: Project) -> ReleaseReport:
    rel = project.release
    if rel is None:
        return ReleaseReport(False, ["Stage 8 has not run: no release"])
    failures: list[str] = []
    failures += [f"{c.id} has no result yet" for c in rel.test_cases if c.result is None]
    failures += [f"{c.id} failed: fix it and re-test, or waive it with a note" for c in rel.test_cases if c.result == "fail"]
    failures += [f"{c.id} is blocked: {c.note or 'no note'}" for c in rel.test_cases if c.result == "blocked"]
    failures += [f"{c.id} is waived without a note" for c in rel.test_cases if c.result == "waived" and not c.note.strip()]
    passing = {rid for c in rel.test_cases if c.result == "pass" for rid in c.requirement_ids}
    failures += [f"{r.id} has no passing test case: \"{r.text[:80]}\""
                 for r in project.active_requirements() if r.kind == "functional" and r.id not in passing]
    failures += [f"High-severity finding: {f.rule} in {f.path}:{f.line}" for f in rel.findings if f.severity == "high"]
    failures += [f"Checklist not done: {i.id} [{i.platform}] {i.text}" for i in rel.checklist if not i.done]
    return ReleaseReport(passed=not failures, failures=failures)
