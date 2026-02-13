from __future__ import annotations

from pathlib import Path

from app.engine.openmotor_ai.ballistics import TimeStep
from app.engine.openmotor_ai.eng_builder import build_eng
from app.engine.openmotor_ai.eng_export import export_eng
from app.engine.openmotor_ai.ric_writer import build_ric
from app.engine.openmotor_ai.spec import MotorSpec
from app.engine.openrocket_like_legacy.models import ArtifactRecord


def write_motor_artifacts(
    *,
    spec: MotorSpec,
    steps: list[TimeStep],
    out_dir: str,
    prefix: str,
    manufacturer: str = "openmotor-ai",
    propellant_label: str | None = None,
) -> list[ArtifactRecord]:
    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)
    eng = build_eng(spec, steps, designation=prefix, manufacturer=manufacturer)
    ric_path = output / f"{prefix}.ric"
    eng_path = output / f"{prefix}.eng"
    ric_path.write_text(build_ric(spec), encoding="utf-8")
    eng_text = export_eng(eng)
    if propellant_label:
        lines = eng_text.rstrip("\n").splitlines()
        insert_at = max(len(lines) - 2, 1)
        lines.insert(insert_at, f"; propellant: {propellant_label}")
        eng_text = "\n".join(lines) + "\n"
    eng_path.write_text(eng_text, encoding="utf-8")
    return [
        ArtifactRecord(kind="ric", path=str(ric_path), metadata={"propellant_label": propellant_label}),
        ArtifactRecord(kind="eng", path=str(eng_path), metadata={"propellant_label": propellant_label}),
    ]
