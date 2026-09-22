"""Wide Ti sweep defaults + chart expand/info modal markup & i18n."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from src.acoustic_bowl import AcousticBowl, bowl_params_from_dict, default_bowl_params

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "static" / "js" / "app.js"
INDEX = ROOT / "app" / "templates" / "index.html"


def test_sweep_titanium_defaults_wide():
    sig = inspect.signature(AcousticBowl.sweep_titanium)
    assert float(sig.parameters["h_max_m"].default) >= 2.5e-3
    assert float(sig.parameters["h_min_m"].default) <= 1e-4
    assert int(sig.parameters["n"].default) >= 96


def test_api_titanium_sweep_default_max():
    client = TestClient(app)
    client.post("/api/bowl/params", json={})
    r = client.post("/api/bowl/sweep", json={"kind": "titanium", "n": 12})
    assert r.status_code == 200
    body = r.json()
    xs = body["ti_thickness_mm"]
    assert max(xs) >= 2.5  # mm
    assert min(xs) <= 0.15


def test_ti_thickness_clip_allows_3mm():
    p = bowl_params_from_dict({"ti_thickness_m": 3e-3}, default_bowl_params())
    assert abs(p.ti_thickness_m - 3e-3) < 1e-9


def test_js_titanium_post_body_wide():
    src = APP_JS.read_text(encoding="utf-8")
    assert "h_max_m: 3e-3" in src or "h_max_m: 3e-3" in src.replace(" ", "")
    assert "kind: \"titanium\"" in src
    assert "function openChartModal" in src
    assert "function closeChartModal" in src
    assert "chartModalCanvas" in src


def test_index_modal_and_chart_tools():
    html = INDEX.read_text(encoding="utf-8")
    assert 'id="chartModal"' in html
    assert 'id="chartModalCanvas"' in html
    assert 'id="chartModalInfo"' in html
    assert 'data-chart-expand="chartBowlTi"' in html
    assert 'data-chart-expand="chartBowlSpectrum"' in html
    assert 'data-chart-expand="chartBowlTemps"' in html
    assert 'id="bowlTiH"' in html
    idx = html.find('id="bowlTiH"')
    snippet = html[idx : idx + 120]
    assert 'max="3.0"' in snippet or "max='3.0'" in snippet


def test_locale_info_keys_de_ru():
    required = [
        "expand",
        "info",
        "modal_close",
        "info_spectrum",
        "info_glue",
        "info_ti",
        "info_energy",
        "info_field",
        "info_dia",
        "info_f0",
        "info_profile",
        "info_phase",
        "info_temps",
        "info_pacEta",
        "info_derate",
        "info_losses",
    ]
    for lang in ("de", "ru"):
        data = json.loads((ROOT / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
        bowl = data["bowl"]
        for key in required:
            assert key in bowl, f"missing bowl.{key} in {lang}"
            assert isinstance(bowl[key], str) and len(bowl[key]) > 2
        assert "CALIBRATION" in bowl["info_ti"] or "калибр" in bowl["info_ti"].lower()
        # Professional detail: formulas / hand-check sections
        assert len(bowl["info_temps"]) > 800
        assert "energy_partition" in bowl["info_temps"] or "Q_p" in bowl["info_temps"] or "Q_p" in bowl["info_spectrum"]
        for ik in ("info_spectrum", "info_temps", "info_energy"):
            assert "Z" in bowl[ik] or "Q_" in bowl[ik] or "P_drive" in bowl[ik] or "derate" in bowl[ik]
        assert "btn_temps_refresh" in bowl
        therapy = data["therapy"]
        for tk in ("info_ix", "info_tx", "info_dose", "info_soc", "info_burst", "info_fsm"):
            assert tk in therapy and len(therapy[tk]) > 80


def test_build_stamp_chart_expand():
    client = TestClient(app)
    r = client.get("/api/build")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == "1.3.4-ti-shape"
    assert "ti-shape-wave" in body["usim_build"]
