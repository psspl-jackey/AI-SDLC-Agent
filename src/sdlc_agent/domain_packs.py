"""Load domain packs and match one to a project's domain."""
from __future__ import annotations

from pathlib import Path

import yaml

PACK_DIR = Path(__file__).resolve().parents[2] / "domain_packs"


def load_packs(pack_dir: Path = PACK_DIR) -> dict[str, dict]:
    return {p.stem: yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted(pack_dir.glob("*.yaml"))}


def match_pack(domain: str, packs: dict[str, dict] | None = None) -> tuple[str, dict] | None:
    packs = packs if packs is not None else load_packs()
    d = (domain or "").lower().strip()
    if not d:
        return None
    for name, pack in packs.items():
        names = [pack.get("name", name), *pack.get("aliases", [])]
        if any(a.lower() in d or d in a.lower() for a in names):
            return name, pack
    return None
