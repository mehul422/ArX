from __future__ import annotations

from datetime import datetime
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.module_r.generator import PhysicsEngine, RICParser, SmartRocketGenerator
from app.module_r.openrocket_exporter import export_openrocket_ork
from app.module_r.schemas import (
    AutoBuildRequest,
    BallastMass,
    BodyTube,
    Bulkhead,
    FinSet,
    InnerTube,
    ModuleRAutoBuildResponse,
    NoseCone,
    ParachuteRef,
    RocketAssembly,
    Stage,
    TelemetryMass,
)


router = APIRouter(prefix="/module-r", tags=["module-r"])


class OrkExportResponse(BaseModel):
    ork_path: str
    warnings: list[str] = Field(default_factory=list)


@router.get("/health")
def module_r_health():
    return {"status": "ok"}


def _constraints_dict(
    *, upper_length_m: float, upper_mass_kg: float, target_apogee_m: float | None
) -> dict[str, float]:
    return {
        "upper_length": float(upper_length_m),
        "upper_mass": float(upper_mass_kg),
        "target_apogee": float(target_apogee_m or 1000.0),
    }


def _build_parametric_assembly(
    *,
    ric_path: str,
    constraints: dict[str, float],
    include_ballast: bool,
    include_telemetry: bool,
    include_parachute: bool,
) -> RocketAssembly:
    motor = RICParser.parse(ric_path)
    dims = PhysicsEngine.calculate_dimensions(
        motor,
        constraints.get("upper_length", 3.0),
        constraints.get("upper_mass", 10.0),
        constraints.get("target_apogee", 1000.0),
    )

    body_children: list[InnerTube | ParachuteRef | TelemetryMass | BallastMass] = []
    if include_telemetry:
        body_children.append(
            TelemetryMass(
                id="telemetry-1",
                name="Telemetry Module",
                mass_kg=0.35,
                position_from_bottom_m=max(dims.body_length * 0.65, 0.05),
            )
        )
    if include_ballast:
        body_children.append(
            BallastMass(
                id="ballast-1",
                name="Ballast",
                mass_kg=max(0.08, motor.propellant_mass * 0.15),
                position_from_bottom_m=max(dims.body_length * 0.2, 0.03),
            )
        )
    if include_parachute:
        body_children.append(
            ParachuteRef(
                id="parachute-1",
                name="Recovery Parachute",
                library_id="smart-parametric",
                diameter_m=dims.parachute_dia,
                position_from_bottom_m=max(dims.body_length * 0.8, 0.05),
            )
        )

    assembly = RocketAssembly(
        name=f"Smart Parametric {motor.name}",
        design_mode="AUTO",
        global_diameter_m=dims.body_od,
        nose_cone=NoseCone(
            id="nose-1",
            name="Ogive Nose Cone",
            type="OGIVE",
            length_m=dims.nose_length,
            diameter_m=dims.body_od,
            material="Fiberglass",
        ),
        stages=[
            Stage(
                id="stage-1",
                name="Stage 1",
                length_m=max(dims.body_length * 0.9, dims.motor_mount_length + 0.05),
                diameter_m=dims.body_od,
                motor_mount=InnerTube(
                    id="stage-1-mount",
                    name="Motor Mount",
                    outer_diameter_m=dims.motor_mount_od,
                    inner_diameter_m=dims.motor_mount_id,
                    length_m=dims.motor_mount_length,
                    position_from_bottom_m=0.01,
                    is_motor_mount=True,
                ),
                bulkhead=Bulkhead(
                    id="stage-1-bulkhead",
                    name="Forward Bulkhead",
                    height_m=0.005,
                    material="Plywood",
                    position_from_top_m=0.0,
                ),
            )
        ],
        body_tubes=[
            BodyTube(
                id="body-1",
                name="Main Body Tube",
                length_m=dims.body_length,
                diameter_m=dims.body_od,
                wall_thickness_m=max((dims.body_od - dims.body_id) / 2.0, 0.0015),
                children=body_children,
            )
        ],
        fin_sets=[
            FinSet(
                id="fins-1",
                name="Primary Fin Set",
                parent_tube_id="body-1",
                fin_count=3,
                root_chord_m=dims.fin_root,
                tip_chord_m=dims.fin_tip,
                span_m=dims.fin_span,
                sweep_m=dims.fin_sweep,
                thickness_m=0.003,
                position_from_bottom_m=0.0,
            )
        ],
        metadata={
            "backend_variant": "smart_parametric",
            "generator": "SmartRocketGenerator",
            "motor_name": motor.name,
            "motor_diameter_m": motor.diameter,
            "motor_length_m": motor.length,
            "target_apogee_m": constraints.get("target_apogee"),
        },
    )
    return assembly


def _run_parametric_build(
    *,
    ric_path: str,
    upper_length_m: float,
    upper_mass_kg: float,
    target_apogee_m: float | None,
    include_ballast: bool,
    include_telemetry: bool,
    include_parachute: bool,
) -> ModuleRAutoBuildResponse:
    output_root = Path(__file__).resolve().parents[3] / "tests" / "module_r"
    output_root.mkdir(parents=True, exist_ok=True)

    constraints = _constraints_dict(
        upper_length_m=upper_length_m,
        upper_mass_kg=upper_mass_kg,
        target_apogee_m=target_apogee_m,
    )

    output_path = output_root / f"module_r_parametric_{uuid.uuid4().hex}.ork"
    generator = SmartRocketGenerator(ric_path, constraints)
    ork_path = generator.generate(str(output_path))

    assembly = _build_parametric_assembly(
        ric_path=ric_path,
        constraints=constraints,
        include_ballast=include_ballast,
        include_telemetry=include_telemetry,
        include_parachute=include_parachute,
    )
    assembly.metadata["legacy_only_mode"] = False
    return ModuleRAutoBuildResponse(
        assembly=assembly,
        ork_path=ork_path,
        created_at=datetime.utcnow(),
    )


@router.post("/auto-build", response_model=ModuleRAutoBuildResponse)
def module_r_auto_build(request: AutoBuildRequest):
    ric_paths = [
        path
        for path in (request.ric_paths or ([request.ric_path] if request.ric_path else []))
        if path
    ]
    if not ric_paths:
        raise HTTPException(status_code=400, detail="uploaded file is empty")
    try:
        return _run_parametric_build(
            ric_path=ric_paths[0],
            upper_length_m=request.constraints.upper_length_m,
            upper_mass_kg=request.constraints.upper_mass_kg,
            target_apogee_m=request.constraints.target_apogee_m,
            include_ballast=request.include_ballast,
            include_telemetry=request.include_telemetry,
            include_parachute=request.include_parachute,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"smart parametric build failed: {exc}") from exc


@router.post("/auto-build/upload", response_model=ModuleRAutoBuildResponse)
def module_r_auto_build_upload(
    ric_file: list[UploadFile] = File(...),
    upper_length_m: float = Form(...),
    upper_mass_kg: float = Form(...),
    target_apogee_m: float | None = Form(default=None),
    include_ballast: bool = Form(default=False),
    include_telemetry: bool = Form(default=True),
    include_parachute: bool = Form(default=True),
    top_n: int = Form(default=5),
    random_seed: int | None = Form(default=None),
    stage_count: int | None = Form(default=None),
):
    _ = top_n
    _ = random_seed
    _ = stage_count
    if not ric_file:
        raise HTTPException(status_code=400, detail="uploaded file is empty")
    output_root = Path(__file__).resolve().parents[3] / "tests" / "module_r"
    output_root.mkdir(parents=True, exist_ok=True)
    ric_paths: list[str] = []
    for upload in ric_file:
        content = upload.file.read()
        if not content:
            continue
        suffix = Path(upload.filename or "").suffix.lower()
        file_suffix = suffix if suffix == ".ric" else ".ric"
        ric_path = output_root / f"smart_upload_{uuid.uuid4().hex}{file_suffix}"
        ric_path.write_bytes(content)
        ric_paths.append(str(ric_path))
    if not ric_paths:
        raise HTTPException(status_code=400, detail="uploaded file is empty")
    try:
        return _run_parametric_build(
            ric_path=ric_paths[0],
            upper_length_m=upper_length_m,
            upper_mass_kg=upper_mass_kg,
            target_apogee_m=target_apogee_m,
            include_ballast=include_ballast,
            include_telemetry=include_telemetry,
            include_parachute=include_parachute,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"smart parametric build failed: {exc}") from exc


@router.post("/auto-build/upload-legacy", response_model=ModuleRAutoBuildResponse)
def module_r_auto_build_upload_legacy(
    ric_file: list[UploadFile] = File(...),
    upper_length_m: float = Form(...),
    upper_mass_kg: float = Form(...),
    target_apogee_m: float | None = Form(default=None),
    include_ballast: bool = Form(default=False),
    include_telemetry: bool = Form(default=True),
    include_parachute: bool = Form(default=True),
    top_n: int = Form(default=5),
    random_seed: int | None = Form(default=None),
    stage_count: int | None = Form(default=None),
):
    return module_r_auto_build_upload(
        ric_file=ric_file,
        upper_length_m=upper_length_m,
        upper_mass_kg=upper_mass_kg,
        target_apogee_m=target_apogee_m,
        include_ballast=include_ballast,
        include_telemetry=include_telemetry,
        include_parachute=include_parachute,
        top_n=top_n,
        random_seed=random_seed,
        stage_count=stage_count,
    )


@router.post("/ork", response_model=OrkExportResponse)
def module_r_export_ork(assembly: RocketAssembly):
    output_root = Path(__file__).resolve().parents[3] / "tests" / "module_r"
    output_path = output_root / f"module_r_manual_{uuid.uuid4().hex}.ork"
    warnings: list[str] = []
    # Enforce fin realism guidance server-side: fin span should be ~3x body diameter.
    recommended_span_m = assembly.global_diameter_m * 3.0
    tolerance = max(0.02, recommended_span_m * 0.08)
    for fin in assembly.fin_sets:
        if abs(fin.span_m - recommended_span_m) > tolerance:
            warnings.append(
                f"{fin.name}: fin span {fin.span_m:.3f} m deviates from 1:3 target "
                f"({recommended_span_m:.3f} m)."
            )
    try:
        export_openrocket_ork(assembly, str(output_path))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return OrkExportResponse(ork_path=str(output_path), warnings=warnings)
