"""Frequenzvergleich: anchors 1/3/6/10/19, API, wide band, UI ids, i18n."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from src.acoustic_bowl import AcousticBowl, BowlParams, default_bowl_params
from src.frequencies import (
    ALLOWED_F0_HZ,
    COMPARE_ANCHOR_F0_HZ,
    half_value_depth_m,
    resolve_compare_f0,
    suggested_piezo_thickness_m,
)

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "static" / "js" / "app.js"
INDEX = ROOT / "app" / "templates" / "index.html"
DE = ROOT / "locales" / "de.json"
RU = ROOT / "locales" / "ru.json"


def test_resolve_compare_keeps_6mhz():
    assert resolve_compare_f0(6e6) == 6e6
    assert resolve_compare_f0(6_000_000.4) == 6e6
    assert abs(half_value_depth_m(6e6) - 0.003 * (10e6 / 6e6)) < 1e-9
    h = suggested_piezo_thickness_m(6e6)
    assert 0.2e-3 < h < 0.5e-3


def test_freq_compare_five_anchors():
    bowl = AcousticBowl(default_bowl_params())
    out = bowl.freq_compare(wide=False)
    assert out["calibration"] is True
    mhz = [r["f0_mhz"] for r in out["rows"]]
    assert mhz == [1.0, 3.0, 6.0, 10.0, 19.0]
    six = next(r for r in out["rows"] if abs(r["f0_mhz"] - 6.0) < 0.01)
    assert six["calib_only"] is True
    for r in out["rows"]:
        assert "p_ac_w" in r and "efficiency" in r and "t_at_f0" in r
        assert r["piezo_h_um"] > 0
    # therapy set unchanged
    assert set(ALLOWED_F0_HZ) == {1e6, 3e6, 10e6, 19e6}
    assert 6e6 in COMPARE_ANCHOR_F0_HZ


def test_freq_compare_uses_bond_and_shape():
    good = AcousticBowl(
        BowlParams(
            glue_spread_scenario="ideal",
            glue_press="strong",
            glue_cure_fraction=1.0,
            ti_face_shape="cup",
            drive_level=1.0,
            load="gel_tissue",
        )
    )
    bad = AcousticBowl(
        BowlParams(
            glue_spread_scenario="islands",
            glue_press="weak",
            glue_cure_fraction=0.2,
            glue_coverage=0.4,
            ti_face_shape="cone",
            drive_level=1.0,
            load="gel_tissue",
        )
    )
    g = good.freq_compare()
    b = bad.freq_compare()
    # At least at one anchor bad radiates less
    assert any(
        br["p_ac_w"] < gr["p_ac_w"]
        for gr, br in zip(g["rows"], b["rows"])
    )


def test_freq_compare_wide_band():
    bowl = AcousticBowl(default_bowl_params())
    out = bowl.freq_compare(wide=True, f_min_hz=0.5e6, f_max_hz=22e6, n_wide=41)
    w = out["wide"]
    assert w is not None
    assert len(w["f_mhz"]) == 41
    assert w["f_mhz"][0] == 0.5
    assert abs(w["f_mhz"][-1] - 22.0) < 1e-6
    assert len(w["p_ac_w"]) == 41
    assert len(w["efficiency"]) == 41
    assert len(w["t_at_f0"]) == 41
    assert w["anchor_mhz"] == [1.0, 3.0, 6.0, 10.0, 19.0]


def test_api_freq_compare():
    client = TestClient(app)
    r = client.post(
        "/api/bowl/params",
        json={
            "glue_spread_scenario": "ideal",
            "glue_press": "medium",
            "drive_level": 0.8,
            "load": "gel_tissue",
            "ti_face_shape": "cup",
        },
    )
    assert r.status_code == 200
    r = client.post("/api/bowl/freq_compare", json={"wide": False})
    assert r.status_code == 200
    body = r.json()
    assert body["calibration"] is True
    assert body["kind"] == "freq_compare"
    assert [x["f0_mhz"] for x in body["rows"]] == [1.0, 3.0, 6.0, 10.0, 19.0]
    assert "6 MHz" in body.get("note_6mhz", "") or "CALIBRATION" in body.get("note_6mhz", "")
    r2 = client.post(
        "/api/bowl/freq_compare",
        json={"wide": True, "f_min_hz": 1e6, "f_max_hz": 20e6, "n_wide": 31},
    )
    assert r2.status_code == 200
    w = r2.json()["wide"]
    assert len(w["f_mhz"]) == 31
    assert w["f_mhz"][0] == 1.0


def test_legacy_sweep_f0_still_four():
    """Therapy-set sweep kind=f0 stays {1,3,10,19}; 5-anchor is freq_compare."""
    client = TestClient(app)
    r = client.post("/api/bowl/sweep", json={"kind": "f0"})
    assert r.status_code == 200
    mhz = {row["f0_mhz"] for row in r.json()["rows"]}
    assert mhz == {1.0, 3.0, 10.0, 19.0}


def test_ui_ids_and_i18n():
    html = INDEX.read_text(encoding="utf-8")
    js = APP_JS.read_text(encoding="utf-8")
    assert 'id="bowlFreqCompareCard"' in html
    assert 'id="chartBowlF0"' in html
    assert 'id="btnBowlFreqCompareRefresh"' in html
    assert "data-expand-wide" in html
    assert "bowl.info_freq_compare" in html
    assert "/api/bowl/freq_compare" in js
    assert "refreshBowlFreqCompareOnly" in js
    assert "applyFreqCompareChart" in js
    assert "chartBowlF0: 1" in js or "chartBowlF0:1" in js.replace(" ", "")
    de = DE.read_text(encoding="utf-8")
    ru = RU.read_text(encoding="utf-8")
    for blob in (de, ru):
        assert "freq_compare" in blob
        assert "btn_freq_compare_refresh" in blob
        assert "info_freq_compare" in blob
        assert "6" in blob  # 6 MHz mention


def test_build_stamp():
    client = TestClient(app)
    body = client.get("/api/build").json()
    assert body["version"] == "1.3.5-freq-compare"
    assert "freq-compare" in body["usim_build"]
