from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import json

from app.engine.openmotor_ai.ric_parser import load_ric
from app.engine.openmotor_ai.spec import PropellantSpec, PropellantTab
from app.engine.openmotor_ai.propellant_schema import PropellantSchema
from app.engine.openmotor_ai.propellant_validation import normalize_units


@dataclass(frozen=True)
class PropellantEntry:
    name: str
    density_kg_m3: float
    tabs: list[PropellantTab]
    source_path: str


def _propellant_from_ric(path: str) -> PropellantEntry | None:
    ric = load_ric(path)
    prop = ric.propellant or {}
    name = str(prop.get("name", "")).strip()
    density = float(prop.get("density", 0.0))
    tabs = []
    for tab in prop.get("tabs", []) or []:
        tabs.append(
            PropellantTab(
                a=float(tab.get("a", 0.0)),
                n=float(tab.get("n", 0.0)),
                k=float(tab.get("k", 0.0)),
                m=float(tab.get("m", 0.0)),
                t=float(tab.get("t", 0.0)),
                min_pressure_pa=float(tab.get("minPressure", 0.0)),
                max_pressure_pa=float(tab.get("maxPressure", 0.0)),
            )
        )
    if not name or not tabs or density <= 0:
        return None
    return PropellantEntry(name=name, density_kg_m3=density, tabs=tabs, source_path=path)


def load_openmotor_propellants(openmotor_root: str) -> list[PropellantEntry]:
    root = Path(openmotor_root)
    if not root.exists():
        raise FileNotFoundError(f"OpenMotor root not found: {openmotor_root}")

    ric_paths = list(root.rglob("motor.ric")) + list(root.rglob("flight.ric"))
    seen = set()
    entries: list[PropellantEntry] = []
    for path in ric_paths:
        entry = _propellant_from_ric(str(path))
        if entry is None:
            continue
        key = (
            entry.name,
            round(entry.density_kg_m3, 6),
            tuple((round(tab.a, 12), round(tab.n, 6), round(tab.k, 6), round(tab.m, 6), round(tab.t, 3)) for tab in entry.tabs),
        )
        if key in seen:
            continue
        seen.add(key)
        entries.append(entry)
    return entries


def select_propellant(entries: Iterable[PropellantEntry], name_contains: str) -> PropellantEntry | None:
    name_contains = name_contains.lower()
    for entry in entries:
        if name_contains in entry.name.lower():
            return entry
    return None


def load_preset_propellants(path: str) -> list[PropellantSchema]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    presets: list[PropellantSchema] = []
    for item in data:
        prop = PropellantSchema.model_validate(item)
        presets.append(normalize_units(prop))
    return presets
