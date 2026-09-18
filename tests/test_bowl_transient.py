"""Coupled thermal–acoustic transient for Akustik-Schale (calibration)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from src.acoustic_bowl import AcousticBowl, bowl_params_from_dict, default_bowl_params
from src.bowl_transient import (
    default_thermal_params,
    derate_factor,
    run_bowl_transient,
    suggest_dt,
    thermal_params_from_dict,
)


def test_suggest_dt_adaptive():
    assert suggest_dt(10) == 0.05
    assert 0.05 <= suggest_dt(60) <= 0.5
    assert suggest_dt(600) == 0.5


def test_transient_heats_piezo_into_gel():
    bowl = AcousticBowl(default_bowl_params())
    th = default_thermal_params()
    th.t_warn_c = 90.0
    th.t_off_c = 100.0
    r = run_bowl_transient(bowl, duration_s=10.0, dt_s=0.1, thermal=th)
    assert r["summary"]["dT_piezo_c"] > 1.0
    assert r["summary"]["T_piezo_max_c"] > th.t0_c + 1.0
    assert len(r["series"]["t_s"]) > 5
    assert r["series"]["P_ac_w"][0] > 0.0


def test_air_load_more_piezo_heat_than_gel():
    th = default_thermal_params()
    th.t_warn_c = 90.0
    th.t_off_c = 100.0
    gel = run_bowl_transient(
        AcousticBowl(default_bowl_params()), duration_s=10.0, dt_s=0.1, thermal=th
    )
    air = run_bowl_transient(
        AcousticBowl(bowl_params_from_dict({"load": "air"})),
        duration_s=10.0,
        dt_s=0.1,
        thermal=th,
    )
    assert air["series"]["P_piezo_heat_w"][0] > gel["series"]["P_piezo_heat_w"][0]
    assert air["summary"]["dT_piezo_c"] > gel["summary"]["dT_piezo_c"]


def test_longer_duration_higher_delta_t():
    th = default_thermal_params()
    th.t_warn_c = 90.0
    th.t_off_c = 100.0
    short = run_bowl_transient(
        AcousticBowl(default_bowl_params()), duration_s=5.0, dt_s=0.1, thermal=th
    )
    long = run_bowl_transient(
        AcousticBowl(default_bowl_params()), duration_s=60.0, dt_s=0.2, thermal=th
    )
    assert long["summary"]["dT_piezo_c"] > short["summary"]["dT_piezo_c"]


def test_derate_engages_near_t_off():
    th = default_thermal_params()
    th.t_warn_c = 30.0
    th.t_off_c = 40.0
    th.derate_smooth = True
    r = run_bowl_transient(
        AcousticBowl(default_bowl_params()), duration_s=60.0, dt_s=0.2, thermal=th
    )
    assert r["summary"]["derate_engaged"] is True
    assert r["summary"]["derate_min"] < 0.95
    assert any(e["kind"] == "engage" for e in r["summary"]["derate_events"])


def test_derate_factor_bounds():
    th = default_thermal_params()
    th.t_warn_c = 55.0
    th.t_off_c = 70.0
    assert derate_factor(25.0, th) == 1.0
    assert derate_factor(70.0, th) == 0.0
    mid = derate_factor(62.5, th)
    assert 0.0 < mid < 1.0


def test_glue_loss_factor_rises_with_temperature():
    th = default_thermal_params()
    th.t_warn_c = 90.0
    th.t_off_c = 100.0
    th.k_glue_loss_per_c = 0.03
    r = run_bowl_transient(
        AcousticBowl(default_bowl_params()), duration_s=20.0, dt_s=0.15, thermal=th
    )
    assert r["series"]["glue_loss_factor"][-1] > r["series"]["glue_loss_factor"][0]


def test_params_restored_after_transient():
    bowl = AcousticBowl(default_bowl_params())
    drive0 = bowl.params.drive_level
    eff0 = bowl.params.stack_efficiency
    run_bowl_transient(bowl, duration_s=5.0, dt_s=0.1)
    assert bowl.params.drive_level == drive0
    assert abs(bowl.params.stack_efficiency - eff0) < 1e-12


def test_api_transient_and_params_path():
    client = TestClient(app)
    # Analysieren path: POST params (incl. thermal) then transient
    r = client.post(
        "/api/bowl/params",
        json={
            "load": "gel_tissue",
            "drive_level": 1.0,
            "ti_diameter_m": 0.018,
            "t_amb_c": 25.0,
            "k_glue_loss_per_c": 0.02,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert abs(body["params"]["ti_diameter_m"] - 0.018) < 1e-9
    assert "thermal" in body
    assert body["thermal"]["t_amb_c"] == 25.0

    tr = client.post("/api/bowl/transient", json={"duration_s": 8, "dt_s": 0.2})
    assert tr.status_code == 200
    data = tr.json()
    assert data["calibration"] is True
    assert "series" in data and "summary" in data
    assert data["summary"]["dT_piezo_c"] > 0.0

    cached = client.get("/api/bowl/transient")
    assert cached.status_code == 200
    assert cached.json().get("cached") is True


def test_api_build_stamp_transient():
    client = TestClient(app)
    b = client.get("/api/build").json()
    assert b.get("usim_build")


def test_thermal_params_from_dict_clips():
    th = thermal_params_from_dict({"t_amb_c": 1000, "k_glue_loss_per_c": 5.0})
    assert th.t_amb_c <= 45.0
    assert th.k_glue_loss_per_c <= 0.2


def test_transient_summary_energy_start_end():
    from src.acoustic_bowl import AcousticBowl, default_bowl_params
    from src.bowl_transient import run_bowl_transient
    b = AcousticBowl(default_bowl_params())
    r = run_bowl_transient(b, duration_s=3.0, dt_s=0.5)
    s = r["summary"]
    assert "energy_start" in s and "energy_end" in s
    for k in ("p_radiated_w", "p_glue_loss_w", "p_piezo_heat_w", "p_ti_loss_w"):
        assert k in s["energy_start"] and k in s["energy_end"]
    # heated run should typically shift partition (not require strict inequality)
    assert s["energy_start"]["p_radiated_w"] >= 0
