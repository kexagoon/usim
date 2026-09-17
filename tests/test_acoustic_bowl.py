"""Acoustic bowl (чаша): transmission, glue sensitivity, air load."""

from __future__ import annotations

from src.acoustic_bowl import (
    AcousticBowl,
    bowl_params_from_dict,
    default_bowl_params,
    era_equivalent_diameter_m,
    suggested_piezo_thickness,
)
from src.propagation import alpha_from_half_value, intensity_at_depth


def test_era_equivalent_diameter():
    d = era_equivalent_diameter_m(3.0)
    assert 0.019 < d < 0.020


def test_suggested_piezo_thickness_half_wave():
    h = suggested_piezo_thickness(19e6, 4200.0)
    assert abs(h - 4200.0 / (2 * 19e6)) < 1e-12


def test_air_load_zero_transmission_and_radiation():
    p = default_bowl_params()
    p.load = "air"
    bowl = AcousticBowl(p)
    t, r, _ = bowl.transmission_reflection(p.f0_hz)
    assert t == 0.0
    assert r == 1.0
    e = bowl.energy_partition()
    assert e.p_radiated_w == 0.0
    assert e.efficiency == 0.0
    assert e.p_piezo_heat_w > 0.5 * e.p_drive_w


def test_gel_tissue_nonzero_transmission():
    bowl = AcousticBowl(default_bowl_params())
    t, r, zin = bowl.transmission_reflection(bowl.params.f0_hz)
    assert t > 0.0
    assert r >= 0.0
    assert abs(zin) > 0.0
    e = bowl.energy_partition()
    assert e.p_radiated_w > 0.0
    assert e.p_radiated_w <= 1.5 + 1e-9
    assert e.efficiency > 0.0


def test_glue_thickness_reduces_radiated_power():
    base = default_bowl_params()
    thin = AcousticBowl(bowl_params_from_dict({"glue_thickness_m": 1e-6}, base))
    thick = AcousticBowl(bowl_params_from_dict({"glue_thickness_m": 40e-6}, base))
    assert thin.energy_partition().p_radiated_w > thick.energy_partition().p_radiated_w
    sw = thin.sweep_glue(n=12)
    assert len(sw["p_ac_w"]) == 12
    assert sw["p_ac_w"][0] > sw["p_ac_w"][-1]


def test_ti_sweep_resonance_shift_present():
    bowl = AcousticBowl(default_bowl_params())
    sw = bowl.sweep_titanium(n=10)
    assert len(sw["ti_thickness_mm"]) == 10
    assert max(sw["resonance_shift_hz"]) != min(sw["resonance_shift_hz"])


def test_spectrum_and_analyze_api_shape():
    bowl = AcousticBowl(default_bowl_params())
    spec = bowl.spectrum(n=41)
    assert len(spec) == 41
    assert all(hasattr(pt, "t_intensity") for pt in spec)
    d = bowl.to_api_dict()
    assert d["calibration"] is True
    assert "energy" in d and "layers" in d
    anchors = d["anchors"]
    assert anchors.get("era_cm2") == 3.0 or anchors.get("era_cm2") == 3.0
    assert anchors.get("p_ac_max_w") == 1.5 or anchors.get("p_ac_max_w") == 1.5


def test_near_field_map_shape():
    bowl = AcousticBowl(default_bowl_params())
    nf = bowl.near_field_map(nx=16, nr=12)
    assert len(nf["z_mm"]) == 16
    assert len(nf["r_mm"]) == 12
    assert len(nf["i_w_cm2"]) == 12
    assert len(nf["i_w_cm2"][0]) == 16
    assert nf["i0_w_cm2"] <= 0.5 + 1e-9


def test_half_value_depth_anchor_still_holds():
    for xh in (0.003, 0.0015):
        a = alpha_from_half_value(xh)
        assert abs(intensity_at_depth(0.5, a, xh) - 0.25) < 1e-12


def test_piezo_diameter_clamped_to_face():
    p = bowl_params_from_dict(
        {"ti_diameter_m": 0.015, "piezo_diameter_m": 0.02},
        default_bowl_params(),
    )
    assert p.piezo_diameter_m <= p.ti_diameter_m
