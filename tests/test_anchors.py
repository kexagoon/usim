"""Seven validation anchors from SPEC part N — must all pass."""

from __future__ import annotations

from typing import Any

from src.driver import duty_factor
from src.fsm_sonotrode import FSMState
from src.propagation import Propagation, alpha_from_half_value, intensity_at_depth
from src.simulation import Simulation, SimulationConfig


def test_anchor_1_f0_home_only_10_or_19() -> None:
    """1. Home manufacturer defaults are 10/19 MHz; allowed sim set is {1,3,10,19}."""
    from src.frequencies import ALLOWED_F0_HZ

    for model, expected in (
        ("SKINOVA_10", 10e6),
        ("SKINOVA_MED", 10e6),
        ("SKINOVA_19", 19e6),
    ):
        sim = Simulation(SimulationConfig(model=model, seed=1))
        assert sim.f0 in (10e6, 19e6)
        assert sim.f0 == expected
        assert sim.f0 == float(sim.devices["models"][model]["f0_hz"])

    # Explicit selection of 1/3 MHz must not crash and must stay in allowed set
    for f0 in (1e6, 3e6, 10e6, 19e6):
        sim = Simulation(SimulationConfig(model="SKINOVA_10", seed=1, f0_hz_override=f0))
        assert sim.f0 == f0
        assert sim.f0 in ALLOWED_F0_HZ
        assert sim.x_half > 0
        _ = sim.prop.profile(0.3)

    assert ALLOWED_F0_HZ == frozenset({1e6, 3e6, 10e6, 19e6})


def test_anchor_2_i_sata_le_0_5() -> None:
    """2. I_SATA ≤ 0.5 W/cm²."""
    sim = Simulation(SimulationConfig(model="SKINOVA_10", seed=2, i_set_override=0.5))
    sim.load_program(1)
    sim.set_gel(True)
    sim.set_path("circle")
    sim.start()
    for s in sim.run_for(0.5, dt_s=0.005):
        assert s.i_sata <= 0.5 + 1e-9

    sim2 = Simulation(SimulationConfig(model="SKINOVA_19", seed=2, i_set_override=0.9))
    blob = sim2.load_program(1)
    assert blob.i_set <= 0.5


def test_anchor_3_p_ac_le_1_5() -> None:
    """3. P_ac ≤ 1.5 W."""
    sim = Simulation(
        SimulationConfig(
            model="SKINOVA_19",
            seed=3,
            i_set_override=0.5,
            mode_override="CONT",
        )
    )
    sim.load_program(1)
    sim.set_gel(True)
    sim.start()
    for s in sim.run_for(0.3, dt_s=0.005):
        assert s.p_ac <= 1.5 + 1e-9


def test_anchor_4_no_gel_pac_zero_t_rises() -> None:
    """4. Without gel P_ac≈0 and T_piezo rises."""
    sim = Simulation(
        SimulationConfig(
            model="SKINOVA_10",
            seed=4,
            gel_present=False,
            i_set_override=0.5,
            mode_override="CONT",
        )
    )
    sim.load_program(1)
    sim.set_gel(False)
    t0 = sim.piezo_th.t_c
    max_pac = 0.0
    for _ in range(200):
        sim.piezo.gel_present = False
        sim.piezo.gel_fraction = 0.0
        drv = sim.driver.regulate(sim.piezo, 0.5, 1.0, force_air=True)
        max_pac = max(max_pac, drv.p_ac_w)
        sim.piezo_th.step(drv.p_piezo_loss_w, 0.01, gel_present=False)
        assert sim.stack.transmission_coefficient(sim.f0, gel_present=False) == 0.0
    t1 = sim.piezo_th.t_c
    assert max_pac < 0.05
    assert t1 > t0 + 0.5


def test_anchor_5_half_value_depth() -> None:
    """5. I(x½) ≈ I0/2 for manufacturer 10/19 and calib 1/3 MHz."""
    for f0, xh in ((10e6, 0.003), (19e6, 0.0015), (1e6, 0.030), (3e6, 0.010)):
        prop = Propagation(f_hz=f0, x_half_m=xh)
        i0 = 0.5
        i_half = prop.intensity_w_cm2(i0, xh)
        assert abs(i_half - i0 / 2.0) / (i0 / 2.0) < 1e-6
        alpha = alpha_from_half_value(xh)
        assert abs(intensity_at_depth(i0, alpha, xh) - i0 / 2.0) < 1e-9


def test_anchor_6_stop_le_12_min() -> None:
    """6. Program stops ≤ 12 min."""
    sim = Simulation(
        SimulationConfig(
            model="SKINOVA_10",
            seed=6,
            duration_override_s=720,
            i_set_override=0.3,
            mode_override="CONT",
            dt_macro_s=0.05,
        )
    )
    sim.load_program(1)
    assert sim.fsm.nvm.t_total_s <= 720.0
    sim.set_gel(True)
    sim.set_path("circle")
    sim.start()
    snaps = sim.run_for(800.0, dt_s=0.5)
    assert snaps[-1].state == FSMState.FINISHED.value
    assert snaps[-1].t_s <= 720.0 + 1.0

    sim2 = Simulation(
        SimulationConfig(model="SKINOVA_19", seed=6, duration_override_s=9999)
    )
    blob = sim2.load_program(1)
    assert blob.duration_s <= 720.0


def test_anchor_7_model19_stops_overtemp_or_stillness() -> None:
    """7. Model 19 stops on overtemp or stillness."""
    # 7a stillness → FAULT_MOTION
    sim = Simulation(
        SimulationConfig(
            model="SKINOVA_19",
            seed=7,
            path="still",
            gel_present=True,
            motion_still_s=2.0,
            motion_eps=0.05,
            dt_macro_s=0.05,
        )
    )
    sim.load_program(1)
    sim.set_gel(True)
    sim.set_path("still")
    sim.start()
    snaps = sim.run_for(5.0, dt_s=0.05)
    assert any(s.state == FSMState.FAULT_MOTION.value for s in snaps)

    # 7b overtemp — low T_off, air load, isolate contact pause
    sim2 = Simulation(
        SimulationConfig(
            model="SKINOVA_19",
            seed=8,
            gel_present=False,
            path="circle",
            t_off_c=30.0,
            t_warn_c=28.0,
            motion_still_s=60.0,
            dt_macro_s=0.02,
            mode_override="CONT",
            i_set_override=0.5,
        )
    )
    sim2.load_program(1)
    sim2.set_gel(False)
    sim2.fsm.undock()
    sim2.fsm.start()
    tripped = False
    for _ in range(500):
        sim2.piezo.gel_present = False
        drv = sim2.driver.regulate(sim2.piezo, 0.5, 1.0, force_air=True)
        t_piezo = sim2.piezo_th.step(drv.p_piezo_loss_w, 0.05, gel_present=False)
        sim2.fsm.tick(
            0.05,
            contact=True,
            t_piezo_c=t_piezo,
            motion_variance=1.0,
            soc=1.0,
            emitting=True,
        )
        if sim2.fsm.state == FSMState.FAULT_OVERTEMP:
            tripped = True
            break
    assert tripped


def run_all_anchors() -> list[dict[str, Any]]:
    """Callable from API self-test panel."""
    tests = [
        ("f0_home", test_anchor_1_f0_home_only_10_or_19),
        ("i_sata", test_anchor_2_i_sata_le_0_5),
        ("p_ac", test_anchor_3_p_ac_le_1_5),
        ("no_gel", test_anchor_4_no_gel_pac_zero_t_rises),
        ("half_value", test_anchor_5_half_value_depth),
        ("tmax_12min", test_anchor_6_stop_le_12_min),
        ("model19_safety", test_anchor_7_model19_stops_overtemp_or_stillness),
    ]
    results: list[dict[str, Any]] = []
    for name, fn in tests:
        try:
            fn()
            results.append({"name": name, "pass": True, "error": None})
        except Exception as exc:  # noqa: BLE001
            results.append({"name": name, "pass": False, "error": str(exc)})
    return results


def test_duty_interpretation() -> None:
    assert abs(duty_factor("PR_1_2", "RATIO_ON_OFF") - 1 / 3) < 1e-9
    assert abs(duty_factor("PR_1_5", "RATIO_ON_OFF") - 1 / 6) < 1e-9
    assert abs(duty_factor("PR_1_2", "ON_OVER_PERIOD") - 0.5) < 1e-9
    assert abs(duty_factor("CONT", "RATIO_ON_OFF") - 1.0) < 1e-9


def test_deterministic_seed() -> None:
    a = Simulation(SimulationConfig(model="SKINOVA_10", seed=99, path="circle"))
    b = Simulation(SimulationConfig(model="SKINOVA_10", seed=99, path="circle"))
    a.load_program(1)
    b.load_program(1)
    a.start()
    b.start()
    sa = a.step(0.01)
    sb = b.step(0.01)
    assert sa.gel_thickness_m == sb.gel_thickness_m
