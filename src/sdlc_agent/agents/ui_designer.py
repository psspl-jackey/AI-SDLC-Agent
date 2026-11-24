"""Stage 4 UI designer: the visual theme and UX principles every app follows.

- Without client suggestions the theme comes from the domain pack's `ui` section (no model call), so
  every project gets a considered default.
- With a UI direction ("green and premium", "simple for older users", "dark blue like a bank"...) the
  model maps it onto the theme's fixed choices. Code then checks everything:
  colours must be hex (common colour words are converted), text on buttons and body text must meet
  WCAG AA contrast (colours are darkened until they do), only light backgrounds are used by the
  starter apps, and the brand name is always the project's own neutral name, never a competitor's.
"""
from __future__ import annotations

import re

from ..domain_packs import load_packs
from ..llm.base import LLMClient
from ..llm.json_call import complete_json
from ..state.models import Project, UiTheme

NAME = "ui_designer"

SYSTEM = """You are a senior UI designer at a software company. You choose an original visual theme for a
client's apps from the client's direction and the product's domain and audience. Never copy a competitor's
brand, logo, colours or name. Return colours as hex codes. Choose only from the allowed values."""

SHAPE = {"tagline": "str", "primary": "str", "accent": "str", "background": "str", "text": "str",
         "font": "str", "radius": "str", "density": "str", "mood": "str", "ux_principles": "strs", "reason": "str"}
SCHEMA = ('Return JSON: {"tagline": str (max 8 words), "primary": "#RRGGBB", "accent": "#RRGGBB", '
          '"background": "#RRGGBB" (light), "text": "#RRGGBB" (dark), "font": "sans"|"rounded"|"serif", '
          '"radius": "sharp"|"soft"|"round", "density": "comfortable"|"compact", "mood": str (3 words), '
          '"ux_principles": [str] (3 to 5, specific to this product), "reason": str}')

GENERIC = {
    "tagline": "", "primary": "#2563EB", "accent": "#F59E0B", "font": "sans", "radius": "soft",
    "density": "comfortable", "mood": "clear, modern, friendly",
    "ux_principles": ["The main action of each screen is one obvious button",
                      "Lists have search, and empty lists explain what to do next",
                      "Forms validate as you type and keep what was entered after an error"],
    "category_icons": {}, "safety_tips": [],
}

COLOR_WORDS = {
    "red": "#B91C1C", "maroon": "#7F1D1D", "orange": "#C2410C", "amber": "#B45309", "yellow": "#A16207",
    "gold": "#A16207", "green": "#15803D", "dark green": "#14532D", "emerald": "#047857", "teal": "#0F766E",
    "cyan": "#0E7490", "blue": "#1D4ED8", "dark blue": "#1E3A8A", "navy": "#1E3A8A", "sky": "#0369A1",
    "indigo": "#4338CA", "purple": "#7E22CE", "violet": "#6D28D9", "pink": "#BE185D", "rose": "#BE123C",
    "magenta": "#A21CAF", "brown": "#78350F", "black": "#111827", "grey": "#4B5563", "gray": "#4B5563",
    "saffron": "#C2410C", "white": "#FFFFFF", "cream": "#FFFBEB", "beige": "#F5F5DC",
}
ALLOWED = {"font": ("sans", "rounded", "serif"), "radius": ("sharp", "soft", "round"),
           "density": ("comfortable", "compact")}


READABLE = re.compile(r"\b(older|elderly|senior|seniors|large text|big text|bigger text|larger text|easy to read|"
                      r"readab\w*|low vision|accessib\w*)\b", re.IGNORECASE)
FONT_WORDS = {"serif": r"\bserif\b|classic|elegant|traditional", "rounded": r"rounded|playful|friendly",
              "sans": r"\bsans\b|minimal|clean|modern"}


def direction_hints(direction: str) -> tuple[dict, list[str]]:
    """Explicit asks in the client's own words win over the model's reading of them."""
    text = direction.lower()
    hints: dict = {}
    accent = re.search(r"(?:([a-z]+(?: [a-z]+)?) accents?\b|accents? (?:of|in|colou?r)? ?([a-z]+(?: [a-z]+)?))", text)
    if accent:
        word = to_hex(accent.group(1) or accent.group(2) or "")
        if word:
            hints["accent"] = word
    colours = [(m.start(), COLOR_WORDS[w]) for w in sorted(COLOR_WORDS, key=len, reverse=True)
               for m in re.finditer(rf"\b{w}\b", text)]
    colours = [hx for _, hx in sorted(colours) if hx != hints.get("accent") and hx not in ("#FFFFFF", "#FFFBEB", "#F5F5DC")]
    if colours:
        hints["primary"] = colours[0]
    if re.search(r"sans[- ]serif", text):
        hints["font"] = "sans"
    else:
        for font, pattern in FONT_WORDS.items():
            if re.search(pattern, text):
                hints["font"] = font
                break
    notes = []
    if READABLE.search(text):
        hints["text_scale"] = 1.15
        hints["density"] = "comfortable"
        notes.append("larger text (x1.15) and comfortable spacing for readability")
    return hints, notes


# ---------- colour maths (WCAG 2.1) ----------

def _rgb(hex_: str) -> tuple[int, int, int]:
    h = hex_.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02X}" for c in rgb)


def luminance(hex_: str) -> float:
    def ch(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = _rgb(hex_)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def darken(hex_: str, factor: float = 0.9) -> str:
    return _hex(tuple(c * factor for c in _rgb(hex_)))


def to_hex(value: str) -> str | None:
    v = (value or "").strip().lower()
    if re.fullmatch(r"#?[0-9a-f]{6}", v):
        return "#" + v.lstrip("#").upper()
    if re.fullmatch(r"#?[0-9a-f]{3}", v):
        return "#" + "".join(c * 2 for c in v.lstrip("#")).upper()
    for word in sorted(COLOR_WORDS, key=len, reverse=True):
        if re.search(rf"\b{word}\b", v):
            return COLOR_WORDS[word]
    return None


def readable_on(bg: str, notes: list[str], label: str) -> tuple[str, str]:
    """Pick white or near-black text for a button colour; darken the colour if neither reaches 4.5:1."""
    color = bg
    for _ in range(20):
        white, dark = contrast(color, "#FFFFFF"), contrast(color, "#111827")
        if white >= 4.5:
            break
        if dark >= 4.5:
            return color, "#111827"
        color = darken(color)
    if color != bg:
        notes.append(f"{label} {bg} darkened to {color} so button text is readable (WCAG AA 4.5:1)")
    return color, "#FFFFFF"


# ---------- theme ----------

def domain_ui(project: Project) -> dict:
    pack = load_packs().get(project.domain_pack or "", {})
    return {**GENERIC, **(pack.get("ui") or {})}


def build_theme(project: Project, result: dict | None = None) -> UiTheme:
    from ..build.starters import app_name  # neutral name; never a competitor's brand
    base = domain_ui(project)
    notes: list[str] = []
    r = dict(result or {})
    hints, hint_notes = direction_hints(project.ui_direction) if project.ui_direction.strip() else ({}, [])
    for key, value in hints.items():
        if key != "text_scale" and str(r.get(key, "")).lower() != str(value).lower():
            if r.get(key):
                notes.append(f"{key}: the direction asks for {value}; the model suggested {r[key]}")
            r[key] = value
    notes += hint_notes
    values = dict(base)
    for key in ("primary", "accent", "background", "text"):
        if r.get(key):
            hex_ = to_hex(str(r[key]))
            if hex_:
                values[key] = hex_
            else:
                notes.append(f"{key} '{r[key]}' is not a colour; kept {values.get(key)}")
    for key, allowed in ALLOWED.items():
        if r.get(key):
            v = str(r[key]).strip().lower()
            if v in allowed:
                values[key] = v
            else:
                notes.append(f"{key} '{r[key]}' is not one of {', '.join(allowed)}; kept {values[key]}")
    if r.get("tagline"):
        values["tagline"] = " ".join(str(r["tagline"]).split()[:10])
    if r.get("mood"):
        values["mood"] = str(r["mood"])[:60]
    # Keep the domain's specific principles; add the model's only when they say something concrete.
    extra = [p for p in r.get("ux_principles", []) if isinstance(p, str) and len(p.split()) >= 5
             and p not in values["ux_principles"]]
    values["ux_principles"] = (list(values["ux_principles"]) + extra)[:7]
    if hints.get("text_scale"):
        values["ux_principles"] = values["ux_principles"] + ["Text is 15% larger than standard and every tap "
                                                             "target is at least 44 px, for easy reading"]

    background = values.get("background") or "#F6F7F9"
    if luminance(background) < 0.8:
        notes.append(f"background {background} is dark; the starter apps use a light background, kept #F6F7F9")
        background = "#F6F7F9"
    text = values.get("text") or "#1F2933"
    if contrast(text, background) < 7:
        notes.append(f"text {text} is hard to read on {background}; used #1F2933")
        text = "#1F2933"
    primary, on_primary = readable_on(values["primary"], notes, "primary")
    accent, on_accent = readable_on(values["accent"], notes, "accent")
    muted = "#5F6B7A"
    while contrast(muted, "#FFFFFF") < 4.5 or contrast(muted, background) < 4.5:
        muted = darken(muted)

    brand = app_name(project)
    return UiTheme(
        brand_name=brand, tagline=values.get("tagline") or "", primary=primary, on_primary=on_primary,
        accent=accent, on_accent=on_accent, background=background, text=text, muted=muted,
        font=values["font"], radius=values["radius"], density=values["density"], mood=values.get("mood", ""),
        text_scale=hints.get("text_scale", 1.0),
        ux_principles=values["ux_principles"], category_icons=values.get("category_icons") or {},
        safety_tips=values.get("safety_tips") or [],
        source="client_direction" if (result or hints) else "domain_default",
        client_direction=project.ui_direction.strip(), adjustments=notes,
    )


def run(llm: LLMClient, project: Project) -> dict | None:
    """Model call only when there is a UI direction to interpret; otherwise the domain default stands."""
    direction = project.ui_direction.strip()
    if not direction:
        return None
    base = domain_ui(project)
    b = project.brief
    prompt = (
        f"Product: {b.goal if b else project.name}\nDomain: {project.domain_pack or 'general'}\n"
        f"Region: {b.region if b else ''}\nUsers: {', '.join(b.target_users) if b else ''}\n\n"
        f"Default theme for this domain: primary {base['primary']}, accent {base['accent']}, font {base['font']}, "
        f"radius {base['radius']}, mood {base['mood']}.\n\n"
        f"Client's UI direction (follow it; keep the defaults for anything it does not mention):\n{direction}\n\n"
        f"{SCHEMA}"
    )
    return complete_json(llm, SYSTEM, prompt, SHAPE)


def design_theme(llm: LLMClient, project: Project) -> UiTheme:
    return build_theme(project, run(llm, project))
