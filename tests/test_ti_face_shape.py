"""Titanium face shape cup|cone|hemisphere — factors, physics, diagram, round-trip."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from src.acoustic_bowl import (
    TI_FACE_SHAPES,
    AcousticBowl,
    BowlParams,
    bowl_params_from_dict,
    normalize_ti_face_shape,
    params_help,
    resolve_ti_face_shape,
)


ROOT = Path(__file__).resolve().parent.parent


def test_resolve_ti_face_shapes():
    assert set(TI_FACE_SHAPES) == {"cup", "cone", "hemisphere"}
    cup = resolve_ti_face_shape("cup")
    cone = resolve_ti_face_shape("cone")
    hemi = resolve_ti_face_shape("hemisphere")
    assert cup.focus_gain < hemi.focus_gain
    assert hemi.z_focus_mul < cup.z_focus_mul < cone.z_focus_mul
    assert cone.beam_width_mul > cup.beam_width_mul > hemi.beam_width_mul
    assert hemi.path_edge_mul > cone.path_edge_mul > cup.path_edge_mul
    assert normalize_ti_face_shape("Halbkugel") == "hemisphere"
    assert normalize_ti_face_shape("leicht konisch") == "cone"
    assert normalize_ti_face_shape("чашка") == "cup"


def test_shape_affects_near_field_and_energy():
    cup = AcousticBowl(BowlParams(ti_face_shape="cup"))
    cone = AcousticBowl(BowlParams(ti_face_shape="cone"))
    hemi = AcousticBowl(BowlParams(ti_face_shape="hemisphere"))
    nf_c = cup.near_field_map(nx=24, nr=12)
    nf_o = cone.near_field_map(nx=24, nr=12)
    nf_h = hemi.near_field_map(nx=24, nr=12)
    assert nf_h["z_focus_mm"] < nf_c["z_focus_mm"] < nf_o["z_focus_mm"]
    assert nf_h["focus_gain"] > nf_c["focus_gain"] > nf_o["focus_gain"]
    e_c = cup.energy_partition()
    e_h = hemi.energy_partition()
    assert e_h.p_radiated_w < e_c.p_radiated_w


def test_build_layers_keeps_nominal_ti_thickness():
    """Phase thickness stays nominal; shape uses attn / energy / field factors."""
    p = BowlParams(ti_thickness_m=3e-4, ti_face_shape="hemisphere")
    bowl = AcousticBowl(p)
    ti = next(ly for ly in bowl.build_layers() if ly.name == "ti_bottom")
    assert abs(ti.thickness_m - 3e-4) < 1e-12
    cup_attn = AcousticBowl(BowlParams(ti_face_shape="cup"))._materials()["titanium"].attenuation_np_m_mhz
    assert ti.material.attenuation_np_m_mhz > cup_attn


def test_wave_path_summary():
    bowl = AcousticBowl(BowlParams(ti_face_shape="cone", glue_spread_scenario="islands"))
    wp = bowl.wave_path_summary()
    assert wp["ti_face_shape"] == "cone"
    assert "t_at_f0" in wp and "loss_glue" in wp and "p_ac_w" in wp
    assert wp["z_focus_mm"] > 0
    assert wp["bond"]["scenario"] == "islands"
    assert wp["shape"]["beam_width_mul"] > 1.0


def test_params_round_trip_shape():
    p = bowl_params_from_dict({"ti_face_shape": "hemisphere", "glue_press": "strong"})
    assert p.ti_face_shape == "hemisphere"
    help_ = params_help()
    assert "hemisphere" in help_["ti_face_shapes"]
    assert "hemisphere" in help_["ti_face_shape_defaults"]


def test_api_params_and_analyze_shape():
    from app.main import app

    client = TestClient(app)
    r = client.post(
        "/api/bowl/params",
        json={"ti_face_shape": "cone", "f0_hz": 10e6},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["params"]["ti_face_shape"] == "cone"
    result = body.get("result") or {}
    assert result.get("wave_path", {}).get("ti_face_shape") == "cone"
    assert result.get("geometry", {}).get("ti_face_shape") == "cone"
    field = client.get("/api/bowl/field?nx=20&nr=10").json()
    assert field.get("ti_face_shape") == "cone"
    assert field.get("z_focus_mm", 0) > 0


def test_diagram_and_ui_presence():
    html = (ROOT / "app" / "templates" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "app" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert 'id="bowlTiFaceShape"' in html
    assert 'data-ti-face-shape="cup"' in html
    assert 'data-ti-face-shape="cone"' in html
    assert 'data-ti-face-shape="hemisphere"' in html
    assert 'id="bowlWavePathStrip"' in html
    assert "setTiFaceShape" in js
    assert "refreshSchematicLive" in js
    assert "ti_face_shape" in js
    assert "hemisphere" in js
    de = (ROOT / "locales" / "de.json").read_text(encoding="utf-8")
    ru = (ROOT / "locales" / "ru.json").read_text(encoding="utf-8")
    for key in ("ti_face_shape", "ti_face_cup", "ti_face_cone", "ti_face_hemisphere", "wave_path_title"):
        assert key in de and key in ru


def test_build_stamp_ti_shape():
    from app.main import app

    client = TestClient(app)
    body = client.get("/api/build").json()
    assert body["version"] == "1.3.4-ti-shape"
    assert "ti-shape" in body["usim_build"]
