import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DndContext, DragEndEvent, useDraggable, useDroppable } from "@dnd-kit/core";
import { MATERIAL_DB, resolveCustomMaterialVisual } from "./materials";
import { AssemblyPart, RocketPartData } from "./types";
import { Workspace } from "./Workspace";
import { usePositioningStore } from "./usePositioningStore";
import { rocketIRToParts } from "./rocketIR";

const INCH_TO_M = 0.0254;
const LB_TO_KG = 0.45359237;

const clamp = (value: number, min: number, max: number) =>
  Math.max(min, Math.min(max, value));

const COMPONENT_SNAP_X_TOL = 2;
const COMPONENT_SNAP_Y_TOL = 1;
const COMPONENT_SNAP_Z_TOL = 2;

const getPartLength = (part: { params: Record<string, number | string | boolean | undefined> }) =>
  Number(part.params.length ?? 0);

const nearestLinearSnapOnDrop = (
  part: RocketPartData,
  existing: AssemblyPart[],
  current: [number, number, number]
) => {
  if (part.type === "fin") return null;
  const selfLength = getPartLength(part);
  const candidates: Array<{ x: number; y: number; z: number; score: number }> = [];

  existing.forEach((other) => {
    const otherLength = getPartLength(other);
    const otherFront = other.position[0];
    const otherAft = other.position[0] + otherLength;

    if (part.type === "nose") {
      if (other.type === "body" || other.type === "inner") {
        const x = otherFront - selfLength;
        const y = other.position[1];
        const z = other.position[2];
        const dx = current[0] - x;
        const dy = current[1] - y;
        const dz = current[2] - z;
        candidates.push({ x, y, z, score: dx * dx + dy * dy + dz * dz });
      }
      return;
    }

    if (part.type === "body" || part.type === "inner") {
      if (other.type === "body" || other.type === "inner" || other.type === "nose") {
        const x = otherAft;
        const y = other.position[1];
        const z = other.position[2];
        const dx = current[0] - x;
        const dy = current[1] - y;
        const dz = current[2] - z;
        candidates.push({ x, y, z, score: dx * dx + dy * dy + dz * dz });
      }
    }
  });

  let best: { x: number; y: number; z: number; score: number } | null = null;
  candidates.forEach((candidate) => {
    const dx = Math.abs(current[0] - candidate.x);
    const dy = Math.abs(current[1] - candidate.y);
    const dz = Math.abs(current[2] - candidate.z);
    if (dx > COMPONENT_SNAP_X_TOL || dy > COMPONENT_SNAP_Y_TOL || dz > COMPONENT_SNAP_Z_TOL) {
      return;
    }
    if (!best || candidate.score < best.score) best = candidate;
  });
  return best;
};

const computePartMassKg = (part: RocketPartData) => {
  const isOverrideActive = Boolean(
    part.params.isOverrideActive ?? part.params.is_override_active
  );
  const overrideMassLb = Number(part.params.manualOverrideMass ?? part.params.manual_override_mass);
  if (isOverrideActive && Number.isFinite(overrideMassLb) && overrideMassLb >= 0) {
    return overrideMassLb * LB_TO_KG;
  }
  const materialName = String(part.params.material ?? "");
  const materialEntry =
    (materialName && MATERIAL_DB[materialName as keyof typeof MATERIAL_DB]) ||
    resolveCustomMaterialVisual(materialName);
  const density = materialEntry.density_kg_m3 ?? 0;

  const radiusM = Number(part.params.radius ?? 0) * INCH_TO_M;
  const lengthM = Number(part.params.length ?? 0) * INCH_TO_M;
  const thicknessM = Number(part.params.thickness ?? 0) * INCH_TO_M;

  if (part.type === "body" || part.type === "inner") {
    const outerR = radiusM;
    const wall = thicknessM > 0 ? thicknessM : 0.002;
    const innerR = Math.max(outerR - wall, 0);
    const volume = Math.PI * (outerR * outerR - innerR * innerR) * lengthM;
    return volume * density;
  }

  if (part.type === "nose") {
    const volume = (Math.PI * radiusM * radiusM * lengthM) / 3;
    return volume * density;
  }

  if (part.type === "fin") {
    const finType = String(part.params.fin_type ?? "trapezoidal").toLowerCase();
    const count = Math.max(1, Number(part.params.fin_count ?? part.params.count ?? 1));
    if (finType === "tube_fin") {
      const lengthM = Number(part.params.tube_length ?? part.params.root ?? 0) * INCH_TO_M;
      const outerR = (Number(part.params.tube_outer_diameter ?? part.params.span ?? 0) * INCH_TO_M) / 2;
      const innerR = (Number(part.params.tube_inner_diameter ?? 0) * INCH_TO_M) / 2;
      const ringVolume = Math.PI * Math.max(outerR * outerR - innerR * innerR, 0) * Math.max(lengthM, 0);
      return ringVolume * density * count;
    }
    const root = Number(part.params.root ?? 0) * INCH_TO_M;
    const tip = Number(part.params.tip ?? 0) * INCH_TO_M;
    const span = Number(part.params.span ?? 0) * INCH_TO_M;
    const thickness = Number(part.params.thickness ?? 0) * INCH_TO_M;
    const area = ((root + tip) / 2) * span;
    return area * thickness * density * count;
  }

  const massKg =
    Number(part.params.mass_kg ?? 0) ||
    Number(part.params.mass_lb ?? 0) * LB_TO_KG;
  return massKg;
};

const buildAvailableParts = (): RocketPartData[] => {
  const parts: RocketPartData[] = [];
  const globalWidth = Number(window.localStorage.getItem("arx_module_r_width") || "0");
  const radius = globalWidth > 0 ? globalWidth / 2 : 2;

  const stages = JSON.parse(
    window.localStorage.getItem("arx_module_r_motor_mounts") || "[]"
  ) as Array<{
    length_in?: number;
    inner_tube_diameter_in?: number;
    inner_tube_thickness_in?: number;
    bulkhead_material?: string;
  }>;
  const stageMaterialById: Record<string, string> = {};
  stages.forEach((stage, idx) => {
    const length = Number(stage.length_in ?? 24);
    const stageId = `stage-${idx + 1}`;
    stageMaterialById[stageId] = stage.bulkhead_material || "Cardboard";
    const bodyDiameter = Math.max(radius * 2, 0.1);
    const rawInnerDiameter = Number(stage.inner_tube_diameter_in ?? 0);
    const rawWallThickness = Number(stage.inner_tube_thickness_in ?? 0);
    const wallThickness = Number.isFinite(rawWallThickness) && rawWallThickness > 0 ? rawWallThickness : 0.06;
    // Treat stored value as tube inner diameter; convert to visible outer diameter.
    const normalizedInner = Number.isFinite(rawInnerDiameter) && rawInnerDiameter > 0
      ? rawInnerDiameter
      : Math.max(bodyDiameter * 0.32, 0.75);
    const normalizedOuter = Math.min(
      Math.max(normalizedInner + wallThickness * 2, 0.8),
      bodyDiameter * 0.82
    );
    parts.push({
      id: `body-${idx + 1}`,
      type: "body",
      label: `Stage ${idx + 1}`,
      params: {
        length,
        radius,
        material: stage.bulkhead_material || "Cardboard",
        logicalHitboxScale: 1.15,
      },
    });
    if (normalizedOuter > 0) {
      parts.push({
        id: `inner-${idx + 1}`,
        type: "inner",
        label: `Motor Mount Inner Tube ${idx + 1}`,
        params: {
          length,
          radius: normalizedOuter / 2,
          material: "Aluminum",
          thickness: wallThickness,
          parent: `body-${idx + 1}`,
          parentType: "Stage",
          logicalHitboxScale: 1.2,
        },
        internal: true,
      });
    }
  });

  const nose = JSON.parse(
    window.localStorage.getItem("arx_module_r_nose_cone") || "null"
  ) as { length_in?: number; profile?: string; material?: string } | null;
  if (nose) {
    parts.push({
      id: "nose-1",
      type: "nose",
      label: "Nose Cone",
      params: {
        length: Number(nose.length_in ?? 12),
        radius,
        profile: nose.profile || "OGIVE",
        material: nose.material || "Fiberglass",
        logicalHitboxScale: 1.15,
      },
    });
  }

  const fins = JSON.parse(
    window.localStorage.getItem("arx_module_r_fins") || "[]"
  ) as Array<{
    type?: string;
    root?: number;
    tip?: number;
    span?: number;
    sweep?: number;
    thickness?: number;
    count?: number;
    parent?: string;
    material?: string;
    finish?: string;
    cross_section?: string;
    position_relative?: string;
    plus_offset?: number;
    rotation_deg?: number;
    fillet_radius?: number;
    fillet_material?: string;
    free_points?: string;
    tube_length?: number;
    tube_outer_diameter?: number;
    tube_inner_diameter?: number;
    tube_auto_inner?: boolean;
  }>;
  fins.forEach((fin, idx) => {
    const parentId = fin.parent || `stage-${idx + 1}`;
    parts.push({
      id: `fin-${idx + 1}`,
      type: "fin",
      label: `Fin Set ${idx + 1}`,
      params: {
        fin_type: String(fin.type || "trapezoidal"),
        parent: parentId,
        fin_count: Number(fin.count ?? 3),
        root: Number(fin.root ?? 6),
        tip: Number(fin.tip ?? 3),
        span: Number(fin.span ?? 4),
        sweep: Number(fin.sweep ?? 0),
        thickness: Number(fin.thickness ?? 0.2),
        radius,
        material: fin.material || stageMaterialById[parentId] || "Cardboard",
        finish: fin.finish || "regular_paint",
        cross_section: fin.cross_section || "square",
        position_relative: fin.position_relative || "bottom",
        plus_offset: Number(fin.plus_offset ?? 0),
        rotation_deg: Number(fin.rotation_deg ?? 0),
        fillet_radius: Number(fin.fillet_radius ?? 0),
        fillet_material: fin.fillet_material || "Balsa",
        free_points: fin.free_points || "",
        tube_length: Number(fin.tube_length ?? fin.root ?? 4),
        tube_outer_diameter: Number(fin.tube_outer_diameter ?? fin.span ?? 2),
        tube_inner_diameter: Number(fin.tube_inner_diameter ?? 0),
        tube_auto_inner: Boolean(fin.tube_auto_inner),
        logicalHitboxScale: 1.2,
      },
    });
  });

  const additionalTubes = JSON.parse(
    window.localStorage.getItem("arx_module_r_additional_tubes") || "[]"
  ) as Array<{
    components?: Array<{
      name?: string;
      type?: string;
      mass?: number;
      mass_lb?: number;
      drag_coefficient?: number;
      material?: string;
      is_override_active?: boolean;
      manual_override_mass_lb?: number;
    }>;
  }>;
  const additionalTubeLengthIn = Math.max(12, radius * 6);
  additionalTubes.forEach((_, tubeIndex) => {
    parts.push({
      id: `additional-${tubeIndex + 1}`,
      type: "body",
      label: `Additional Tube ${tubeIndex + 1}`,
      params: {
        length: additionalTubeLengthIn,
        radius,
        material: "Cardboard",
        logicalHitboxScale: 1.15,
      },
    });
  });
  const resolveAdditionalMaterial = (kind?: string) => {
    switch (kind) {
      case "telemetry":
        return "Aluminum";
      case "mass":
        return "Steel";
      case "inner_tube":
        return "Aluminum";
      case "parachute":
        return "Nylon";
      default:
        return "Cardboard";
    }
  };
  additionalTubes.forEach((tube, tubeIndex) => {
    (tube.components || []).forEach((component, componentIndex) => {
      const massKg = Number(component.mass_lb ?? component.mass ?? 0) * LB_TO_KG;
      const partType = (() => {
        if (component.type === "inner_tube") return "inner";
        if (component.type === "mass") return "mass";
        if (component.type === "parachute") return "parachute";
        if (component.type === "telemetry") return "telemetry";
        return "inner";
      })();
      parts.push({
        id: `additional-${tubeIndex + 1}-${componentIndex + 1}`,
        type: partType as RocketPartData["type"],
        label: `Tube ${tubeIndex + 1}: ${component.name || component.type || "Component"}`,
        params: {
          length: Math.max(6, radius * 2.5),
          radius: Math.max(0.6, radius * 0.35),
          material: component.material || resolveAdditionalMaterial(component.type),
          mass_kg: massKg,
          parent: `additional-${tubeIndex + 1}`,
          parentType: "Additional Tube",
          drag_coefficient: Number(component.drag_coefficient ?? 0),
          isOverrideActive: Boolean(component.is_override_active),
          manualOverrideMass: Number(component.manual_override_mass_lb ?? 0),
          logicalHitboxScale: 1.35,
        },
        internal: true,
      });
    });
  });

  return parts;
};

const buildAvailablePartsFromCanonicalImport = (): RocketPartData[] => {
  const raw = window.localStorage.getItem("arx_module_r_latest_auto_assembly");
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw) as unknown;
    const result = rocketIRToParts(parsed);
    if (result.warnings.length > 0) {
      console.warn("RocketIR import warnings:", result.warnings);
    }
    return result.parts;
  } catch (error) {
    console.warn("Failed to parse arx_module_r_latest_auto_assembly", error);
    return [];
  }
};

const StorageItem: React.FC<{ part: RocketPartData }> = ({ part }) => {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: part.id,
  });

  const style: React.CSSProperties = {
    transform: transform
      ? `translate3d(${transform.x}px, ${transform.y}px, 0)`
      : undefined,
    opacity: isDragging ? 0.6 : 1,
  };

  return (
    <div
      ref={setNodeRef}
      className="module-r-storage-item"
      style={style}
      {...listeners}
      {...attributes}
    >
      <div className="module-r-storage-thumb">
        <div className={`module-r-storage-shape shape-${part.type}`} />
      </div>
      <div className="module-r-storage-label">{part.label}</div>
    </div>
  );
};

const WorkspaceDropZone: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { setNodeRef, isOver } = useDroppable({ id: "workspace" });
  return (
    <div
      ref={setNodeRef}
      className={`module-r-workspace-drop ${isOver ? "module-r-drop-active" : ""}`}
    >
      {children}
    </div>
  );
};

export const PositioningModule: React.FC = () => {
  const availableParts = usePositioningStore((state) => state.availableParts);
  const assembly = usePositioningStore((state) => state.assembly);
  const history = usePositioningStore((state) => state.history);
  const selectedId = usePositioningStore((state) => state.selectedId);
  const setAvailableParts = usePositioningStore((state) => state.setAvailableParts);
  const syncAssemblyFromCatalog = usePositioningStore((state) => state.syncAssemblyFromCatalog);
  const addToAssembly = usePositioningStore((state) => state.addToAssembly);
  const lastDropPosition = usePositioningStore((state) => state.lastDropPosition);
  const setLastDropPosition = usePositioningStore((state) => state.setLastDropPosition);
  const updatePartPosition = usePositioningStore((state) => state.updatePartPosition);
  const selectPart = usePositioningStore((state) => state.selectPart);
  const undoLast = usePositioningStore((state) => state.undoLast);
  const flipPart = usePositioningStore((state) => state.flipPart);
  const setFinPlaced = usePositioningStore((state) => state.setFinPlaced);

  const [cameraMode, setCameraMode] = useState<"orthographic" | "perspective">(
    "orthographic"
  );
  const [viewMode, setViewMode] = useState<"3d" | "2d">("3d");
  const [isFullscreen, setIsFullscreen] = useState(false);
  const workspacePanelRef = useRef<HTMLDivElement | null>(null);

  const showFinRecommendation = useMemo(() => {
    const hasNose = assembly.some((part) => part.type === "nose");
    const hasBody = assembly.some((part) => part.type === "body");
    const hasMotor = assembly.some((part) => part.type === "inner");
    const hasUnplacedFin = assembly.some((part) => part.type === "fin" && !part.finPlaced);
    return viewMode === "2d" && hasNose && hasBody && hasMotor && hasUnplacedFin;
  }, [assembly, viewMode]);
  const finRecommendationText = useMemo(() => {
    const selectedFin = selectedId
      ? assembly.find((part) => part.id === selectedId && part.type === "fin")
      : null;
    if (!selectedFin) return "";
    const diameterIn = Number(window.localStorage.getItem("arx_module_r_width") || "0");
    if (!(diameterIn > 0)) return "";
    const recommended = diameterIn * 3;
    const current = Number(selectedFin.params.span ?? 0);
    const tolerance = Math.max(0.15, recommended * 0.08);
    if (Math.abs(current - recommended) <= tolerance) {
      return `FIN SPAN PROPORTIONAL (${recommended.toFixed(2)} IN TARGET)`;
    }
    return `RECOMMENDED FIN SPAN ${recommended.toFixed(2)} IN (1:3 BODY:SPAN)`;
  }, [assembly, selectedId]);

  const refreshParts = useCallback(() => {
    const mode = String(window.localStorage.getItem("arx_module_r_mode") || "MANUAL").toUpperCase();
    const useCanonical = mode === "AUTO";
    const canonicalParts = buildAvailablePartsFromCanonicalImport();
    const nextParts = useCanonical && canonicalParts.length > 0 ? canonicalParts : buildAvailableParts();
    setAvailableParts(nextParts);
    syncAssemblyFromCatalog(nextParts);
  }, [setAvailableParts, syncAssemblyFromCatalog]);

  useEffect(() => {
    refreshParts();
    const handler = () => refreshParts();
    window.addEventListener("arx:module-r:parts-updated", handler);
    return () => window.removeEventListener("arx:module-r:parts-updated", handler);
  }, [refreshParts]);

  useEffect(() => {
    const trackedKeys = [
      "arx_module_r_mode",
      "arx_module_r_width",
      "arx_module_r_motor_mounts",
      "arx_module_r_nose_cone",
      "arx_module_r_fins",
      "arx_module_r_additional_tubes",
      "arx_module_r_latest_auto_assembly",
    ];
    const snapshot = () =>
      trackedKeys.map((key) => `${key}:${window.localStorage.getItem(key) ?? ""}`).join("|");
    let last = snapshot();
    const timer = window.setInterval(() => {
      const next = snapshot();
      if (next !== last) {
        last = next;
        refreshParts();
      }
    }, 700);
    return () => window.clearInterval(timer);
  }, [refreshParts]);

  const partsById = useMemo(
    () => new Map(availableParts.map((part) => [part.id, part])),
    [availableParts]
  );
  const assemblyIds = useMemo(() => new Set(assembly.map((part) => part.id)), [assembly]);
  const storageParts = useMemo(
    () =>
      availableParts.filter((part) => {
        if (assemblyIds.has(part.id)) return false;
        const isAdditionalNested =
          String(part.params.parentType ?? "").toLowerCase() === "additional tube" &&
          Boolean(part.internal);
        return !isAdditionalNested;
      }),
    [availableParts, assemblyIds]
  );
  const selectedPart = useMemo(
    () => assembly.find((part) => part.id === selectedId) || null,
    [assembly, selectedId]
  );

  const handleDragEnd = (event: DragEndEvent) => {
    if (!event.over || event.over.id !== "workspace") return;
    const part = partsById.get(String(event.active.id));
    if (!part) return;
    const snap = nearestLinearSnapOnDrop(part, assembly, lastDropPosition);
    const dropPosition: [number, number, number] = snap
      ? [snap.x, snap.y, snap.z]
      : lastDropPosition;
    addToAssembly(part, dropPosition);
    selectPart(part.id);
  };
  const handleStorageTrayWheel = useCallback((event: React.WheelEvent<HTMLDivElement>) => {
    const tray = event.currentTarget;
    if (tray.scrollWidth <= tray.clientWidth + 1) return;

    const dominantDelta =
      Math.abs(event.deltaY) >= Math.abs(event.deltaX) ? event.deltaY : event.deltaX;
    if (!Number.isFinite(dominantDelta) || dominantDelta === 0) return;

    const maxScrollLeft = tray.scrollWidth - tray.clientWidth;
    const atStart = tray.scrollLeft <= 1;
    const atEnd = tray.scrollLeft >= maxScrollLeft - 1;
    const scrollingLeft = dominantDelta < 0;
    const scrollingRight = dominantDelta > 0;
    const canScrollHorizontally = (scrollingLeft && !atStart) || (scrollingRight && !atEnd);

    if (!canScrollHorizontally) return;

    event.preventDefault();
    tray.scrollLeft += dominantDelta;
  }, []);
  useEffect(() => {
    const onFs = () => setIsFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener("fullscreenchange", onFs);
    return () => document.removeEventListener("fullscreenchange", onFs);
  }, []);
  const toggleFullscreen = useCallback(async () => {
    const panel = workspacePanelRef.current;
    if (!panel) return;
    if (document.fullscreenElement) {
      await document.exitFullscreen();
      return;
    }
    await panel.requestFullscreen();
  }, []);

  const totalMassKg = useMemo(
    () => assembly.reduce((sum, part) => sum + computePartMassKg(part), 0),
    [assembly]
  );
  const totalMassLb = totalMassKg / LB_TO_KG;

  const handleExport = async () => {
    const apiBase =
      (import.meta as { env?: Record<string, string> }).env?.VITE_API_BASE_URL || "";

    const widthIn = Number(window.localStorage.getItem("arx_module_r_width") || "0");
    const globalDiameterM = widthIn * INCH_TO_M;

    const nose = JSON.parse(
      window.localStorage.getItem("arx_module_r_nose_cone") || "null"
    ) as { length_in?: number; profile?: string; material?: string } | null;

    if (!nose) return;

    const stages = JSON.parse(
      window.localStorage.getItem("arx_module_r_motor_mounts") || "[]"
    ) as Array<{
      length_in?: number;
      bulkhead_height_in?: number;
      bulkhead_material?: string;
      inner_tube_diameter_in?: number;
      inner_tube_thickness_in?: number;
    }>;

    const fins = JSON.parse(
      window.localStorage.getItem("arx_module_r_fins") || "[]"
    ) as Array<{
      parent?: string;
      count?: number;
      root?: number;
      tip?: number;
      span?: number;
      sweep?: number;
      thickness?: number;
    }>;

    const additional = JSON.parse(
      window.localStorage.getItem("arx_module_r_additional_tubes") || "[]"
    ) as Array<{
      components?: Array<{
        name?: string;
        type?: string;
        mass?: number;
        mass_lb?: number;
        drag_coefficient?: number;
        material?: string;
        is_override_active?: boolean;
        manual_override_mass_lb?: number;
      }>;
    }>;

    const assemblyMap = new Map(
      assembly.map((part) => [part.id, part.position[0]])
    );

    const stageEntries = stages.map((stage, index) => {
      const lengthM = Number(stage.length_in ?? 0) * INCH_TO_M;
      const bulkheadHeightM = Number(stage.bulkhead_height_in ?? 0) * INCH_TO_M;
      const innerDiameterM = Number(stage.inner_tube_diameter_in ?? 0) * INCH_TO_M;
      const thicknessM = Number(stage.inner_tube_thickness_in ?? 0) * INCH_TO_M;
      const outerDiameterM = innerDiameterM + thicknessM * 2;
      return {
        id: `stage-${index + 1}`,
        name: `Stage ${index + 1}`,
        length_m: lengthM,
        diameter_m: globalDiameterM,
        motor_mount: {
          id: `motor-mount-${index + 1}`,
          name: `Motor Mount ${index + 1}`,
          outer_diameter_m: outerDiameterM || globalDiameterM,
          inner_diameter_m: innerDiameterM || globalDiameterM * 0.96,
          length_m: lengthM,
          position_from_bottom_m: 0,
          is_motor_mount: true,
        },
        bulkhead: {
          id: `bulkhead-${index + 1}`,
          name: `Bulkhead ${index + 1}`,
          height_m: bulkheadHeightM || globalDiameterM * 0.05,
          material: stage.bulkhead_material || "Cardboard",
          position_from_top_m: 0,
        },
      };
    });

    const bodyTubes = additional.map((tube, tubeIndex) => {
      const tubeId = `additional-${tubeIndex + 1}`;
      const lengthM = globalDiameterM * 3;
      const children = (tube.components || []).map((component, index) => {
        const componentId = `additional-${tubeIndex + 1}-${index + 1}`;
        const baseX = assemblyMap.get(componentId) || 0;
        const parentX = assemblyMap.get(tubeId) || 0;
        const positionFromBottomM = clamp(
          (baseX - parentX) * INCH_TO_M,
          0,
          lengthM
        );
        if (component.type === "parachute") {
          const chuteMassKg =
            Number(
              component.is_override_active
                ? component.manual_override_mass_lb
                : component.mass_lb ?? component.mass ?? 0
            ) * LB_TO_KG;
          return {
            type: "parachute",
            id: `chute-${componentId}`,
            name: component.name || "Parachute",
            library_id: component.name || "parachute",
            diameter_m: globalDiameterM * 0.8,
            mass_kg: chuteMassKg,
            drag_coefficient: Number(component.drag_coefficient ?? 0.75),
            material: component.material || "Nylon",
            position_from_bottom_m: clamp(lengthM * 0.25, 0, lengthM),
          };
        }
        if (component.type === "telemetry") {
          const telemetryMassKg =
            Number(
              component.is_override_active
                ? component.manual_override_mass_lb
                : component.mass_lb ?? component.mass ?? 0
            ) * LB_TO_KG;
          return {
            type: "telemetry",
            id: `telemetry-${componentId}`,
            name: component.name || "Telemetry",
            mass_kg: telemetryMassKg,
            position_from_bottom_m: positionFromBottomM,
          };
        }
        if (component.type === "inner_tube") {
          return {
            type: "inner_tube",
            id: `inner-${componentId}`,
            name: component.name || "Inner Tube",
            outer_diameter_m: globalDiameterM * 0.5,
            inner_diameter_m: globalDiameterM * 0.46,
            length_m: globalDiameterM * 2,
            position_from_bottom_m: positionFromBottomM,
            is_motor_mount: false,
          };
        }
        return {
          type: "ballast",
          id: `mass-${componentId}`,
          name: component.name || "Mass",
          mass_kg: Math.max(
            Number(
              component.is_override_active
                ? component.manual_override_mass_lb
                : component.mass_lb ?? component.mass ?? 0
            ) * LB_TO_KG,
            0.001
          ),
          position_from_bottom_m: positionFromBottomM,
        };
      });
      return {
        id: tubeId,
        name: `Additional Tube ${tubeIndex + 1}`,
        length_m: lengthM,
        diameter_m: globalDiameterM,
        wall_thickness_m: 0.002,
        children,
      };
    });

    const finSets = fins.map((fin, index) => {
      const finId = `fin-${index + 1}`;
      const requestedParentId = fin.parent || "stage-1";
      const parentId = requestedParentId.startsWith("body-")
        ? requestedParentId.replace("body-", "stage-")
        : requestedParentId;
      const stageIdx = Number(parentId.split("-")[1] || "1") - 1;
      const parentLengthM = Number(stages[stageIdx]?.length_in ?? 0) * INCH_TO_M;
      const rootChordM = Number(fin.root ?? 0) * INCH_TO_M;
      const relative = String(fin.position_relative ?? "bottom").toLowerCase();
      const plusOffsetM = Number(fin.plus_offset ?? 0) * INCH_TO_M;
      const rawFromBottom =
        relative === "top"
          ? Math.max(0, parentLengthM - rootChordM - plusOffsetM)
          : Math.max(0, plusOffsetM);
      const positionFromBottomM = clamp(
        rawFromBottom,
        0,
        Math.max(parentLengthM - rootChordM, 0)
      );
      return {
        id: finId,
        name: `Fin Set ${index + 1}`,
        parent_tube_id: parentId,
        fin_count: Number(fin.count ?? 3),
        root_chord_m: Number(fin.root ?? 0) * INCH_TO_M,
        tip_chord_m: Number(fin.tip ?? 0) * INCH_TO_M,
        span_m: Number(fin.span ?? 0) * INCH_TO_M,
        sweep_m: Number(fin.sweep ?? 0) * INCH_TO_M,
        thickness_m: Number(fin.thickness ?? 0.003) * INCH_TO_M,
        position_from_bottom_m: positionFromBottomM,
      };
    });

    const payload = {
      name: "Manual Assembly",
      design_mode: "MANUAL",
      global_diameter_m: globalDiameterM,
      nose_cone: {
        id: "nose-1",
        name: "Nose Cone",
        type: String(nose.profile || "OGIVE"),
        length_m: Number(nose.length_in ?? 0) * INCH_TO_M,
        diameter_m: globalDiameterM,
        material: nose.material,
      },
      stages: stageEntries,
      body_tubes: bodyTubes,
      fin_sets: finSets,
      metadata: {
        total_mass_kg: totalMassKg,
        total_mass_lb: totalMassLb,
      },
    };

    const response = await fetch(`${apiBase}/api/v1/module-r/ork`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) return;
    const result = (await response.json()) as { ork_path: string; warnings?: string[] };
    if (Array.isArray(result.warnings) && result.warnings.length > 0) {
      window.alert(`Module R warning:\n${result.warnings.join("\n")}`);
    }
    const path = result.ork_path || "";
    const normalizedPath = path.replace(/\\/g, "/");
    const testsMarker = "/tests/";
    const rawRelativeDownloadPath = normalizedPath.includes(testsMarker)
      ? normalizedPath.split(testsMarker)[1]
      : normalizedPath.split("/").pop() || "";
    const relativeDownloadPath =
      rawRelativeDownloadPath && !rawRelativeDownloadPath.includes("/")
        ? `module_r/${rawRelativeDownloadPath}`
        : rawRelativeDownloadPath;
    const encodedRelativePath = relativeDownloadPath
      .split("/")
      .filter(Boolean)
      .map((segment) => encodeURIComponent(segment))
      .join("/");
    const downloadUrl = path.startsWith("http")
      ? path
      : `${apiBase}/api/v1/downloads/${encodedRelativePath}`;
    window.location.assign(downloadUrl);
  };

  return (
    <DndContext onDragEnd={handleDragEnd}>
      <div className="module-r-positioning-layout">
        <div className="module-r-workspace" ref={workspacePanelRef}>
          <div className="panel-header module-r-workspace-header">
            <div className="module-r-workspace-info-row">
              <span className="module-r-workspace-title">WORKSPACE</span>
              {selectedPart && (
                <span className="module-r-selected-label">
                  SELECTED: {selectedPart.label}
                </span>
              )}
              <span className="module-r-selected-label">
                TOTAL MASS: {totalMassKg.toFixed(2)} KG ({totalMassLb.toFixed(2)} LB)
              </span>
            </div>
            <div className="module-r-workspace-note-row">
              <span className="module-r-controls-hint">
                {viewMode === "3d"
                  ? "CONTROLS: LEFT DRAG ROTATE | SHIFT+LEFT DRAG PAN | MIDDLE DRAG ORBIT | WHEEL/TWO-FINGER ZOOM"
                  : "CONTROLS: LEFT CLICK SELECT | SHIFT+LEFT DRAG PAN | WHEEL/TWO-FINGER ZOOM"}
              </span>
              {showFinRecommendation && (
                <span className="module-r-selected-label">
                  FIN RECOMMENDATION ACTIVE
                </span>
              )}
              {finRecommendationText && (
                <span className="module-r-selected-label">{finRecommendationText}</span>
              )}
            </div>
            <div className="module-r-workspace-actions-row">
              <button
                type="button"
                className="module-r-toggle-btn"
                onClick={() => setViewMode((mode) => (mode === "3d" ? "2d" : "3d"))}
              >
                {viewMode === "3d" ? "2D" : "3D"}
              </button>
              {selectedId && (
                <>
                  <button
                    type="button"
                    className="module-r-toggle-btn"
                    onClick={() => flipPart(selectedId, "x")}
                  >
                    Flip X
                  </button>
                  <button
                    type="button"
                    className="module-r-toggle-btn"
                    onClick={() => flipPart(selectedId, "y")}
                  >
                    Flip Y
                  </button>
                  {viewMode === "3d" && (
                    <button
                      type="button"
                      className="module-r-toggle-btn"
                      onClick={() => flipPart(selectedId, "z")}
                    >
                      Flip Z
                    </button>
                  )}
                  {selectedPart?.type === "fin" && !selectedPart.finPlaced && (
                    <button
                      type="button"
                      className="module-r-toggle-btn"
                      onClick={() => setFinPlaced(selectedId)}
                    >
                      FinSnap
                    </button>
                  )}
                </>
              )}
              {history.length > 0 && (
                <button
                  type="button"
                  className="module-r-toggle-btn"
                  onClick={() => undoLast()}
                >
                  Undo
                </button>
              )}
              {storageParts.length === 0 && (
                <button
                  type="button"
                  className="module-r-toggle-btn"
                  onClick={() => handleExport()}
                >
                  Finish & Export
                </button>
              )}
              <button
                type="button"
                className="module-r-toggle-btn"
                onClick={() =>
                  setCameraMode((mode) =>
                    mode === "orthographic" ? "perspective" : "orthographic"
                  )
                }
              >
                {cameraMode === "orthographic" ? "PERSPECTIVE" : "ORTHO"}
              </button>
              <button
                type="button"
                className="module-r-toggle-btn"
                onClick={() => void toggleFullscreen()}
              >
                {isFullscreen ? "EXIT FULLSCREEN" : "FULLSCREEN"}
              </button>
            </div>
          </div>
          <WorkspaceDropZone>
            <Workspace
              parts={assembly}
              selectedId={selectedId}
              onSelect={selectPart}
              onPositionChange={updatePartPosition}
              cameraMode={cameraMode}
              viewMode={viewMode}
              onHoverPosition={setLastDropPosition}
              backgroundImageUrl="/rocket_bg.png"
            />
          </WorkspaceDropZone>
        </div>

        <div className="module-r-storage">
          <div className="panel-header">COMPONENT STORAGE</div>
          <div className="module-r-storage-list" onWheel={handleStorageTrayWheel}>
            {storageParts.length === 0 ? (
              <div className="module-r-storage-empty">NO COMPONENTS AVAILABLE</div>
            ) : (
              storageParts.map((part) => <StorageItem key={part.id} part={part} />)
            )}
          </div>
        </div>
      </div>
    </DndContext>
  );
};
