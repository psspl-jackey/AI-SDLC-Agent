"""UI theme: domain default, client direction read by the model, code checks (contrast, values, brand)."""
import pytest

from sdlc_agent.agents import ui_designer
from sdlc_agent.agents.ui_designer import build_theme, contrast, direction_hints, to_hex
from sdlc_agent.build.git_host import FakeGitHost
from sdlc_agent.build.starters import theme_files, theme_ts
from sdlc_agent.orchestrator import Deps, set_ui_direction
from sdlc_agent.orchestrator.apps import add_starter_apps, apply_theme
from test_starters import project


def test_domain_default_needs_no_model_call():
    p = project()
    assert ui_designer.run(object(), p) is None  # no direction: the llm is never touched
    t = build_theme(p)
    assert t.source == "domain_default" and t.primary == "#0F766E" and t.font == "rounded"
    assert t.brand_name == "Gujarat Classifieds" and "OLX" not in t.brand_name
    assert t.category_icons["Mobiles"] and t.safety_tips and t.ux_principles


@pytest.mark.parametrize("primary", ["#FFFF00", "#7DD3FC", "#F59E0B", "#0F766E", "#111111"])
def test_button_text_always_meets_wcag_aa(primary):
    p = project()
    t = build_theme(p, {"primary": primary, "accent": primary})
    assert contrast(t.primary, t.on_primary) >= 4.5 and contrast(t.accent, t.on_accent) >= 4.5
    assert contrast(t.text, t.background) >= 7 and contrast(t.muted, t.surface) >= 4.5


def test_code_fixes_what_the_model_gets_wrong():
    p = project()
    t = build_theme(p, {"primary": "green", "background": "#101010", "font": "comic", "radius": "blobby",
                        "ux_principles": ["Nice", "Show the seller's city on every card so buyers know the distance"]})
    assert t.primary == "#15803D"  # colour word converted
    assert t.background == "#F6F7F9" and t.font == "rounded" and t.radius == "round"
    assert len(t.adjustments) == 3
    assert "Nice" not in t.ux_principles and t.ux_principles[-1].startswith("Show the seller's city")
    assert t.ux_principles[0].startswith("Search first")  # the domain's own principles stay


def test_explicit_asks_in_the_direction_win():
    hints, notes = direction_hints("Premium: dark blue with a gold accent, classic serif, easy to read for older users")
    assert hints["primary"] == "#1E3A8A" and hints["accent"] == to_hex("gold") and hints["font"] == "serif"
    assert hints["text_scale"] == 1.15 and notes
    p = project()
    p.ui_direction = "dark blue with a gold accent, for older users"
    t = build_theme(p, {"primary": "#0D3B5C", "accent": "#F59E0B"})
    assert t.primary == "#1E3A8A" and t.text_scale == 1.15 and t.source == "client_direction"
    assert any("the direction asks for" in a for a in t.adjustments)
    assert direction_hints("modern sans-serif, purple")[0] == {"primary": to_hex("purple"), "font": "sans"}


def test_theme_file_carries_every_token():
    p = project()
    p.design.theme = build_theme(p, {"primary": "#7E22CE"})
    ts = theme_ts(p)
    assert '"primary": "#7E22CE"' in ts and '"onPrimary"' in ts and '"textScale": 1.0' in ts and "as const" in ts
    assert '"fontFamily": null' in theme_ts(p, mobile=True)


def test_set_direction_and_apply_only_touches_theme_files(settings, fake_llm):
    deps = Deps(settings=settings, llm=fake_llm)
    p = project()
    p.id = deps.store.create("x").id
    deps.store.save(p)
    git = FakeGitHost()
    add_starter_apps(deps, p.id, git)
    p = set_ui_direction(deps, p.id, "fresh green market feel")
    assert p.design.theme.source == "client_direction" and p.design.theme.primary == "#15803D"
    before, develop_before = len(git.commits), dict(git.branches["develop"])
    apply_theme(deps, p.id, git)
    branch, message = git.commits[-1]
    assert len(git.commits) == before + 1 and branch.startswith("feature/T-000-ui-theme-")
    changed = {k for k, v in git.branches["develop"].items() if develop_before.get(k) != v}
    assert changed == set(theme_files(p)) == {"apps/admin/src/theme.ts", "apps/web/src/theme.ts", "apps/mobile/src/theme.ts"}
    apply_theme(deps, p.id, git)  # nothing changed: no new commit
    assert len(git.commits) == before + 1


def test_stage4_puts_a_theme_on_the_design(settings, fake_llm):
    from test_stage4 import client_approved
    from conftest import fake_read_url
    from sdlc_agent.orchestrator import run_stage4
    deps = Deps(settings=settings, llm=fake_llm, read_url=fake_read_url, check_link=lambda url: True)
    p = run_stage4(deps, client_approved(deps).id)
    assert p.design.theme is not None and p.design.theme.source == "domain_default"
    assert any(n.split(" ", 2)[2].startswith("UI theme (domain default)") for n in p.notes)
