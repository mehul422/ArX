from __future__ import annotations

import glob
import math
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

import numpy as np

try:
    from sklearn.ensemble import RandomForestRegressor
except Exception:  # pragma: no cover - optional dependency
    RandomForestRegressor = None  # type: ignore[assignment]


def _local_name(tag: str) -> str:
    return tag.split("}", 1)[-1].lower()


def _as_float(text: str | None) -> float | None:
    if text is None:
        return None
    try:
        return float(text)
    except Exception:
        return None


class LibraryAnalyzer:
    def __init__(self, library_path: str):
        self.library_path = library_path
        self.samples: list[tuple[float, float, float]] = []
        self.model = (
            RandomForestRegressor(n_estimators=120, random_state=42)
            if RandomForestRegressor is not None
            else None
        )
        self.is_trained = False

    def _load_ork_root(self, file_path: str) -> ET.Element:
        if zipfile.is_zipfile(file_path):
            with zipfile.ZipFile(file_path, "r") as zf:
                ork_entry = next(
                    (name for name in zf.namelist() if name.lower().endswith((".ork", ".xml"))),
                    None,
                )
                if not ork_entry:
                    raise ValueError("ORK archive missing XML entry")
                xml_bytes = zf.read(ork_entry)
            return ET.fromstring(xml_bytes)
        return ET.parse(file_path).getroot()

    def _parse_ork_features(self, file_path: str) -> dict[str, float] | None:
        try:
            root = self._load_ork_root(file_path)
        except Exception:
            return None

        max_radius = 0.0
        total_length = 0.0
        max_fin_span = 0.0
        total_mass = 0.0

        for node in root.iter():
            tag = _local_name(node.tag)

            if tag in {"bodytube", "nosecone", "transition"}:
                length = _as_float(node.findtext("length"))
                if length is not None and length > 0:
                    total_length += length

                for rad_tag in ("radius", "outerradius", "aftradius"):
                    radius = _as_float(node.findtext(rad_tag))
                    if radius is not None and radius > 0:
                        max_radius = max(max_radius, radius)

                # Some ORK variants keep diameters explicitly.
                diameter = _as_float(node.findtext("diameter"))
                if diameter is not None and diameter > 0:
                    max_radius = max(max_radius, diameter / 2.0)

            if tag in {"trapezoidfinset", "ellipticalfinset", "freeformfinset"}:
                span = _as_float(node.findtext("height"))
                if span is None:
                    span = _as_float(node.findtext("span"))
                if span is not None and span > 0:
                    max_fin_span = max(max_fin_span, span)

            if tag == "masscomponent":
                mass = _as_float(node.findtext("mass"))
                if mass is None:
                    mass = _as_float(node.findtext("overridemass"))
                if mass is not None and mass > 0:
                    total_mass += mass

        diameter = max_radius * 2.0
        if diameter <= 0:
            return None

        # Keep a sane fallback if no reliable stack sum was found.
        length_estimate = total_length if total_length > 0 else diameter * 18.0
        fin_span_estimate = max_fin_span if max_fin_span > 0 else diameter * 2.2
        return {
            "diameter": float(diameter),
            "length_estimate": float(length_estimate),
            "fin_span_estimate": float(fin_span_estimate),
            "mass_estimate": float(total_mass),
        }

    def _estimate_apogee_potential(self, dims: dict[str, float]) -> float:
        diameter = max(dims["diameter"], 1e-6)
        length = max(dims["length_estimate"], diameter)
        fin_span = max(dims["fin_span_estimate"], diameter * 0.1)
        mass = max(dims.get("mass_estimate", 0.0), 0.0)

        fineness = length / diameter
        base_alt = 500.0 + (6000.0 / max(math.sqrt(diameter / 0.05), 0.5))
        slender_bonus = min(max(fineness, 6.0), 40.0) / 20.0
        fin_bonus = min(fin_span / diameter, 5.0) * 0.08
        mass_penalty = 1.0 / max(1.0 + (mass / 25.0), 0.35)
        return max(250.0, base_alt * (1.0 + slender_bonus + fin_bonus) * mass_penalty)

    def train(self) -> None:
        pattern = str(Path(self.library_path) / "**" / "*.ork")
        files = glob.glob(pattern, recursive=True)
        X: list[list[float]] = []
        y: list[list[float]] = []
        samples: list[tuple[float, float, float]] = []

        for file_path in files:
            dims = self._parse_ork_features(file_path)
            if not dims:
                continue
            apogee_label_m = self._estimate_apogee_potential(dims)
            X.append([apogee_label_m])
            y.append([dims["diameter"], dims["length_estimate"]])
            samples.append((apogee_label_m, dims["diameter"], dims["length_estimate"]))

        self.samples = samples
        if len(X) < 8:
            self.is_trained = False
            return
        if self.model is None:
            # Fallback model-less mode uses samples directly.
            self.is_trained = True
            return

        self.model.fit(np.array(X), np.array(y))
        self.is_trained = True

    def predict_geometry(self, target_apogee_m: float) -> tuple[float, float]:
        target = max(float(target_apogee_m), 200.0)

        if self.is_trained and self.model is not None:
            pred = self.model.predict(np.array([[target]]))[0]
            return float(max(pred[0], 0.03)), float(max(pred[1], 0.6))

        if self.is_trained and self.samples:
            # Nearest-neighbor blend in sample space as a robust fallback.
            ranked = sorted(self.samples, key=lambda item: abs(item[0] - target))[:5]
            if ranked:
                dia = float(sum(item[1] for item in ranked) / len(ranked))
                length = float(sum(item[2] for item in ranked) / len(ranked))
                return max(dia, 0.03), max(length, 0.6)

        # Physics fallback (no useful training corpus)
        ratio = max(target / 1000.0, 0.3)
        diameter = 0.054 * math.sqrt(ratio)
        length = 1.2 * (ratio**0.6)
        return float(max(diameter, 0.03)), float(max(length, 0.6))
