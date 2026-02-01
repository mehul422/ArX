from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DesignRequest:
    target_apogee_ft: float
    rocket_file_path: str | None = None
    geometry: str = "BATES"
    propellant: str = "KNSB"
    constraints: dict[str, float] | None = None


def build_design_prompt(request: DesignRequest) -> str:
    constraint_lines = []
    if request.constraints:
        for key, value in request.constraints.items():
            constraint_lines.append(f"- {key}: {value}")
    constraints_text = "\n".join(constraint_lines) if constraint_lines else "- None"

    return (
        "You are designing a solid rocket motor using only the supported geometry and propellant.\n"
        f"Target apogee (ft): {request.target_apogee_ft}\n"
        f"Geometry: {request.geometry}\n"
        f"Propellant: {request.propellant}\n"
        f"Rocket file (optional): {request.rocket_file_path or 'not provided'}\n"
        "Constraints:\n"
        f"{constraints_text}\n"
        "\n"
        "Return a structured motor design with grain stack, nozzle, and propellant parameters.\n"
        "Do NOT invent new geometry types. Use only BATES + KNSB.\n"
    )
