from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import yaml

from app.engine.openmotor_ai.eng_parser import load_eng
from app.engine.openmotor_ai.propellant_schema import (
    BurnRateLaw,
    CombustionProperties,
    PhysicalProperties,
    PropellantSchema,
    ValueWithUnits,
)
from app.engine.openmotor_ai.propellant_validation import normalize_units, validate_propellant
from app.engine.openmotor_ai.ric_parser import load_ric


def _from_dict(data: dict[str, Any]) -> PropellantSchema:
    return PropellantSchema.model_validate(data)


def _from_csv(path: str) -> PropellantSchema:
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        row = next(reader)
    name = row.get("name", "Imported")
    density = float(row.get("density", 0.0))
    a = float(row.get("a", 0.0))
    n = float(row.get("n", 0.0))
    gamma = float(row.get("gamma", 0.0)) if row.get("gamma") else None
    tc = float(row.get("combustion_temperature", 0.0)) if row.get("combustion_temperature") else None
    mw = float(row.get("molecular_weight", 0.0)) if row.get("molecular_weight") else None
    return PropellantSchema(
        name=name,
        family=row.get("family"),
        source="imported",
        physical_properties=PhysicalProperties(
            density=ValueWithUnits(value=density, units=row.get("density_units", "kg/m^3"))
        ),
        combustion_properties=CombustionProperties(
            burn_rate_law=BurnRateLaw(
                a=ValueWithUnits(value=a, units=row.get("a_units", "m/s/Pa^n")),
                n=ValueWithUnits(value=n, units="dimensionless"),
            ),
            gamma=ValueWithUnits(value=gamma, units="dimensionless") if gamma else None,
            combustion_temperature=ValueWithUnits(value=tc, units="K") if tc else None,
            molecular_weight=ValueWithUnits(value=mw, units="kg/kmol") if mw else None,
        ),
    )


def _from_ric(path: str) -> PropellantSchema:
    ric = load_ric(path)
    prop = ric.propellant or {}
    tabs = prop.get("tabs", [])
    tab = tabs[0] if tabs else {}
    return PropellantSchema(
        name=str(prop.get("name", "Imported")),
        family="Imported",
        source="imported",
        physical_properties=PhysicalProperties(
            density=ValueWithUnits(value=float(prop.get("density", 0.0)), units="kg/m^3")
        ),
        combustion_properties=CombustionProperties(
            burn_rate_law=BurnRateLaw(
                a=ValueWithUnits(value=float(tab.get("a", 0.0)), units="m/s/Pa^n"),
                n=ValueWithUnits(value=float(tab.get("n", 0.0)), units="dimensionless"),
            ),
            gamma=ValueWithUnits(value=float(tab.get("k", 0.0)), units="dimensionless"),
            combustion_temperature=ValueWithUnits(value=float(tab.get("t", 0.0)), units="K"),
            molecular_weight=ValueWithUnits(value=float(tab.get("m", 0.0)), units="kg/kmol"),
        ),
    )


def _from_eng(path: str) -> PropellantSchema:
    eng = load_eng(path)
    return PropellantSchema(
        name=eng.header.designation,
        family="Imported",
        source="imported",
        physical_properties=PhysicalProperties(
            density=ValueWithUnits(value=0.0, units="kg/m^3")
        ),
        combustion_properties=CombustionProperties(
            burn_rate_law=BurnRateLaw(
                a=ValueWithUnits(value=0.0, units="m/s/Pa^n"),
                n=ValueWithUnits(value=0.0, units="dimensionless"),
            )
        ),
        description="ENG contains thrust curve only; propellant properties not provided.",
    )


def detect_and_load(path: str) -> PropellantSchema:
    ext = Path(path).suffix.lower()
    if ext in (".json",):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return _from_dict(data)
    if ext in (".yaml", ".yml"):
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return _from_dict(data)
    if ext in (".csv",):
        return _from_csv(path)
    if ext in (".ric",):
        return _from_ric(path)
    if ext in (".eng",):
        return _from_eng(path)
    raise ValueError(f"Unsupported propellant format: {ext}")


def normalize_and_validate(
    prop: PropellantSchema,
    mode: str = "realistic",
) -> tuple[PropellantSchema, list[str], list[str]]:
    prop = normalize_units(prop)
    return validate_propellant(prop, mode=mode)
