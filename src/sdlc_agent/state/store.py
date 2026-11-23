"""Project storage. JSON files for the demo; swap for PostgreSQL later behind the same methods."""
from __future__ import annotations

import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Iterable

from .models import Project


def next_id(prefix: str, existing: Iterable[str]) -> str:
    """Next sequential id like GAP-007, given the ids already used."""
    pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$")
    nums = [int(m.group(1)) for i in existing if (m := pattern.match(i))]
    return f"{prefix}-{(max(nums) + 1 if nums else 1):03d}"


class ProjectStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.unreadable: list[tuple[str, str]] = []
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, project_id: str) -> Path:
        return self.root / f"{project_id}.json"

    def create(self, name: str) -> Project:
        project = Project(id=uuid.uuid4().hex[:8], name=name)
        self.save(project)
        return project

    def save(self, project: Project) -> None:
        data = project.model_dump_json(indent=2)
        fd, tmp = tempfile.mkstemp(dir=self.root, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, self._path(project.id))  # atomic write

    def load(self, project_id: str) -> Project:
        return Project.model_validate_json(self._path(project_id).read_text(encoding="utf-8"))

    def list(self) -> list[Project]:
        """Every readable project. A file that does not load (corrupt, or written by newer code than the
        running process) is skipped and reported in `unreadable`, so one bad file never hides the rest."""
        projects, self.unreadable = [], []
        for path in self.root.glob("*.json"):
            try:
                projects.append(Project.model_validate_json(path.read_text(encoding="utf-8")))
            except (ValueError, OSError) as exc:
                self.unreadable.append((path.stem, str(exc).splitlines()[0][:200]))
        return sorted(projects, key=lambda p: p.created_at, reverse=True)
