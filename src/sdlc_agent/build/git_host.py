"""Git hosts for Stage 7, and the guard every agent write goes through.

GitHost is the interface (branch, commit, pull request). Implementations:
- FakeGitHost: in memory, for tests.
- LocalGitHost: a real git repository under data/build/<project>/repo; pull requests are recorded
  in pull_requests.json. Nothing is pushed anywhere, so the full flow can be demoed offline.
- A GitHub host plugs in later behind the same interface (needs a repo and a scoped token).

GuardedGit wraps any host and enforces the rules in code, whatever the coding agent produced:
- branches must be feature/<KEY>-...; main and develop are never written to directly;
- pull requests only into develop, and their description must cite the ticket's requirement ids;
- commit messages start with the ticket key;
- file paths stay inside the repository; .env, keys and .git are refused; a secret scan runs on
  every file; file count and size are capped.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Protocol

PROTECTED = ("main", "master", "develop")
BRANCH_RE = re.compile(r"^feature/[A-Z][A-Z0-9]*-\d+-[a-z0-9-]{1,50}$")
MAX_FILES = 25
MAX_FILE_BYTES = 100_000
FORBIDDEN_NAMES = re.compile(r"(^|/)(\.env(\..*)?|id_rsa|id_ed25519|.*\.pem|.*\.p12|.*\.keystore|.*\.jks)$", re.IGNORECASE)
SECRET_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}"),  # Anthropic
    re.compile(r"sk-[A-Za-z0-9]{32,}"),  # OpenAI-style
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),  # GitHub token
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),  # Google API key
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),  # Slack
]


class GitRuleError(ValueError):
    """An agent tried to do something the delivery rules forbid."""


class GitHost(Protocol):
    def create_branch(self, name: str, base: str) -> None: ...
    def commit_files(self, branch: str, files: dict[str, str], message: str) -> str: ...
    def open_pull_request(self, head: str, base: str, title: str, body: str) -> str: ...


# ---------- guard ----------


def check_files(files: dict[str, str]) -> None:
    if not files:
        raise GitRuleError("No files to commit")
    if len(files) > MAX_FILES:
        raise GitRuleError(f"Too many files in one change ({len(files)} > {MAX_FILES}); split the ticket")
    for path, content in files.items():
        p = PurePosixPath(path)
        if p.is_absolute() or ".." in p.parts or not p.parts or p.parts[0] == ".git" or "\\" in path:
            raise GitRuleError(f"File path outside the repository: {path}")
        if FORBIDDEN_NAMES.search(path):
            raise GitRuleError(f"Secret or key file refused: {path}")
        if len(content.encode("utf-8")) > MAX_FILE_BYTES:
            raise GitRuleError(f"File too large: {path}")
        for pattern in SECRET_PATTERNS:
            if pattern.search(content):
                raise GitRuleError(f"Possible secret in {path}; secrets belong in environment configuration")


@dataclass
class GuardedGit:
    host: GitHost
    base: str = "develop"

    def create_branch(self, name: str) -> None:
        if name in PROTECTED or not BRANCH_RE.match(name):
            raise GitRuleError(f"Branch name not allowed: {name} (use feature/<KEY>-<n>-short-name)")
        self.host.create_branch(name, self.base)

    def commit_files(self, branch: str, files: dict[str, str], message: str, ticket_key: str) -> str:
        if branch in PROTECTED or not BRANCH_RE.match(branch):
            raise GitRuleError(f"Commits only go to feature branches, not {branch}")
        if not message.startswith(f"{ticket_key}: "):
            raise GitRuleError(f"Commit message must start with '{ticket_key}: '")
        check_files(files)
        return self.host.commit_files(branch, files, message)

    def open_pull_request(self, head: str, title: str, body: str, requirement_ids: list[str]) -> str:
        if head in PROTECTED or not BRANCH_RE.match(head):
            raise GitRuleError(f"Pull requests only from feature branches, not {head}")
        missing = [r for r in requirement_ids if r not in body]
        if missing:
            raise GitRuleError(f"Pull request description must cite {', '.join(missing)}")
        return self.host.open_pull_request(head, self.base, title, body)


# ---------- hosts ----------


@dataclass
class FakeGitHost:
    branches: dict[str, dict[str, str]] = field(default_factory=lambda: {"main": {}, "develop": {}})
    commits: list[tuple[str, str]] = field(default_factory=list)
    pull_requests: list[dict] = field(default_factory=list)

    def create_branch(self, name: str, base: str) -> None:
        if name in self.branches:
            raise ValueError(f"Branch exists: {name}")
        self.branches[name] = dict(self.branches[base])

    def commit_files(self, branch: str, files: dict[str, str], message: str) -> str:
        self.branches[branch].update(files)
        self.commits.append((branch, message))
        return f"fake{len(self.commits):04d}"

    def open_pull_request(self, head: str, base: str, title: str, body: str) -> str:
        self.pull_requests.append({"head": head, "base": base, "title": title, "body": body})
        return f"fake://pull/{len(self.pull_requests)}"

    def merge(self, branch: str) -> None:
        self.branches["develop"].update(self.branches[branch])

    def read_tree(self, branch: str) -> dict[str, str]:
        return dict(self.branches[branch])


class LocalGitHost:
    """A real local repository; nothing is pushed. Pull requests are recorded next to it."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.repo = self.root / "repo"
        self.prs_file = self.root / "pull_requests.json"
        if not (self.repo / ".git").exists():
            self.repo.mkdir(parents=True, exist_ok=True)
            self._git("init", "-q", "-b", "main")
            (self.repo / "README.md").write_text("# Project\n\nScaffolded by the AI SDLC Agent.\n", encoding="utf-8")
            self._git("add", "-A")
            self._git("commit", "-q", "-m", "chore: initial commit")
            self._git("branch", "develop")

    def _git(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-c", "user.name=AI SDLC Agent", "-c", "user.email=agent@localhost", "-c", "commit.gpgsign=false",
             *args], cwd=self.repo, check=True, capture_output=True, text=True,
        ).stdout.strip()

    def create_branch(self, name: str, base: str) -> None:
        self._git("branch", name, base)

    def commit_files(self, branch: str, files: dict[str, str], message: str) -> str:
        self._git("checkout", "-q", branch)
        try:
            for path, content in files.items():
                target = (self.repo / path).resolve()
                if self.repo.resolve() not in target.parents:
                    raise GitRuleError(f"File path outside the repository: {path}")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            self._git("add", "-A")
            self._git("commit", "-q", "-m", message)
            return self._git("rev-parse", "--short", "HEAD")
        finally:
            self._git("checkout", "-q", "develop")

    def open_pull_request(self, head: str, base: str, title: str, body: str) -> str:
        prs = json.loads(self.prs_file.read_text(encoding="utf-8")) if self.prs_file.exists() else []
        prs.append({"number": len(prs) + 1, "head": head, "base": base, "title": title, "body": body})
        self.prs_file.write_text(json.dumps(prs, indent=2), encoding="utf-8")
        return f"local://{self.root.name}/pull/{len(prs)}"

    def merge(self, branch: str) -> None:
        """Simulates the human merging a reviewed pull request into develop (demo only)."""
        self._git("checkout", "-q", "develop")
        self._git("merge", "-q", "--no-ff", "-m", f"Merge {branch} into develop", branch)

    def read_tree(self, branch: str) -> dict[str, str]:
        """Text files on a branch (for the Stage 8 security scan)."""
        out: dict[str, str] = {}
        for path in self._git("ls-tree", "-r", "--name-only", branch).splitlines():
            try:
                out[path] = self._git("show", f"{branch}:{path}")
            except subprocess.CalledProcessError:
                continue
        return out

    def diff(self, branch: str, base: str = "develop") -> str:
        """What a pull request changes, for review on the dashboard before merging."""
        return self._git("diff", f"{base}...{branch}")
