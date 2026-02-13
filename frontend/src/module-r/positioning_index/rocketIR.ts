import { RocketPartData } from "./types";

const M_TO_IN = 39.37007874015748;

type RocketIRChild =
  | {
      type: "inner_tube";
      id: string;
      name: string;
      outer_diameter_m: number;
      inner_diameter_m?: number;
      length_m: number;
      position_from_bottom_m: number;
      is_motor_mount?: boolean;
    }
  | {
      type: "parachute";
      id: string;
      name: string;
      library_id: string;
      diameter_m?: number;
      position_from_bottom_m: number;
    }
  | {
      type: "telemetry";
      id: string;
      name: string;
      mass_kg: number;
      position_from_bottom_m: number;
    }
  | {
      type: "ballast";
      id: string;
      name: string;
      mass_kg: number;
      position_from_bottom_m: number;
    };

type RocketIR = {
  name: string;
  design_mode: "MANUAL" | "AUTO";
  global_diameter_m: number;
  nose_cone: {
    id: string;
    name: string;
    type: "OGIVE" | "CONICAL" | "ELLIPTICAL" | "PARABOLIC";
    length_m: number;
    diameter_m: number;
    material?: string;
  };
  stages: Array<{
    id: string;
    name: string;
    length_m: number;
    diameter_m: number;
    motor_mount: {
      id: string;
      name: string;
      outer_diameter_m: number;
      inner_diameter_m?: number;
      length_m: number;
      position_from_bottom_m: number;
      is_motor_mount?: boolean;
    };
    bulkhead: {
      id: string;
      name: string;
      height_m: number;
      material?: string;
      position_from_top_m: number;
    };
  }>;
  body_tubes: Array<{
    id: string;
    name: string;
    length_m: number;
    diameter_m: number;
    wall_thickness_m?: number;
    children: RocketIRChild[];
  }>;
  fin_sets: Array<{
    id: string;
    name: string;
    parent_tube_id: string;
    fin_count: number;
    root_chord_m: number;
    tip_chord_m: number;
    span_m: number;
    sweep_m: number;
    thickness_m: number;
    position_from_bottom_m: number;
  }>;
  metadata?: Record<string, unknown>;
};

const safeNumber = (value: unknown, fallback = 0): number => {
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : fallback;
};

const metersToInches = (meters: number) => safeNumber(meters, 0) * M_TO_IN;

export type RocketIRImportResult = {
  parts: RocketPartData[];
  warnings: string[];
};

const validateRocketIR = (raw: unknown): { ir: RocketIR | null; warnings: string[] } => {
  const warnings: string[] = [];
  if (!raw || typeof raw !== "object") {
    return { ir: null, warnings: ["RocketIR payload is not an object."] };
  }
  const ir = raw as RocketIR;
  if (!ir.nose_cone || !Array.isArray(ir.stages) || !Array.isArray(ir.fin_sets)) {
    return { ir: null, warnings: ["RocketIR missing required sections (nose/stages/fins)."] };
  }
  if (safeNumber(ir.global_diameter_m) <= 0) {
    warnings.push("RocketIR global diameter is invalid; using fallback radius.");
  }
  return { ir, warnings };
};

export const rocketIRToParts = (raw: unknown): RocketIRImportResult => {
  const { ir, warnings } = validateRocketIR(raw);
  if (!ir) return { parts: [], warnings };

  const parts: RocketPartData[] = [];
  const fallbackRadiusIn = Math.max(metersToInches(safeNumber(ir.global_diameter_m)) / 2, 2);
  const stageMaterialById: Record<string, string> = {};

  ir.stages.forEach((stage, idx) => {
    const stageId = stage.id || `stage-${idx + 1}`;
    const stageLengthIn = Math.max(metersToInches(stage.length_m), 1);
    const stageRadiusIn = Math.max(metersToInches(stage.diameter_m) / 2, fallbackRadiusIn);
    const shellMaterial = stage.bulkhead?.material || "Aluminum";
    stageMaterialById[stageId] = shellMaterial;

    parts.push({
      id: stageId,
      type: "body",
      label: stage.name || `Stage ${idx + 1}`,
      params: {
        length: stageLengthIn,
        radius: stageRadiusIn,
        material: shellMaterial,
      },
    });

    if (stage.motor_mount) {
      const mount = stage.motor_mount;
      parts.push({
        id: mount.id || `${stageId}-mount`,
        type: "inner",
        label: mount.name || `${stage.name || stageId} Motor Mount`,
        params: {
          length: Math.max(metersToInches(mount.length_m), 1),
          radius: Math.max(metersToInches(mount.outer_diameter_m) / 2, 0.2),
          material: mount.is_motor_mount ? "Aluminum" : "Cardboard",
          thickness: Math.max(
            metersToInches(
              Math.max((mount.outer_diameter_m - safeNumber(mount.inner_diameter_m, 0)) / 2, 0)
            ),
            0.02
          ),
          parent: stageId,
        },
        internal: true,
      });
    }
  });

  if (ir.nose_cone) {
    parts.push({
      id: ir.nose_cone.id || "nose-1",
      type: "nose",
      label: ir.nose_cone.name || "Nose Cone",
      params: {
        length: Math.max(metersToInches(ir.nose_cone.length_m), 1),
        radius: Math.max(metersToInches(ir.nose_cone.diameter_m) / 2, fallbackRadiusIn),
        profile: ir.nose_cone.type || "OGIVE",
        material: ir.nose_cone.material || "Fiberglass",
      },
    });
  }

  ir.fin_sets.forEach((finSet, idx) => {
    const parentId = finSet.parent_tube_id || `stage-${idx + 1}`;
    parts.push({
      id: finSet.id || `fin-${idx + 1}`,
      type: "fin",
      label: finSet.name || `Fin Set ${idx + 1}`,
      params: {
        parent: parentId,
        fin_count: Math.max(1, safeNumber(finSet.fin_count, 3)),
        root: Math.max(metersToInches(finSet.root_chord_m), 0.5),
        tip: Math.max(metersToInches(finSet.tip_chord_m), 0.2),
        span: Math.max(metersToInches(finSet.span_m), 0.2),
        sweep: Math.max(metersToInches(finSet.sweep_m), 0),
        thickness: Math.max(metersToInches(finSet.thickness_m), 0.02),
        radius: fallbackRadiusIn,
        material: stageMaterialById[parentId] || "Aluminum",
      },
    });
  });

  ir.body_tubes.forEach((tube, tubeIdx) => {
    const tubeId = tube.id || `body-${tubeIdx + 1}`;
    parts.push({
      id: tubeId,
      type: "body",
      label: tube.name || `Body Tube ${tubeIdx + 1}`,
      params: {
        length: Math.max(metersToInches(tube.length_m), 1),
        radius: Math.max(metersToInches(tube.diameter_m) / 2, fallbackRadiusIn),
        material: "Aluminum",
        thickness: Math.max(metersToInches(safeNumber(tube.wall_thickness_m, 0.002)), 0.02),
      },
    });

    (tube.children || []).forEach((child, childIdx) => {
      const cid = child.id || `${tubeId}-child-${childIdx + 1}`;
      if (child.type === "inner_tube") {
        parts.push({
          id: cid,
          type: "inner",
          label: child.name || "Inner Tube",
          params: {
            length: Math.max(metersToInches(child.length_m), 0.4),
            radius: Math.max(metersToInches(child.outer_diameter_m) / 2, 0.2),
            material: child.is_motor_mount ? "Aluminum" : "Cardboard",
            thickness: Math.max(
              metersToInches(
                Math.max((child.outer_diameter_m - safeNumber(child.inner_diameter_m, 0)) / 2, 0)
              ),
              0.02
            ),
            parent: tubeId,
          },
          internal: true,
        });
        return;
      }

      if (child.type === "parachute") {
        parts.push({
          id: cid,
          type: "parachute",
          label: child.name || "Parachute",
          params: {
            length: Math.max(metersToInches(safeNumber(child.diameter_m, 0.2) * 0.3), 1),
            radius: Math.max(metersToInches(safeNumber(child.diameter_m, 0.2)) / 2, 0.2),
            material: "Nylon",
            parent: tubeId,
          },
          internal: true,
        });
        return;
      }

      if (child.type === "telemetry" || child.type === "ballast") {
        parts.push({
          id: cid,
          type: child.type === "telemetry" ? "telemetry" : "mass",
          label: child.name || (child.type === "telemetry" ? "Telemetry Module" : "Ballast"),
          params: {
            mass_kg: Math.max(safeNumber(child.mass_kg, 0), 0),
            length: Math.max(fallbackRadiusIn * 0.8, 1),
            radius: Math.max(fallbackRadiusIn * 0.35, 0.2),
            material: child.type === "telemetry" ? "Aluminum" : "Steel",
            parent: tubeId,
          },
          internal: true,
        });
      }
    });
  });

  if (parts.length === 0) {
    warnings.push("RocketIR import produced no parts.");
  }
  return { parts, warnings };
};
