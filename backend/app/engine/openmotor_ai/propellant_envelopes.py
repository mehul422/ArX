from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Envelope:
    density_min: float
    density_max: float
    a_min: float
    a_max: float
    n_min: float
    n_max: float
    gamma_min: float
    gamma_max: float
    tc_min: float
    tc_max: float
    c_star_min: float
    c_star_max: float


_SUGAR = Envelope(
    density_min=1600,
    density_max=1900,
    a_min=2.0e-5,
    a_max=6.0e-5,
    n_min=0.25,
    n_max=0.45,
    gamma_min=1.15,
    gamma_max=1.25,
    tc_min=1500,
    tc_max=1900,
    c_star_min=800,
    c_star_max=1100,
)

_COMPOSITE = Envelope(
    density_min=1600,
    density_max=1900,
    a_min=3.0e-5,
    a_max=8.0e-5,
    n_min=0.25,
    n_max=0.45,
    gamma_min=1.18,
    gamma_max=1.25,
    tc_min=2500,
    tc_max=3600,
    c_star_min=1200,
    c_star_max=1700,
)

_ALT_NITRATE = Envelope(
    density_min=1550,
    density_max=1800,
    a_min=2.0e-5,
    a_max=5.0e-5,
    n_min=0.25,
    n_max=0.40,
    gamma_min=1.15,
    gamma_max=1.22,
    tc_min=2000,
    tc_max=2800,
    c_star_min=1000,
    c_star_max=1400,
)

_BLACK_POWDER = Envelope(
    density_min=1500,
    density_max=1900,
    a_min=8.0e-5,
    a_max=2.0e-4,
    n_min=0.10,
    n_max=0.30,
    gamma_min=1.10,
    gamma_max=1.20,
    tc_min=1200,
    tc_max=1800,
    c_star_min=600,
    c_star_max=900,
)

_DOUBLE_BASE = Envelope(
    density_min=1500,
    density_max=1700,
    a_min=5.0e-5,
    a_max=2.0e-4,
    n_min=0.10,
    n_max=0.35,
    gamma_min=1.15,
    gamma_max=1.25,
    tc_min=2000,
    tc_max=3200,
    c_star_min=900,
    c_star_max=1300,
)

_HYBRID_FUEL = Envelope(
    density_min=800,
    density_max=1100,
    a_min=5.0e-6,
    a_max=3.0e-5,
    n_min=0.40,
    n_max=0.80,
    gamma_min=1.15,
    gamma_max=1.25,
    tc_min=2600,
    tc_max=3400,
    c_star_min=1200,
    c_star_max=1700,
)


def envelope_for(name: str | None, family: str | None) -> Envelope | None:
    name_l = (name or "").strip().lower()
    family_l = (family or "").strip().lower()

    if "sugar" in family_l or name_l in {"knsb", "knsu", "kndx", "kner"}:
        return _SUGAR
    if "composite" in family_l:
        return _COMPOSITE
    if name_l in {"apcp", "ap/htpb", "ap/al/htpb"}:
        return _COMPOSITE
    if name_l in {"white lightning", "blue thunder", "black jack", "redline", "green gorilla", "warp 9", "skidmark"}:
        return _COMPOSITE
    if name_l in {"double-base", "smokeless powder"}:
        return _DOUBLE_BASE
    if name_l in {"ansb", "ansu", "ancp"} or "nitrate" in family_l:
        return _ALT_NITRATE
    if "black powder" in name_l:
        return _BLACK_POWDER
    if "hybrid" in family_l or name_l in {"htpb (hybrid fuel grain)", "paraffin wax", "polyethylene"}:
        return _HYBRID_FUEL
    return None
