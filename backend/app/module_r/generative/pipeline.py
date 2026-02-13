from __future__ import annotations

from pathlib import Path
from typing import Any

from app.module_r.generative.library_analyzer import LibraryAnalyzer
from app.module_r.generative.rocket_morpher import RocketMorpher


def suggest_geometry(
    *,
    target_apogee_m: float | None,
    upper_length_limit_m: float,
    upper_mass_limit_kg: float,
    min_required_length_m: float,
    min_required_diameter_m: float,
    library_path: str | None = None,
) -> dict[str, Any]:
    library_root = (
        Path(library_path)
        if library_path
        else (Path(__file__).resolve().parents[3] / "resources" / "orks" / "uploads")
    )
    analyzer = LibraryAnalyzer(str(library_root))
    analyzer.train()

    target = float(target_apogee_m or 3000.0)
    ideal_diameter, ideal_length = analyzer.predict_geometry(target)

    morpher = RocketMorpher()
    morph = morpher.apply_morph(
        target_diameter_m=ideal_diameter,
        target_length_m=ideal_length,
        upper_length_limit_m=upper_length_limit_m,
        upper_mass_limit_kg=upper_mass_limit_kg,
        min_required_length_m=min_required_length_m,
        min_required_diameter_m=min_required_diameter_m,
    )
    return {
        **morph,
        "ideal_diameter_m": float(ideal_diameter),
        "ideal_length_m": float(ideal_length),
        "target_apogee_m": target,
        "library_path": str(library_root),
        "library_sample_count": len(analyzer.samples),
        "model_trained": bool(analyzer.is_trained),
    }
