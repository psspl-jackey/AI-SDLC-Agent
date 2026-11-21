"""Turn each input into readable chunks, each with a source reference for traceability."""
from __future__ import annotations

import csv
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from ..state.models import Chunk, InputType, RawInput, SourceRef
from .detect import detect_input_type

USER_AGENT = "AI-SDLC-Agent/0.1 (requirements research; public pages only)"


def read_input(raw: RawInput) -> list[Chunk]:
    kind = raw.detected_type or detect_input_type(raw)
    if kind in (InputType.ONE_LINE, InputType.NOTES):
        return [Chunk(text=raw.value.strip(), source=SourceRef(kind="intake", ref="client text"))]
    if kind in (InputType.URL, InputType.APP_STORE_URL):
        return read_url(raw.value)
    if kind is InputType.IMAGE:
        # Reading screens from images needs a vision-capable model; queued for a later iteration.
        return [Chunk(
            text=f"[Image provided: {Path(raw.value).name}. Image reading is not enabled yet; "
                 f"describe the screen in the intake notes.]",
            source=SourceRef(kind="file", ref=Path(raw.value).name),
        )]
    return read_file(Path(raw.value))


def read_file(path: Path) -> list[Chunk]:
    ext = path.suffix.lower()
    name = path.name
    if ext == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return [
            Chunk(text=text, source=SourceRef(kind="file", ref=f"{name} p.{i}"))
            for i, page in enumerate(reader.pages, start=1)
            if (text := (page.extract_text() or "").strip())
        ]
    if ext == ".docx":
        import docx

        d = docx.Document(str(path))
        parts = [p.text for p in d.paragraphs if p.text.strip()]
        for t_index, table in enumerate(d.tables, start=1):
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    parts.append(" | ".join(cells))
        return [Chunk(text="\n".join(parts), source=SourceRef(kind="file", ref=name))] if parts else []
    if ext == ".xlsx":
        from openpyxl import load_workbook

        wb = load_workbook(str(path), read_only=True, data_only=True)
        chunks = []
        for ws in wb.worksheets:
            rows = [
                " | ".join(str(v) for v in row if v not in (None, ""))
                for row in ws.iter_rows(values_only=True)
            ]
            rows = [r for r in rows if r]
            if rows:
                chunks.append(Chunk(text="\n".join(rows), source=SourceRef(kind="file", ref=f"{name} sheet {ws.title}")))
        return chunks
    if ext == ".csv":
        with path.open(newline="", encoding="utf-8", errors="replace") as f:
            rows = [" | ".join(c for c in row if c) for row in csv.reader(f)]
        return [Chunk(text="\n".join(r for r in rows if r), source=SourceRef(kind="file", ref=name))]
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    return [Chunk(text=text, source=SourceRef(kind="file", ref=name))] if text else []


def allowed_by_robots(url: str) -> bool:
    parsed = urlparse(url)
    rp = urllib.robotparser.RobotFileParser()
    try:
        resp = httpx.get(f"{parsed.scheme}://{parsed.netloc}/robots.txt", timeout=10,
                         headers={"User-Agent": USER_AGENT}, follow_redirects=True)
        if resp.status_code >= 400:
            return True  # no robots file: crawling public pages is allowed
        rp.parse(resp.text.splitlines())
        return rp.can_fetch(USER_AGENT, url)
    except httpx.HTTPError:
        return True


def read_url(url: str, max_chars: int = 15000) -> list[Chunk]:
    """Read one public page: title, headings, navigation labels and visible text."""
    if not allowed_by_robots(url):
        return [Chunk(text=f"[Skipped {url}: the site's robots rules do not allow automated reading.]",
                      source=SourceRef(kind="url", ref=url))]
    resp = httpx.get(url, timeout=20, follow_redirects=True, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else ""
    headings = [h.get_text(" ", strip=True) for h in soup.find_all(["h1", "h2", "h3"])]
    nav = [a.get_text(" ", strip=True) for n in soup.find_all("nav") for a in n.find_all("a")]
    body = " ".join(soup.get_text(" ", strip=True).split())
    text = "\n".join(filter(None, [
        f"Page title: {title}",
        "Navigation: " + ", ".join(dict.fromkeys(x for x in nav if x)) if nav else "",
        "Headings: " + " / ".join(headings[:40]) if headings else "",
        "Text: " + body[:max_chars],
    ]))
    return [Chunk(text=text, source=SourceRef(kind="url", ref=url))]
