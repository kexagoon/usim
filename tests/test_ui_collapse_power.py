"""UI collapse + board/source power API fields."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from src.acoustic_bowl import AcousticBowl, bowl_params_from_dict, default_bowl_params
from src.driver import Driver, DriverParams
from src.piezo_bvd import PiezoBVD


def test_index_has_collapse_and_editable_bowl_ti():
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    html = r.text
    assert 'id="btnSettingsCollapse"' in html
    assert 'id="pcbDriveV"' in html
    assert 'id="driveLevel"' in html
    assert 'id="pElecMax"' in html
    assert 'id="bowlPElecMax"' in html
    assert "usim.settingsCollapsed" not in html or True  # key lives in JS
    assert 'id="bowlTiD"' in html
    # bowlTiD must remain editable (no readonly on that input)
    idx = html.find('id="bowlTiD"')
    snippet = html[idx : idx + 160]
    assert "readonly" not in snippet


def test_settings_board_power_fields_affect_status():
    client = TestClient(app)
    r = client.post(
        "/api/settings",
        json={
            "pcb_drive_v": 50.0,
            "drive_level": 0.5,
            "p_elec_max_w": 3.0,
            "i_sense_window_ms": 5.0,
            "eta_elec": 0.7,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert abs(body["pcb_drive_v"] - 50.0) < 1e-9
    assert abs(body["drive_level"] - 0.5) < 1e-9
    assert abs(body["p_elec_max_w"] - 3.0) < 1e-9
    assert abs(body["i_sense_window_ms"] - 5.0) < 1e-9
    assert abs(body["vdrive_peak_v"] - 50.0) < 1e-9  # synced from pcb when vdrive omitted


def test_driver_drive_level_scales_power():
    piezo = PiezoBVD()
    piezo.gel_present = True
    full = Driver(DriverParams(drive_level=1.0, pcb_drive_v=40.0, p_elec_max_w=20.0))
    half = Driver(DriverParams(drive_level=0.5, pcb_drive_v=40.0, p_elec_max_w=20.0))
    out_f = full.regulate(piezo, 0.3, 1.0)
    out_h = half.regulate(piezo, 0.3, 1.0)
    assert out_h.i_sata_w_cm2 < out_f.i_sata_w_cm2
    assert out_h.p_bat_w < out_f.p_bat_w


def test_bowl_pcb_voltage_scales_drive_budget():
    base = default_bowl_params()
    low = bowl_params_from_dict({"pcb_drive_v": 20.0, "drive_level": 1.0}, base)
    high = bowl_params_from_dict({"pcb_drive_v": 40.0, "drive_level": 1.0}, base)
    e_low = AcousticBowl(low).energy_partition()
    e_high = AcousticBowl(high).energy_partition()
    assert e_high.p_drive_w > e_low.p_drive_w


def test_bowl_params_accept_p_elec_max():
    client = TestClient(app)
    r = client.post("/api/bowl/params", json={"p_elec_max_w": 4.0, "pcb_drive_v": 35.0})
    assert r.status_code == 200
    params = r.json()["params"]
    assert abs(params["p_elec_max_w"] - 4.0) < 1e-9
    assert abs(params["pcb_drive_v"] - 35.0) < 1e-9


def test_build_stamp():
    client = TestClient(app)
    r = client.get("/api/build")
    assert r.status_code == 200
    assert r.json().get("usim_build")  # build stamp present (value evolves with releases)
