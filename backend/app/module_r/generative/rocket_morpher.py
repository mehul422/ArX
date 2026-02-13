from __future__ import annotations


class RocketMorpher:
    def apply_morph(
        self,
        *,
        target_diameter_m: float,
        target_length_m: float,
        upper_length_limit_m: float,
        upper_mass_limit_kg: float,
        min_required_length_m: float,
        min_required_diameter_m: float,
    ) -> dict[str, float]:
        # Enforce hard constraints while preserving the model's suggestion shape.
        clamped_length = min(max(target_length_m, min_required_length_m), upper_length_limit_m)
        clamped_diameter = max(target_diameter_m, min_required_diameter_m)

        # If mass budget is very tight, bias toward thinner/slightly shorter geometry.
        # This is a heuristic correction, not a full mass solve.
        if upper_mass_limit_kg < 8.0:
            clamped_diameter *= 0.95
            clamped_length *= 0.95
            clamped_diameter = max(clamped_diameter, min_required_diameter_m)
            clamped_length = max(clamped_length, min_required_length_m)

        return {
            "target_diameter_m": float(clamped_diameter),
            "target_length_m": float(clamped_length),
            "length_scale": float(clamped_length / max(target_length_m, 1e-6)),
            "diameter_scale": float(clamped_diameter / max(target_diameter_m, 1e-6)),
        }
