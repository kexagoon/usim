"""Energieaufteilung per-chart refresh + glue_spread_scenario wiring."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from src.acoustic_bowl import (
    AcousticBowl,
    BowlParams,
    GLUE_SPREAD_SCENARIOS,
    resolve_glue_spread,
)

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "static" / "js" / "app.js"
INDEX = ROOT / "app" / "templates" / "index.html"


def test_energy_refresh_button_in_html():
    html = INDEX.read_text(encoding="utf-8")
    assert 'id="btnBowlEnergyRefresh"' in html
    assert "bowl.btn_energy_refresh" in html
    assert 'data-chart-expand="chartBowlEnergy"' in html
    assert 'id="bowlGlueSpread"' in html
    assert 'data-glue-spread="ideal"' in html
    assert 'id="bowlGlueCoverage"' in html


def test_energy_destroy_recreate_helpers_in_js():
    src = APP_JS.read_text(encoding="utf-8")
    assert "function buildEnergyChart" in src
    assert "function ensureEnergyChartFresh" in src
    assert "function refreshBowlEnergyOnly" in src
    assert 'postJSON("/api/bowl/energy"' in src
    assert "ensureEnergyChartFresh" in src
    # transient path hardens energy chart (applyEnergyDoughnut always destroy+recreates)
    start = src.find("function renderBowlTransient")
    end = src.find("async function refreshBowlTempsOnly", start)
    body = src[start:end]
    assert "applyEnergyDoughnut" in body
    assert "cloneEnergyParts" in body or "applyEnergyDoughnut" in body
    assert "function ensureEnergyChartFresh" in src
    assert 'type: "bar"' in src  # energy uses bar for freeze reliability


def test_glue_spread_scenarios_resolve():
    for key in GLUE_SPREAD_SCENARIOS:
        gs = resolve_glue_spread(key)
        assert gs.key == key
        assert 0.2 <= gs.coverage <= 1.0
        assert gs.attn_mul > 0
        assert gs.w_glue_mul > 0


def test_glue_spread_affects_energy_partition():
    ideal = AcousticBowl(BowlParams(glue_spread_scenario="ideal")).energy_partition()
    islands = AcousticBowl(BowlParams(glue_spread_scenario="islands")).energy_partition()
    thick = AcousticBowl(BowlParams(glue_spread_scenario="thick_fillet")).energy_partition()
    assert islands.p_radiated_w < ideal.p_radiated_w
    assert thick.p_glue_loss_w > ideal.p_glue_loss_w

    bias_p = AcousticBowl(BowlParams(glue_spread_scenario="bias_piezo")).energy_partition()
    bias_t = AcousticBowl(BowlParams(glue_spread_scenario="bias_ti")).energy_partition()
    share_p = bias_p.p_piezo_heat_w / max(bias_p.p_piezo_heat_w + bias_p.p_ti_loss_w, 1e-12)
    share_t = bias_t.p_piezo_heat_w / max(bias_t.p_piezo_heat_w + bias_t.p_ti_loss_w, 1e-12)
    assert share_p > share_t


def test_api_bowl_energy_endpoint():
    client = TestClient(app)
    # set params with scenario
    r = client.post(
        "/api/bowl/params",
        json={
            "glue_spread_scenario": "thick_fillet",
            "glue_coverage": 0.9,
            "drive_level": 1.0,
        },
    )
    assert r.status_code == 200
    assert r.json()["params"]["glue_spread_scenario"] == "thick_fillet"

    cold = client.get("/api/bowl/energy")
    assert cold.status_code == 200
    cj = cold.json()
    assert "energy_start" in cj
    assert "p_radiated_w" in cj["energy_start"]
    assert cj["glue_spread"]["scenario"] == "thick_fillet"

    hot = client.post(
        "/api/bowl/energy",
        json={"duration_s": 10, "dt_s": 0.2, "include_heated": True},
    )
    assert hot.status_code == 200
    hj = hot.json()
    assert hj["heated"] is True
    assert "energy_end" in hj
    assert "p_radiated_w" in hj["energy_end"]


def test_i18n_energy_glue_keys():
    import json

    for lang in ("de", "ru"):
        data = json.loads((ROOT / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
        bowl = data["bowl"]
        for key in (
            "btn_energy_refresh",
            "btn_energy_refresh_busy",
            "btn_energy_refresh_title",
            "glue_spread",
            "glue_coverage",
            "glue_spread_ideal",
            "glue_spread_thin_wet",
            "glue_spread_thick_fillet",
            "glue_spread_bias_piezo",
            "glue_spread_bias_ti",
            "glue_spread_islands",
            "help_glue_spread",
            "glue_press",
            "glue_cure",
        ):
            assert key in bowl and isinstance(bowl[key], str) and bowl[key].strip()
        assert "glue_spread" in bowl["info_energy"] or "resolve_glue_spread" in bowl["info_energy"]
