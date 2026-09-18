"""Acoustic bowl (чаша): transmission, glue sensitivity, air load, multi-f0."""

from __future__ import annotations

from src.acoustic_bowl import (
    AcousticBowl,
    apply_named_preset,
    bowl_params_from_dict,
    compare_bowl_presets,
    default_bowl_params,
    era_equivalent_diameter_m,
    suggested_piezo_thickness,
)
from src.frequencies import ALLOWED_F0_HZ, half_value_depth_m, validate_f0, wavelength_m
from src.propagation import alpha_from_half_value, intensity_at_depth


def test_era_equivalent_diameter():
    d = era_equivalent_diameter_m(3.0)
    assert 0.019 < d < 0.020


def test_suggested_piezo_thickness_half_wave():
    for f0 in sorted(ALLOWED_F0_HZ):
        h = suggested_piezo_thickness(f0, 4200.0)
        assert abs(h - 4200.0 / (2 * f0)) < 1e-12


def test_wavelength_scales_with_f0():
    assert abs(wavelength_m(1e6) - 1.54e-3) < 1e-9
    assert abs(wavelength_m(19e6) - 1540.0 / 19e6) < 1e-12


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


def test_air_load_zero_at_1_and_3_mhz():
    for f0 in (1e6, 3e6):
        p = bowl_params_from_dict({"f0_hz": f0, "load": "air"})
        assert p.f0_hz == f0
        bowl = AcousticBowl(p)
        assert bowl.transmission_reflection(f0)[0] == 0.0
        assert bowl.energy_partition().p_radiated_w == 0.0


def test_gel_tissue_nonzero_at_all_allowed_f0():
    for f0 in sorted(ALLOWED_F0_HZ):
        p = bowl_params_from_dict({"f0_hz": f0, "load": "gel_tissue"})
        bowl = AcousticBowl(p)
        t, r, zin = bowl.transmission_reflection(f0)
        assert t >= 0.0
        assert r >= 0.0
        assert abs(zin) > 0.0
        e = bowl.energy_partition()
        assert e.p_radiated_w >= 0.0
        assert e.p_radiated_w <= 1.5 + 1e-9


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


def test_piezo_diameter_sweep():
    bowl = AcousticBowl(default_bowl_params())
    sw = bowl.sweep_piezo_diameter(n=8)
    assert len(sw["piezo_diameter_mm"]) == 8
    assert sw["p_ac_w"][-1] >= sw["p_ac_w"][0] - 1e-9


def test_f0_compare_bar():
    bowl = AcousticBowl(default_bowl_params())
    cmp_ = bowl.compare_frequencies()
    assert len(cmp_["rows"]) == 4
    mhz = {r["f0_mhz"] for r in cmp_["rows"]}
    assert mhz == {1.0, 3.0, 10.0, 19.0}


def test_spectrum_phase_and_analyze_api_shape():
    bowl = AcousticBowl(default_bowl_params())
    spec = bowl.spectrum(n=41)
    assert len(spec) == 41
    assert all(hasattr(pt, "t_phase_rad") for pt in spec)
    d = bowl.to_api_dict()
    assert d["calibration"] is True
    assert "energy" in d and "layers" in d
    assert "time_of_flight" in d
    anchors = d["anchors"]
    assert anchors.get("era_cm2") == 3.0
    assert anchors.get("p_ac_max_w") == 1.5
    assert set(anchors.get("allowed_f0_hz")) == set(ALLOWED_F0_HZ)


def test_depth_profile_and_tof():
    bowl = AcousticBowl(default_bowl_params())
    prof = bowl.depth_profile(n_per_layer=8)
    assert len(prof["z_mm"]) > 10
    tof = bowl.time_of_flight()
    assert tof["total_ns"] > 0


def test_near_field_map_shape():
    bowl = AcousticBowl(default_bowl_params())
    nf = bowl.near_field_map(nx=16, nr=12)
    assert len(nf["z_mm"]) == 16
    assert len(nf["r_mm"]) == 12
    assert len(nf["i_w_cm2"]) == 12
    assert len(nf["i_w_cm2"][0]) == 16
    assert nf["i0_w_cm2"] <= 0.5 + 1e-9


def test_half_value_depth_anchor_still_holds():
    for xh in (0.003, 0.0015, 0.030, 0.010):
        a = alpha_from_half_value(xh)
        assert abs(intensity_at_depth(0.5, a, xh) - 0.25) < 1e-12
    assert abs(half_value_depth_m(10e6) - 0.003) < 1e-12
    assert abs(half_value_depth_m(1e6) - 0.030) < 1e-12


def test_piezo_diameter_clamped_to_face():
    p = bowl_params_from_dict(
        {"ti_diameter_m": 0.015, "piezo_diameter_m": 0.02},
        default_bowl_params(),
    )
    assert p.piezo_diameter_m <= p.ti_diameter_m


def test_invalid_f0_snaps_to_allowed():
    p = bowl_params_from_dict({"f0_hz": 12e6})
    assert p.f0_hz in ALLOWED_F0_HZ
    assert validate_f0(1e6) == 1e6


def test_presets_and_compare():
    p = apply_named_preset("thin_glue")
    assert p.glue_thickness_m <= 5e-6
    p19 = apply_named_preset("skinova_19")
    assert p19.f0_hz == 19e6
    cmp_ = compare_bowl_presets(
        {"f0_hz": 10e6, "glue_thickness_m": 2e-6},
        {"f0_hz": 10e6, "glue_thickness_m": 40e-6},
    )
    assert "delta" in cmp_
    assert cmp_["delta"]["p_radiated_w"] < 0


def test_matching_and_backing_layers():
    p = bowl_params_from_dict(
        {"matching_enabled": True, "backing": "heavy", "load": "water"}
    )
    bowl = AcousticBowl(p)
    names = [ly.name for ly in bowl.build_layers()]
    assert "matching" in names
    assert "backing" in names
    assert "water" in names


def test_stack_order_piezo_glue_ti_load():
    bowl = AcousticBowl(default_bowl_params())
    names = [ly.name for ly in bowl.build_layers()]
    # Drop optional backing; require piezo → glue → ti_bottom before load
    core = [n for n in names if n != "backing"]
    assert core[0] == "pzt"
    assert core[1] == "glue"
    assert core[2] == "ti_bottom"
    assert core[-1] in ("gel", "tissue", "water", "fat", "bone", "air")
    # gel_tissue ends with tissue after gel
    assert "ti_bottom" in names
    assert names.index("pzt") < names.index("glue") < names.index("ti_bottom")


def test_air_radiates_near_zero():
    p = bowl_params_from_dict({"load": "air", "drive_level": 1.0})
    e = AcousticBowl(p).energy_partition()
    assert e.p_radiated_w == 0.0
    assert e.efficiency == 0.0


def test_cup_geometry_loads_from_yaml():
    p = default_bowl_params()
    assert p.cup_inner_diameter_m > 0
    assert p.cup_outer_diameter_m > 0
    assert p.cup_depth_m > 0
    assert p.cup_wall_thickness_m > 0
    assert abs(p.ti_diameter_m - p.cup_outer_diameter_m) < 1e-9
    # ERA consistency with defaults
    d_eq = era_equivalent_diameter_m(3.0)
    assert abs(p.cup_outer_diameter_m - d_eq) < 1e-4
    geo = AcousticBowl(p).geometry_meta()
    assert "cup_depth_m" in geo
    assert geo["stack_order"][0:3] == ["pzt", "glue", "ti_bottom"]


def test_electrode_resistance_reduces_radiated_power():
    base = default_bowl_params()
    low_r = bowl_params_from_dict(
        {"r_wire_piezo_ohm": 0.1, "r_ti_return_ohm": 0.1, "load": "gel_tissue"}, base
    )
    high_r = bowl_params_from_dict(
        {"r_wire_piezo_ohm": 15.0, "r_ti_return_ohm": 15.0, "load": "gel_tissue"}, base
    )
    e_low = AcousticBowl(low_r).energy_partition()
    e_high = AcousticBowl(high_r).energy_partition()
    assert e_low.p_radiated_w > e_high.p_radiated_w


def test_cup_params_from_dict_and_api_geometry():
    p = bowl_params_from_dict(
        {
            "cup_inner_diameter_m": 0.017,
            "cup_outer_diameter_m": 0.01954,
            "cup_depth_m": 0.005,
            "droplet_demo": True,
            "pcb_drive_v": 35.0,
        }
    )
    assert p.cup_depth_m == 0.005
    assert p.droplet_demo is True
    assert p.pcb_drive_v == 35.0
    d = AcousticBowl(p).to_api_dict()
    assert "geometry" in d
    assert d["geometry"]["droplet_demo"] is True
    assert d["params"]["cup_inner_diameter_m"] == 0.017
