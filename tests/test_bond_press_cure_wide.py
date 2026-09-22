"""Bond press/cure compose + layer wiring + energy bar anti-freeze + wide expand + default tab."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from src.acoustic_bowl import (
    AcousticBowl,
    BowlParams,
    bond_factors_from_params,
    normalize_glue_cure,
    normalize_glue_press,
    resolve_glue_spread,
)

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "static" / "js" / "app.js"
INDEX = ROOT / "app" / "templates" / "index.html"


def test_normalize_press_cure():
    assert normalize_glue_press("stark") == "strong"
    assert normalize_glue_press("schwach") == "weak"
    assert normalize_glue_cure("uncured") == 0.15
    assert normalize_glue_cure(55) == 0.55  # percent
    assert normalize_glue_cure(0.8) == 0.8


def test_press_cure_compose_with_spread():
    base = resolve_glue_spread("ideal", 1.0, "medium", 1.0)
    weak = resolve_glue_spread("ideal", 1.0, "weak", 0.15)
    strong = resolve_glue_spread("ideal", 1.0, "strong", 1.0)
    assert weak.coverage < base.coverage
    assert weak.attn_mul > base.attn_mul
    assert weak.g_pg_mul < base.g_pg_mul
    assert strong.mismatch_mul <= base.mismatch_mul
    assert strong.g_gt_mul >= base.g_gt_mul


def test_bond_affects_spectrum_and_energy():
    """Audit: glue bond factors must reach transfer matrix (spectrum/|T|) AND energy."""
    good = AcousticBowl(
        BowlParams(glue_spread_scenario="ideal", glue_press="strong", glue_cure_fraction=1.0)
    )
    bad = AcousticBowl(
        BowlParams(glue_spread_scenario="islands", glue_press="weak", glue_cure_fraction=0.15)
    )
    t_g, _, zg = good.transmission_reflection(good.params.f0_hz)
    t_b, _, zb = bad.transmission_reflection(bad.params.f0_hz)
    assert t_b < t_g
    assert bad.energy_partition().p_radiated_w < good.energy_partition().p_radiated_w
    glue_g = next(ly for ly in good.build_layers() if ly.name == "glue")
    glue_b = next(ly for ly in bad.build_layers() if ly.name == "glue")
    assert glue_b.material.attenuation_np_m_mhz > glue_g.material.attenuation_np_m_mhz
    assert glue_b.diameter_m < glue_g.diameter_m


def test_sweeps_use_bond_via_energy():
    ideal = AcousticBowl(BowlParams(glue_spread_scenario="ideal", glue_press="medium"))
    thick = AcousticBowl(BowlParams(glue_spread_scenario="thick_fillet", glue_press="medium"))
    s_i = ideal.sweep_glue(n=8)
    s_t = thick.sweep_glue(n=8)
    assert max(s_t["p_ac_w"]) < max(s_i["p_ac_w"]) or max(s_t["efficiency"]) <= max(s_i["efficiency"])


def test_api_params_press_cure():
    client = TestClient(app)
    r = client.post(
        "/api/bowl/params",
        json={"glue_press": "strong", "glue_cure_fraction": 0.55, "glue_spread_scenario": "thin_wet"},
    )
    assert r.status_code == 200
    p = r.json()["params"]
    assert p["glue_press"] == "strong"
    assert abs(p["glue_cure_fraction"] - 0.55) < 1e-6
    en = client.get("/api/bowl/energy").json()
    assert en["glue_spread"]["press"] == "strong"
    assert abs(en["glue_spread"]["cure_fraction"] - 0.55) < 1e-6


def test_field_z_max_and_spectrum_wide_span():
    client = TestClient(app)
    client.post("/api/bowl/params", json={})
    wide = client.get("/api/bowl/spectrum?n=41&span=0.8")
    assert wide.status_code == 200
    assert wide.json()["span"] == 0.8
    f = wide.json()["f_hz"]
    assert max(f) / min(f) > 1.5
    field = client.get("/api/bowl/field?nx=20&nr=12&z_max_m=0.02")
    assert field.status_code == 200
    assert max(field.json()["z_mm"]) >= 19.0


def test_js_energy_bar_recreate_and_wide():
    src = APP_JS.read_text(encoding="utf-8")
    assert 'type: "bar"' in src
    assert "indexAxis: \"y\"" in src or "indexAxis: 'y'" in src
    assert "function ensureEnergyChartFresh" in src
    assert "cloneEnergyParts" in src
    assert "fetchWideChartConfig" in src
    assert 'switchTab("bowl")' in src
    assert "setGluePress" in src and "setGlueCure" in src
    assert "glue_press:" in src and "glue_cure_fraction:" in src
    # applyEnergy always recreates (no recreate:false path left for energy refresh)
    assert 'applyEnergyDoughnut(bowlEnergyPhase || "end", { recreate: false })' not in src


def test_html_default_bowl_and_press_cure():
    html = INDEX.read_text(encoding="utf-8")
    assert 'data-tab="bowl"' in html
    # bowl tab button has active
    idx = html.find('data-tab="bowl"')
    assert "active" in html[max(0, idx - 40) : idx + 20]
    assert 'id="tab-therapy"' in html and 'class="therapy-layout hidden"' in html
    assert 'id="bowlGluePress"' in html
    assert 'id="bowlGlueCure"' in html
    assert 'data-glue-press="strong"' in html
    assert 'data-glue-cure="uncured"' in html
    assert 'data-expand-wide="1"' in html


def test_i18n_press_cure_keys():
    for lang in ("de", "ru"):
        data = json.loads((ROOT / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
        bowl = data["bowl"]
        for key in (
            "glue_press", "glue_press_strong", "glue_press_medium", "glue_press_weak",
            "help_glue_press", "glue_cure", "glue_cure_cured", "glue_cure_partial",
            "glue_cure_uncured", "help_glue_cure", "expand_wide_note",
        ):
            assert key in bowl and bowl[key].strip()
        assert "resolve_glue_spread" in bowl["help_glue_spread"] or "Bond" in bowl["help_glue_spread"] or "bond" in bowl["help_glue_spread"].lower()


def test_build_stamp_bond_wide():
    client = TestClient(app)
    body = client.get("/api/build").json()
    assert body["version"] == "1.3.4-ti-shape"
    assert "ti-shape" in body["usim_build"]
