"""Runs the project's apps locally: install, test, start and stop, on a checkout of develop.

The checkout is a git worktree at data/build/<project>/run/workspace (detached at develop), so the
agents' repository is never touched and installed packages (node_modules, .venv) survive re-checks.
Commands run on this machine, not in a sandbox: only starter commands from starters/*/starter.yaml
are run, never commands written by the model. A Docker sandbox replaces this later.
"""
from __future__ import annotations

import os
import shlex
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

TAIL = 4000


def lan_ip() -> str:
    """This computer's address on the local network (phones on the same Wi-Fi reach it)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def _env() -> dict[str, str]:
    env = dict(os.environ)
    extra = [p for p in ("/opt/homebrew/bin", "/usr/local/bin") if p not in env.get("PATH", "")]
    env["PATH"] = ":".join([env.get("PATH", ""), *extra]).strip(":")
    env.pop("VIRTUAL_ENV", None)  # the harness venv must not leak into the app's own venv
    env.setdefault("EXPO_NO_TELEMETRY", "1")
    env.setdefault("NEXT_TELEMETRY_DISABLED", "1")
    return env


class AppRunner:
    def __init__(self, build_root: Path):
        self.root = Path(build_root).resolve()
        self.repo = self.root / "repo"
        self.workspace = self.root / "run" / "workspace"
        self.logs = self.root / "run" / "logs"
        self.pids = self.root / "run" / "pids"

    # ---------- workspace ----------

    def _git(self, *args: str, cwd: Path | None = None) -> str:
        return subprocess.run(["git", *args], cwd=cwd or self.repo, check=True, capture_output=True, text=True).stdout.strip()

    def sync(self) -> str:
        """Point the workspace at the current develop; returns the commit."""
        if not (self.workspace / ".git").exists():
            self.workspace.parent.mkdir(parents=True, exist_ok=True)
            self._git("worktree", "prune")
            self._git("worktree", "add", "-q", "--detach", str(self.workspace), "develop")
        else:
            self._git("checkout", "-q", "-f", "--detach", "develop", cwd=self.workspace)
        return self._git("rev-parse", "--short", "HEAD", cwd=self.workspace)

    def format(self, command: str, port: int) -> str:
        return command.format(python=shlex.quote(sys.executable), port=port, lan_ip=lan_ip())

    # ---------- one-off commands ----------

    def run(self, app_dir: str, command: str, timeout: int = 900) -> tuple[bool, str, float]:
        start = time.monotonic()
        try:
            p = subprocess.run(command, shell=True, cwd=self.workspace / app_dir, env=_env(), capture_output=True,
                               text=True, timeout=timeout, stdin=subprocess.DEVNULL)
            out, ok = (p.stdout + p.stderr), p.returncode == 0
        except subprocess.TimeoutExpired as exc:
            out = f"{exc.stdout or ''}{exc.stderr or ''}\nTimed out after {timeout} s"
            out, ok = out if isinstance(out, str) else str(out), False
        return ok, out[-TAIL:], round(time.monotonic() - start, 1)

    # ---------- long-running apps ----------

    def _key(self, app_dir: str) -> str:
        return app_dir.replace("/", "_")

    def log_file(self, app_dir: str) -> Path:
        return self.logs / f"{self._key(app_dir)}.log"

    def pid(self, app_dir: str) -> int | None:
        f = self.pids / f"{self._key(app_dir)}.pid"
        if not f.exists():
            return None
        try:
            pid = int(f.read_text())
            try:  # reap it if it is our finished child, or a zombie would look alive
                if os.waitpid(pid, os.WNOHANG)[0] == pid:
                    raise ProcessLookupError
            except ChildProcessError:
                pass  # started by another process (e.g. an earlier dashboard run)
            os.kill(pid, 0)
            return pid
        except (ValueError, ProcessLookupError, PermissionError):
            f.unlink(missing_ok=True)
            return None

    def start(self, app_dir: str, command: str) -> int:
        if (pid := self.pid(app_dir)) is not None:
            return pid
        self.logs.mkdir(parents=True, exist_ok=True)
        self.pids.mkdir(parents=True, exist_ok=True)
        log = open(self.log_file(app_dir), "w", encoding="utf-8")  # noqa: SIM115 - handed to the child
        proc = subprocess.Popen(command, shell=True, cwd=self.workspace / app_dir, env=_env(), stdout=log,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
        (self.pids / f"{self._key(app_dir)}.pid").write_text(str(proc.pid))
        return proc.pid

    def stop(self, app_dir: str) -> bool:
        pid = self.pid(app_dir)
        if pid is None:
            return False
        try:
            os.killpg(pid, signal.SIGTERM)
            for _ in range(20):
                time.sleep(0.25)
                if self.pid(app_dir) is None:
                    break
            else:
                os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        (self.pids / f"{self._key(app_dir)}.pid").unlink(missing_ok=True)
        return True

    def log_tail(self, app_dir: str, chars: int = TAIL) -> str:
        f = self.log_file(app_dir)
        return f.read_text(encoding="utf-8", errors="replace")[-chars:] if f.exists() else ""
