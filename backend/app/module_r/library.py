from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from app.module_r.models import ComponentCategory, LibraryComponent, MaterialSpec


_DEFAULT_MATERIALS: list[MaterialSpec] = [
    MaterialSpec(name="Cardboard", density_kg_m3=700, elastic_modulus_pa=2.6e9),
    MaterialSpec(name="Blue Tube", density_kg_m3=780, elastic_modulus_pa=3.1e9),
    MaterialSpec(name="Fiberglass", density_kg_m3=1850, elastic_modulus_pa=22e9),
    MaterialSpec(name="Phenolic", density_kg_m3=1350, elastic_modulus_pa=9e9),
    MaterialSpec(name="Aluminum", density_kg_m3=2700, elastic_modulus_pa=69e9),
    MaterialSpec(name="Aluminum 6063-T6", density_kg_m3=2700, elastic_modulus_pa=68.9e9),
    MaterialSpec(name="Nylon", density_kg_m3=1150, elastic_modulus_pa=2.5e9),
    MaterialSpec(name="Steel", density_kg_m3=7850, elastic_modulus_pa=200e9),
]


_DEFAULT_PARTS: list[dict[str, Any]] = [
    {
        "id": "tube-estes-75",
        "vendor": "Estes",
        "name": "BT-75 Body Tube",
        "material": "Cardboard",
        "hollow": True,
        "outer_diameter_m": 0.066,
        "inner_diameter_m": 0.063,
        "length_m": 0.5,
        "shape": "cylinder",
    },
    {
        "id": "tube-blue-98",
        "vendor": "Public Missiles",
        "name": "Blue Tube 98",
        "material": "Blue Tube",
        "hollow": True,
        "outer_diameter_m": 0.101,
        "inner_diameter_m": 0.097,
        "length_m": 0.7,
        "shape": "cylinder",
    },
    {
        "id": "tube-perf-6in",
        "vendor": "Public Missiles",
        "name": "Phenolic 6in Airframe Tube",
        "material": "Phenolic",
        "hollow": True,
        "outer_diameter_m": 0.170,
        "inner_diameter_m": 0.164,
        "length_m": 0.9,
        "shape": "cylinder",
    },
    {
        "id": "tube-blue-6in",
        "vendor": "Blue Tube",
        "name": "Blue Tube 6in",
        "material": "Blue Tube",
        "hollow": True,
        "outer_diameter_m": 0.168,
        "inner_diameter_m": 0.162,
        "length_m": 0.8,
        "shape": "cylinder",
    },
    {
        "id": "tube-blue-75",
        "vendor": "Public Missiles",
        "name": "Blue Tube 75",
        "material": "Blue Tube",
        "hollow": True,
        "outer_diameter_m": 0.078,
        "inner_diameter_m": 0.074,
        "length_m": 0.6,
        "shape": "cylinder",
    },
    {
        "id": "nose-ogive-75",
        "vendor": "Public Missiles",
        "name": "Ogive Nose 75",
        "material": "Fiberglass",
        "hollow": False,
        "outer_diameter_m": 0.078,
        "length_m": 0.2,
        "shape": "ogive",
    },
    {
        "id": "nose-ogive-98",
        "vendor": "Public Missiles",
        "name": "Ogive Nose 98",
        "material": "Fiberglass",
        "hollow": False,
        "outer_diameter_m": 0.101,
        "length_m": 0.26,
        "shape": "ogive",
    },
    {
        "id": "nose-ogive-6in",
        "vendor": "Public Missiles",
        "name": "Ogive Nose 6in",
        "material": "Fiberglass",
        "hollow": False,
        "outer_diameter_m": 0.168,
        "length_m": 0.28,
        "shape": "ogive",
    },
    {
        "id": "av-bay-38",
        "vendor": "Generic",
        "name": "Electronics Bay 38",
        "material": "Fiberglass",
        "hollow": True,
        "outer_diameter_m": 0.038,
        "inner_diameter_m": 0.034,
        "length_m": 0.18,
        "shape": "cylinder",
        "labels": "electronics,avionics",
    },
    {
        "id": "fin-g10-std",
        "vendor": "Generic",
        "name": "G10 Fin Set",
        "material": "Fiberglass",
        "hollow": False,
        "shape": "fin",
        "span_m": 0.12,
        "root_chord_m": 0.14,
        "tip_chord_m": 0.08,
        "sweep_m": 0.02,
        "metadata": {"fin_count": 4},
    },
    {
        "id": "ballast-steel",
        "vendor": "Generic",
        "name": "Steel Ballast Slug",
        "material": "Steel",
        "hollow": False,
        "shape": "slug",
        "mass_kg": 0.25,
    },
]


class ComponentLibrary:
    def __init__(self, parts: list[LibraryComponent], materials: dict[str, MaterialSpec]):
        self.parts = parts
        self.materials = materials

    @classmethod
    def load(
        cls,
        *,
        parts_json: str | None = None,
        parts_csv: str | None = None,
        materials_json: str | None = None,
        motor_diameter_m: float | None = None,
    ) -> "ComponentLibrary":
        raw_parts: list[dict[str, Any]] = []
        if parts_json and Path(parts_json).exists():
            raw_parts.extend(json.loads(Path(parts_json).read_text(encoding="utf-8")))
        if parts_csv and Path(parts_csv).exists():
            with Path(parts_csv).open("r", encoding="utf-8") as fh:
                raw_parts.extend(list(csv.DictReader(fh)))
        if not raw_parts:
            raw_parts = list(_DEFAULT_PARTS)

        if materials_json and Path(materials_json).exists():
            raw_materials = json.loads(Path(materials_json).read_text(encoding="utf-8"))
            materials = {
                item["name"]: MaterialSpec(
                    name=item["name"],
                    density_kg_m3=float(item["density_kg_m3"]),
                    elastic_modulus_pa=float(item["elastic_modulus_pa"])
                    if item.get("elastic_modulus_pa")
                    else None,
                )
                for item in raw_materials
            }
        else:
            materials = {mat.name: mat for mat in _DEFAULT_MATERIALS}

        parts: list[LibraryComponent] = []
        for idx, raw in enumerate(raw_parts):
            category = classify_component(raw, motor_diameter_m=motor_diameter_m)
            parts.append(
                LibraryComponent(
                    id=str(raw.get("id") or f"part-{idx + 1}"),
                    vendor=str(raw.get("vendor") or "generic"),
                    name=str(raw.get("name") or f"Part {idx + 1}"),
                    category=category,
                    shape=str(raw.get("shape")) if raw.get("shape") else None,
                    material=str(raw.get("material") or "Cardboard"),
                    hollow=bool(raw.get("hollow", False)),
                    outer_diameter_m=_to_float(raw.get("outer_diameter_m")),
                    inner_diameter_m=_to_float(raw.get("inner_diameter_m")),
                    length_m=_to_float(raw.get("length_m")),
                    wall_thickness_m=_to_float(raw.get("wall_thickness_m")),
                    mass_kg=_to_float(raw.get("mass_kg")),
                    span_m=_to_float(raw.get("span_m")),
                    root_chord_m=_to_float(raw.get("root_chord_m")),
                    tip_chord_m=_to_float(raw.get("tip_chord_m")),
                    sweep_m=_to_float(raw.get("sweep_m")),
                    metadata={
                        **(
                            raw.get("metadata")
                            if isinstance(raw.get("metadata"), dict)
                            else {}
                        ),
                        **{
                            k: v
                            for k, v in raw.items()
                            if k
                            not in {
                                "id",
                                "vendor",
                                "name",
                                "shape",
                                "material",
                                "hollow",
                                "outer_diameter_m",
                                "inner_diameter_m",
                                "length_m",
                                "wall_thickness_m",
                                "mass_kg",
                                "span_m",
                                "root_chord_m",
                                "tip_chord_m",
                                "sweep_m",
                                "metadata",
                            }
                        },
                    },
                )
            )
        return cls(parts=parts, materials=materials)

    def parts_by_category(self, category: ComponentCategory) -> list[LibraryComponent]:
        return [part for part in self.parts if part.category == category]

    def material(self, name: str) -> MaterialSpec:
        return (
            self.materials.get(name)
            or self.materials.get("Aluminum 6063-T6")
            or self.materials["Cardboard"]
        )


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def classify_component(part_data: dict[str, Any], *, motor_diameter_m: float | None) -> ComponentCategory:
    name = str(part_data.get("name", "")).lower()
    shape = str(part_data.get("shape", "")).lower()
    labels = str(part_data.get("labels", "")).lower()
    material = str(part_data.get("material", "")).lower()

    hollow = bool(part_data.get("hollow", False))
    outer = _to_float(part_data.get("outer_diameter_m")) or _to_float(part_data.get("diameter_m"))
    inner = _to_float(part_data.get("inner_diameter_m"))
    density_hint = _to_float(part_data.get("density_kg_m3"))
    mass = _to_float(part_data.get("mass_kg"))

    if "electronic" in name or "electronics" in labels or "avionics" in labels:
        return "telemetry_module"
    if shape in {"ogive", "conical", "elliptical", "parabolic"} or "nose" in name:
        return "nose_cone"
    if shape in {"fin", "trapezoid_fin"} or "fin" in name:
        return "fin_set"
    if not hollow and (
        (density_hint is not None and density_hint >= 3000)
        or "steel" in material
        or "lead" in material
        or "ballast" in name
    ):
        return "ballast"

    if hollow and outer is not None and motor_diameter_m is not None:
        if abs(outer - motor_diameter_m) <= 0.004:
            return "motor_mount"
        if outer > motor_diameter_m + 0.004:
            if "inner" in name or "av-bay" in name or "electronics" in labels:
                return "inner_tube"
            return "body_tube"

    if hollow and outer is not None:
        return "body_tube"
    if mass and mass > 0.01:
        return "ballast"
    return "unknown"
