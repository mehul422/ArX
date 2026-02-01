from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class CdTable:
    mach: list[float]
    cd: list[float]
    source: str = "custom"

    def at(self, mach: float) -> float:
        if not self.mach or not self.cd or len(self.mach) != len(self.cd):
            return 0.0
        if mach <= self.mach[0]:
            return self.cd[0]
        if mach >= self.mach[-1]:
            return self.cd[-1]
        for i in range(1, len(self.mach)):
            if mach <= self.mach[i]:
                t = (mach - self.mach[i - 1]) / max(self.mach[i] - self.mach[i - 1], 1e-9)
                return self.cd[i - 1] + t * (self.cd[i] - self.cd[i - 1])
        return self.cd[-1]


@dataclass(frozen=True)
class AeroInputs:
    nose_type: str = "ogive"
    fineness_ratio: float = 10.0
    fin_thickness_ratio: float = 0.02
    fin_planform: str = "trapezoid"
    boattail: bool = False


def default_cd_curve(inputs: AeroInputs) -> CdTable:
    base_cd = 0.12 + 0.02 * max(0.0, 12.0 - inputs.fineness_ratio)
    fin_cd = 0.08 + 0.5 * inputs.fin_thickness_ratio
    if inputs.fin_planform.lower() == "swept":
        fin_cd *= 0.9
    if inputs.nose_type.lower() in ("cone", "conical"):
        base_cd *= 1.08
    if inputs.boattail:
        base_cd *= 0.92

    mach = [0.0, 0.3, 0.6, 0.8, 0.95, 1.05, 1.2, 1.5, 2.0, 3.0]
    transonic_bump = [1.0, 1.0, 1.05, 1.2, 1.6, 1.55, 1.3, 1.15, 1.05, 1.0]
    cd = [(base_cd + fin_cd) * b for b in transonic_bump]
    return CdTable(mach=mach, cd=cd, source="heuristic")


def compare_cd_models(
    constant_cd: float,
    table: CdTable,
    mach_samples: list[float] | None = None,
) -> dict[str, float]:
    if mach_samples is None:
        mach_samples = [0.3, 0.6, 0.9, 1.0, 1.2, 1.6, 2.0]
    diffs = [abs(constant_cd - table.at(m)) for m in mach_samples]
    return {
        "mean_abs_error": sum(diffs) / max(len(diffs), 1),
        "max_abs_error": max(diffs) if diffs else 0.0,
    }
