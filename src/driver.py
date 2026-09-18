"""HF driver / matching network behavioural model."""

from __future__ import annotations

import math
from dataclasses import dataclass

from src.piezo_bvd import PiezoBVD, Z_AIR


@dataclass
class DriverParams:
    vdrive_peak_v: float = 40.0
    pcb_drive_v: float = 40.0  # board / source peak (Kalibrierung)
    eta_elec: float = 0.7
    stack_efficiency: float = 0.65
    i_max_w_cm2: float = 0.5
    era_cm2: float = 3.0
    limit_domain: str = "SATA"  # SATA | SAPA
    p_ac_max_w: float = 1.5
    drive_level: float = 1.0  # 0..1 board power fraction
    p_elec_max_w: float = 8.0  # electrical power budget (Kalibrierung)
    i_sense_window_ms: float = 2.0  # current-sense window (Kalibrierung)


@dataclass
class DriverOutput:
    vdrive_peak: float
    i_sata_w_cm2: float
    i_sapa_w_cm2: float
    p_ac_w: float
    p_elec_w: float
    p_bat_w: float
    p_piezo_loss_w: float
    eta_ea: float
    vswr: float
    contact: bool


def duty_factor(mode: str, interpretation: str = "RATIO_ON_OFF") -> float:
    """Map CONT / PR_1_2 / PR_1_5 to duty cycle D."""
    mode = mode.upper().replace("-", "_").replace(":", "_")
    if mode in ("CONT", "CONTINUOUS", "D1"):
        return 1.0
    if interpretation == "ON_OVER_PERIOD":
        if mode in ("PR_1_2", "1_2", "1:2"):
            return 0.5
        if mode in ("PR_1_5", "1_5", "1:5"):
            return 0.2
    # RATIO_ON_OFF (default Wellcomet physio convention)
    if mode in ("PR_1_2", "1_2", "1:2"):
        return 1.0 / 3.0
    if mode in ("PR_1_5", "1_5", "1:5"):
        return 1.0 / 6.0
    return 1.0


class Driver:
    """Regulate Vdrive so that I_SATA tracks I_set under load."""

    def __init__(self, params: DriverParams | None = None) -> None:
        self.params = params or DriverParams()
        self.vdrive_peak = self.params.vdrive_peak_v

    def _board_vpeak(self) -> float:
        """Peak drive from PCB/source; pcb_drive_v is authoritative when set."""
        p = self.params
        base = p.pcb_drive_v if p.pcb_drive_v > 0 else p.vdrive_peak_v
        return float(base)

    def regulate(
        self,
        piezo: PiezoBVD,
        i_set_w_cm2: float,
        duty: float,
        *,
        force_air: bool = False,
    ) -> DriverOutput:
        st = piezo.evaluate()
        params = self.params
        level = max(0.0, min(1.0, float(params.drive_level)))
        i_set = min(i_set_w_cm2 * level, params.i_max_w_cm2)
        v_board = self._board_vpeak()

        # Without gel: almost no acoustic output → energy into piezo heat
        if force_air or not st.contact or st.z_load <= Z_AIR * 10:
            p_ac = 0.0
            # Attempted acoustic budget becomes heat in the ceramic (air mismatch)
            i_req = max(i_set, 0.1)
            p_would = min(i_req, params.i_max_w_cm2) * params.era_cm2
            p_bat = p_would / max(params.stack_efficiency * params.eta_elec, 0.05)
            p_bat = max(2.0 * level, min(p_bat, min(5.0, params.p_elec_max_w)))
            p_elec = p_bat * params.eta_elec
            p_piezo_loss = p_elec  # no radiation → full heat load on piezo/face
            self.vdrive_peak = v_board
            vswr = 10.0
            return DriverOutput(
                vdrive_peak=self.vdrive_peak,
                i_sata_w_cm2=0.0,
                i_sapa_w_cm2=0.0,
                p_ac_w=p_ac,
                p_elec_w=p_elec,
                p_bat_w=p_bat,
                p_piezo_loss_w=p_piezo_loss,
                eta_ea=0.0,
                vswr=vswr,
                contact=False,
            )

        # With gel: regulate to I_set
        # I_SAPA from surface; I_SATA = I_SAPA * D
        if params.limit_domain == "SAPA":
            i_sapa = min(i_set, params.i_max_w_cm2)
            i_sata = i_sapa * duty
        else:
            i_sata = min(i_set, params.i_max_w_cm2)
            i_sapa = i_sata / max(duty, 1e-9)

        p_ac = i_sata * params.era_cm2  # W (SATA * ERA)
        p_ac = min(p_ac, params.p_ac_max_w)

        # Re-derive intensities after P_ac clamp
        i_sata = p_ac / params.era_cm2
        i_sapa = i_sata / max(duty, 1e-9)

        eta_total = params.stack_efficiency * params.eta_elec
        p_elec = p_ac / max(eta_total, 0.05)
        p_bat = p_elec  # already referred through eta_elec in eta_total split
        # More precise: P_bat = P_ac / (stack_eff * eta_elec)
        p_bat = p_ac / max(params.stack_efficiency * params.eta_elec, 0.05)
        # Clamp to board electrical power budget (Kalibrierung)
        if p_bat > params.p_elec_max_w > 0:
            scale = params.p_elec_max_w / p_bat
            p_bat = params.p_elec_max_w
            p_ac *= scale
            i_sata = p_ac / params.era_cm2
            i_sapa = i_sata / max(duty, 1e-9)
        p_elec = p_bat * params.eta_elec
        p_piezo_loss = p_bat * params.eta_elec * (1.0 - params.stack_efficiency)

        # Adjust Vdrive proportionally to required I (board peak = PCB/source)
        self.vdrive_peak = v_board * math.sqrt(
            max(i_sata, 1e-6) / params.i_max_w_cm2
        )

        # VSWR proxy from R1 vs matched
        vswr = 1.0 + 0.1 * (st.r1 / max(piezo.params.r_m, 1e-9) - 1.0)
        vswr = max(1.0, min(vswr, 3.0))

        return DriverOutput(
            vdrive_peak=self.vdrive_peak,
            i_sata_w_cm2=i_sata,
            i_sapa_w_cm2=i_sapa,
            p_ac_w=p_ac,
            p_elec_w=p_elec,
            p_bat_w=p_bat,
            p_piezo_loss_w=p_piezo_loss,
            eta_ea=params.stack_efficiency,
            vswr=vswr,
            contact=True,
        )
