"""Starter apps: runnable skeletons written by code (not the model) from the approved design.

For every included platform whose tech pack has a starter in starters/<pack>/, this renders a small
working app into apps/<name>/ of the project repository:
- backend: API with login, categories, items (ads or products), favourites, moderation, dummy payment,
  and a SQLite database seeded with dummy data for the project's domain and region;
- admin panel and website: React UIs on the chosen shell (Next.js or Vite);
- android + ios: one Expo app when both use the same cross-platform pack.

Agent tickets then add features inside these apps instead of writing files that do not connect.
Packs without a starter (Flutter, native Kotlin/Swift, Node backend...) are reported, not faked.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..state.models import Project

ROOT = Path(__file__).resolve().parents[3] / "starters"
API_PORT = 8000

DEMO_USERS = [
    {"name": "Demo Admin", "email": "admin@demo.local", "password": "Admin@123", "role": "admin"},
    {"name": "Ravi Patel", "email": "ravi@demo.local", "password": "Demo@123", "role": "user"},
    {"name": "Priya Shah", "email": "priya@demo.local", "password": "Demo@123", "role": "user"},
]

# Dummy catalogue per domain: (title, category, price, description)
DOMAIN_SEED = {
    "classifieds": {
        "labels": ("Ad", "Ads"),
        "categories": ["Mobiles", "Cars", "Bikes", "Property", "Electronics", "Furniture", "Jobs"],
        "items": [
            ("iPhone 13, 128 GB, good condition", "Mobiles", 38000, "Single owner, bill and box available. Battery health 88%."),
            ("Samsung Galaxy S22 Ultra", "Mobiles", 52000, "Phantom black, minor scratches, with charger."),
            ("Redmi Note 12, 6 GB RAM", "Mobiles", 9500, "Used for 1 year, works perfectly."),
            ("Maruti Swift VXi 2019, petrol", "Cars", 520000, "42,000 km, first owner, insurance till next year."),
            ("Hyundai Creta SX 2021, diesel", "Cars", 1350000, "Company serviced, sunroof, 35,000 km."),
            ("Honda Activa 6G 2022", "Bikes", 68000, "11,000 km, all papers clear."),
            ("Royal Enfield Classic 350", "Bikes", 165000, "2021 model, well maintained."),
            ("2 BHK flat for rent near SG Highway", "Property", 18000, "Semi-furnished, 1,150 sq ft, covered parking. Monthly rent."),
            ("3 BHK apartment for sale", "Property", 7500000, "East facing, 1,650 sq ft, society with gym and pool."),
            ("Sony 55 inch 4K smart TV", "Electronics", 42000, "2 years old, with wall mount and remote."),
            ("HP Pavilion laptop, i5 12th gen", "Electronics", 41000, "16 GB RAM, 512 GB SSD, under warranty."),
            ("Teak wood 6-seater dining table", "Furniture", 24000, "Solid teak, with 6 chairs."),
            ("L-shaped sofa set", "Furniture", 21000, "Grey fabric, 3 years old, no damage."),
            ("Delivery executive wanted", "Jobs", 18000, "Full time, own two-wheeler needed. Monthly salary."),
        ],
    },
    "ecommerce": {
        "labels": ("Product", "Products"),
        "categories": ["Sarees", "Dupattas", "Stoles", "Kurtas"],
        "items": [
            ("Patola silk saree, red and gold", "Sarees", 18500, "Handwoven double ikat from Patan."),
            ("Bandhani cotton saree", "Sarees", 3200, "Traditional tie-dye, soft cotton."),
            ("Kanjivaram silk saree", "Sarees", 22000, "Pure zari border, wedding wear."),
            ("Bandhani silk dupatta", "Dupattas", 1450, "Hand tied, vibrant colours."),
            ("Chikankari georgette dupatta", "Dupattas", 1800, "Lucknowi hand embroidery."),
            ("Pashmina wool stole", "Stoles", 4200, "Soft and warm, natural dye."),
            ("Block print cotton stole", "Stoles", 650, "Hand block printed, Sanganeri."),
            ("Ajrakh cotton kurta", "Kurtas", 1900, "Natural dyes, Kutch Ajrakh print."),
        ],
    },
    "default": {
        "labels": ("Item", "Items"),
        "categories": ["General", "Services", "Products"],
        "items": [
            ("Sample item one", "General", 1000, "Dummy data for the demo."),
            ("Sample service", "Services", 2500, "Dummy data for the demo."),
            ("Sample product", "Products", 500, "Dummy data for the demo."),
        ],
    },
}

CITIES = {
    "gujarat": ["Ahmedabad", "Surat", "Vadodara", "Rajkot", "Gandhinagar", "Bhavnagar"],
    "india": ["Mumbai", "Delhi", "Bengaluru", "Pune", "Ahmedabad", "Chennai"],
    "default": ["City A", "City B", "City C"],
}

DIR_NAMES = {"backend": "apps/backend", "admin_panel": "apps/admin", "web": "apps/web", "mobile": "apps/mobile"}
SURFACE_TITLES = {"admin_panel": " Admin", "web": "", "backend": " API", "mobile": ""}


@dataclass
class StarterSpec:
    pack: str
    platforms: list[str]
    folder: Path
    raw: dict

    def per(self, key: str, surface: str):
        v = self.raw.get(key)
        return v.get(surface) if isinstance(v, dict) else v


@dataclass
class AppPlan:
    """One runnable app in the repo. android + ios share one ('mobile') when they share a pack."""
    surface: str  # backend | admin_panel | web | mobile
    platforms: list[str]
    pack: str
    dir: str
    port: int
    install: list[str] = field(default_factory=list)
    test: list[str] = field(default_factory=list)
    start: str = ""
    url: str = ""
    spec: StarterSpec | None = None


def load_starters(root: Path = ROOT) -> dict[str, StarterSpec]:
    out = {}
    for f in sorted(root.glob("*/starter.yaml")):
        raw = yaml.safe_load(f.read_text(encoding="utf-8"))
        out[raw["pack"]] = StarterSpec(pack=raw["pack"], platforms=raw["platforms"], folder=f.parent, raw=raw)
    return out


def plan_apps(project: Project) -> tuple[list[AppPlan], list[str]]:
    """Apps to create, and notes for included platforms that have no starter yet."""
    if project.design is None or project.platform_matrix is None:
        return [], ["Stage 4 has not run: no stacks chosen"]
    starters = load_starters()
    included = [d.platform for d in project.platform_matrix.included()]
    stacks = {s.platform: s.pack for s in project.design.stacks}
    apps: list[AppPlan] = []
    notes: list[str] = []
    mobile = [p for p in ("android", "ios") if p in included]
    surfaces: list[tuple[str, list[str]]] = [(p, [p]) for p in included if p not in ("android", "ios")]
    if mobile:
        packs = {stacks.get(p) for p in mobile}
        if len(packs) == 1:
            surfaces.append(("mobile", mobile))
        else:
            surfaces += [(p, [p]) for p in mobile]
    for surface, platforms in surfaces:
        pack = stacks.get(platforms[0])
        spec = starters.get(pack or "")
        if spec is None or not set(platforms) <= set(spec.platforms):
            notes.append(f"{', '.join(platforms)}: no starter app for the {pack or 'unchosen'} pack yet; "
                         "the team sets this app up")
            continue
        apps.append(AppPlan(
            surface=surface, platforms=platforms, pack=pack, spec=spec,
            dir=spec.per("dir", surface) or DIR_NAMES.get(surface, f"apps/{surface}"),
            port=int(spec.per("port", surface)), install=list(spec.raw.get("install", [])),
            test=list(spec.raw.get("test", [])), start=spec.raw.get("start", ""), url=spec.raw.get("url", ""),
        ))
    return apps, notes


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30].strip("-") or "app"


def _region_text(project: Project) -> str:
    parts = [project.brief.region if project.brief else "", project.intake_answers.get("region", ""), project.name,
             *(r.value for r in project.raw_inputs if r.kind == "text")]
    return " ".join(filter(None, parts)).lower()


def app_name(project: Project) -> str:
    """Short, neutral product name for screens. Briefs like 'an app like OLX' must not put another
    company's brand on the demo, so those get '<Region> <Domain>' instead."""
    name = project.name.strip()
    domain = (project.domain_pack or "").replace("_", " ").title()
    region = next((w.title() for w in ("gujarat", "india") if w in _region_text(project)), "")
    if re.search(r"\b(like|similar to|clone of|same as)\b", name, re.IGNORECASE) or len(name) > 40:
        return " ".join(filter(None, [region, domain or "App"]))
    return name[:40] or "Demo app"


def seed_data(project: Project) -> dict:
    domain = (project.domain_pack or "").lower()
    seed = DOMAIN_SEED.get(domain, DOMAIN_SEED["default"])
    region = _region_text(project)
    cities = CITIES["gujarat" if "gujarat" in region else "india" if "india" in region else "default"]
    currency = "INR" if ("india" in region or "gujarat" in region) else "USD"
    users = [dict(u, city=cities[i % len(cities)]) for i, u in enumerate(DEMO_USERS)]
    sellers = [u["email"] for u in users if u["role"] == "user"]
    items = []
    for i, (title, category, price, description) in enumerate(seed["items"]):
        items.append({"title": title, "category": category, "price": price, "description": description,
                      "city": cities[i % len(cities)], "seller": sellers[i % len(sellers)],
                      "featured": i % 5 == 0, "status": "pending" if i % 7 == 6 else "active"})
    return {
        "config": {"app_name": app_name(project), "item_label": seed["labels"][0], "items_label": seed["labels"][1],
                   "currency": currency, "cities": cities},
        "users": users, "categories": seed["categories"], "items": items,
    }


def _render(text: str, values: dict[str, str]) -> str:
    return re.sub(r"\{\{(\w+)\}\}", lambda m: str(values.get(m.group(1), m.group(0))), text)


def render_apps(project: Project) -> tuple[dict[str, dict[str, str]], list[AppPlan], list[str]]:
    """Files per app ({app dir: {repo path: content}}), the app plans, and notes."""
    apps, notes = plan_apps(project)
    seed = seed_data(project)
    admin = next(u for u in seed["users"] if u["role"] == "admin")
    user = next(u for u in seed["users"] if u["role"] == "user" and u["email"].startswith("priya"))
    out: dict[str, dict[str, str]] = {}
    for app in apps:
        values = {
            "project_name": seed["config"]["app_name"], "app_slug": _slug(seed["config"]["app_name"]),
            "app_id": re.sub(r"[^a-z0-9]", "", _slug(seed["config"]["app_name"]))[:20] or "app",
            "api_port": str(API_PORT), "port": str(app.port), "surface": app.surface,
            "surface_title": SURFACE_TITLES.get(app.surface, ""), "items_label": seed["config"]["items_label"],
            "admin_email": admin["email"], "admin_password": admin["password"],
            "user_email": user["email"], "user_password": user["password"],
        }
        files: dict[str, str] = {}
        sources = [(app.spec.folder / "files", "")]
        if app.spec.raw.get("ui"):
            ui = "admin" if app.surface == "admin_panel" else "web"
            sources += [(ROOT / "ui" / ui, "src/"), (ROOT / "ui" / "shared", "src/")]
        for base, prefix in sources:
            for f in sorted(base.rglob("*")):
                if f.is_file():
                    files[f"{app.dir}/{prefix}{f.relative_to(base).as_posix()}"] = _render(f.read_text(encoding="utf-8"), values)
        if app.surface == "backend":
            files[f"{app.dir}/seed.json"] = json.dumps(seed, indent=2, ensure_ascii=False) + "\n"
        files[f"{app.dir}/README.md"] = app_readme(app, seed)
        out[app.dir] = files
    return out, apps, notes


def app_readme(app: AppPlan, seed: dict) -> str:
    lines = [f"# {seed['config']['app_name']}: {app.surface.replace('_', ' ')} ({app.pack})", "",
             "Starter app written by the AI SDLC Agent from the approved design. Agent and developer tickets add",
             "features here.", "", "## Run", "", "```bash"]
    lines += [c.replace("{python}", "python3") for c in app.install]
    lines += [app.start.replace("{port}", str(app.port)), "```", ""]
    if app.test:
        lines += ["## Check", "", "```bash", *app.test, "```", ""]
    if app.surface == "backend":
        lines += ["API docs: http://localhost:%d/docs" % app.port, "", "## Demo accounts (dummy data, local only)", ""]
        lines += [f"- {u['email']} / {u['password']} ({u['role']})" for u in seed["users"]]
    if app.surface == "mobile":
        lines += ["Open with Expo Go on an iPhone or Android phone on the same Wi-Fi (scan the QR code), or press `a`",
                  "for the Android emulator. The backend must be running on this computer."]
    return "\n".join(lines) + "\n"
