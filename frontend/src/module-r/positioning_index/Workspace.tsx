import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { Canvas, useThree, type ThreeEvent } from "@react-three/fiber";
import { Grid, Line, OrbitControls, TransformControls } from "@react-three/drei";
import type { TransformControls as TransformControlsImpl } from "three-stdlib";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import { RocketPartGroup } from "./RocketPart";
import { AssemblyPart } from "./types";
import { generateFinShape, generateNoseConePoints, NoseConeType } from "./geometryUtils";

const GRID_COLOR = new THREE.Color("#123238");
const SNAP_STEP_X = 0.5;
const SNAP_STEP_Y = 0.5;
const FIN_SNAP_X_TOL = 8;
const FIN_SNAP_Y_TOL = 1;

type FinSnapTarget = {
  id: string;
  x: number;
  y: number;
  z: number;
  radius: number;
};

type CameraPose = {
  position: [number, number, number];
  target: [number, number, number];
  zoom?: number;
  fov?: number;
};

type SnapAnchor3D = {
  id: string;
  ownerId: string;
  outwardSign: -1 | 0 | 1;
  logical: [number, number, number];
};

const COMPONENT_SNAP_X_TOL = 2;
const COMPONENT_SNAP_Y_TOL = 1;

const nearestFinSnapTarget = (
  x: number,
  y: number,
  targets: FinSnapTarget[],
  enforceTolerance: boolean
) => {
  let best: FinSnapTarget | null = null;
  let bestScore = Number.POSITIVE_INFINITY;
  targets.forEach((target) => {
    const dx = Math.abs(x - target.x);
    const dy = Math.abs(y - target.y);
    if (enforceTolerance && (dx > FIN_SNAP_X_TOL || dy > FIN_SNAP_Y_TOL)) return;
    const score = dx * dx + dy * dy;
    if (score < bestScore) {
      best = target;
      bestScore = score;
    }
  });
  return best;
};

const resolveFinPreferredTargetId = (part: AssemblyPart) => {
  if (part.type !== "fin") return undefined;
  const rawParent = String(part.params.parent ?? "");
  if (!rawParent) return undefined;
  if (rawParent.startsWith("body-")) return rawParent;
  if (rawParent.startsWith("additional-")) {
    const segments = rawParent.split("-");
    return segments.length === 2 ? rawParent : `additional-${segments[1] || "1"}`;
  }
  if (rawParent.startsWith("stage-")) {
    const stageNum = rawParent.split("-")[1];
    return stageNum ? `body-${stageNum}` : undefined;
  }
  return undefined;
};

const getPartLength = (part: AssemblyPart) => Number(part.params.length ?? 0);
const isLinearSnapEligible = (part: AssemblyPart) =>
  part.type === "body" || part.type === "inner" || part.type === "nose";
const isSnapAnchorOwnerEligible = (part: AssemblyPart) =>
  isLinearSnapEligible(part) || part.type === "fin";
const isLongitudinalFlipped = (part: AssemblyPart) =>
  Boolean(part.flipX) !== Boolean(part.flipY);
const degToRad = (deg: number) => (deg * Math.PI) / 180;
const getFinBasePhase = (fin: AssemblyPart) => {
  const relative = String(fin.params.position_relative ?? "bottom").toLowerCase();
  const rotationDeg = Number(fin.params.rotation_deg ?? 0);
  const base = relative === "bottom" ? Math.PI : 0;
  const rotation = Number.isFinite(rotationDeg) ? degToRad(rotationDeg) : 0;
  return base + rotation;
};
const resolveParentBodyForFin = (fin: AssemblyPart, allParts: AssemblyPart[]) => {
  const preferredId = resolveFinPreferredTargetId(fin);
  return (
    (preferredId && allParts.find((part) => part.id === preferredId && part.type === "body")) ||
    allParts.find((part) => part.type === "body") ||
    null
  );
};
const computeFinRollForPart = (fin: AssemblyPart, allParts: AssemblyPart[]) => {
  const parentBody = resolveParentBodyForFin(fin, allParts);
  if (!parentBody) return 0;
  const dy = fin.position[1] - parentBody.position[1];
  const dz = fin.position[2] - parentBody.position[2];
  if (Math.abs(dy) < 1e-6 && Math.abs(dz) < 1e-6) {
    return getFinBasePhase(fin);
  }
  // Continuous roll aligns fin orientation with exact radial placement.
  return Math.atan2(dy, dz);
};
const worldToLogicalForFin = (world: THREE.Vector3): [number, number, number] => [
  world.z,
  world.y,
  world.x,
];
const computeFinEdgeCentersLogical = (
  fin: AssemblyPart,
  allParts: AssemblyPart[]
): [[number, number, number], [number, number, number]] => {
  const root = Number(fin.params.root ?? 0);
  const tip = Number(fin.params.tip ?? 0);
  const span = Number(fin.params.span ?? 0);
  const sweep = Number(fin.params.sweep ?? 0);
  const bodyRadius = Number(fin.params.radius ?? 0.5);

  const localRoot = new THREE.Vector3(root * 0.5, 0, 0);
  const localTip = new THREE.Vector3(sweep + tip * 0.5, span, 0);

  const meshMatrix = new THREE.Matrix4()
    .makeRotationZ(Math.PI / 2)
    .premultiply(new THREE.Matrix4().makeTranslation(bodyRadius, 0, 0));
  const rocketPartGroupMatrix = new THREE.Matrix4().makeRotationX(Math.PI / 2);

  const finRoll = computeFinRollForPart(fin, allParts);
  const partRotation = new THREE.Euler(
    fin.rotation[0] + (fin.flipX ? Math.PI : 0) + (fin.flipZ ? -Math.PI / 2 : 0),
    fin.rotation[1] + (fin.flipY ? Math.PI : 0),
    fin.rotation[2] + finRoll,
    "XYZ"
  );
  const partMatrix = new THREE.Matrix4().makeRotationFromEuler(partRotation);
  const partTranslation = new THREE.Matrix4().makeTranslation(
    fin.position[2],
    fin.position[1],
    fin.position[0]
  );
  const worldMatrix = new THREE.Matrix4()
    .copy(partTranslation)
    .multiply(partMatrix)
    .multiply(rocketPartGroupMatrix)
    .multiply(meshMatrix);

  const worldRoot = localRoot.clone().applyMatrix4(worldMatrix);
  const worldTip = localTip.clone().applyMatrix4(worldMatrix);
  return [worldToLogicalForFin(worldRoot), worldToLogicalForFin(worldTip)];
};
const snapFinXByParallelEdges = (fin: AssemblyPart, targetX: number) => {
  const root = Number(fin.params.root ?? 0);
  const tip = Number(fin.params.tip ?? 0);
  const sweep = Number(fin.params.sweep ?? 0);
  const dir = isLongitudinalFlipped(fin) ? -1 : 1;
  // Two parallel chord lines of a trapezoidal fin (root chord and tip chord),
  // represented by their longitudinal centers.
  const edgeCenters = [root * 0.5, sweep + tip * 0.5];
  const candidates = edgeCenters.map((offset) => targetX - offset * dir);
  const current = fin.position[0];
  return candidates.reduce(
    (best, value) => (Math.abs(current - value) < Math.abs(current - best) ? value : best),
    candidates[0] ?? targetX
  );
};

type ArmedFinRailTarget = {
  ballId: string;
  railKey: string;
  finId: string;
  edgeOffset: number;
};
const getLinearEndpoints = (part: AssemblyPart): [number, number] => {
  const length = getPartLength(part);
  if (part.type === "nose") {
    const dir = isLongitudinalFlipped(part) ? -1 : 1;
    return [part.position[0], part.position[0] + dir * length];
  }
  return [part.position[0], part.position[0] + length];
};

const nearestLinearSnap = (
  part: AssemblyPart,
  allParts: AssemblyPart[] = [],
  current: [number, number, number]
) => {
  if (part.type === "fin") return null;
  const selfLength = getPartLength(part);
  const candidates: Array<{ x: number; y: number; score: number }> = [];

  allParts.forEach((other) => {
    if (other.id === part.id) return;
    const otherLength = getPartLength(other);
    const otherFront = other.position[0];
    const otherAft = other.position[0] + otherLength;

    if (part.type === "nose") {
      if (other.type === "body" || other.type === "inner") {
        const x = otherFront - selfLength;
        const dx = Math.abs(current[0] - x);
        const dy = Math.abs(current[1] - other.position[1]);
        candidates.push({ x, y: other.position[1], score: dx * dx + dy * dy });
      }
      return;
    }

    if (part.type === "body" || part.type === "inner") {
      if (other.type === "body" || other.type === "inner" || other.type === "nose") {
        const x = otherAft;
        const dx = Math.abs(current[0] - x);
        const dy = Math.abs(current[1] - other.position[1]);
        candidates.push({ x, y: other.position[1], score: dx * dx + dy * dy });
      }
    }
  });

  let best: { x: number; y: number; score: number } | null = null;
  candidates.forEach((candidate) => {
    const dx = Math.abs(current[0] - candidate.x);
    const dy = Math.abs(current[1] - candidate.y);
    if (dx > COMPONENT_SNAP_X_TOL || dy > COMPONENT_SNAP_Y_TOL) return;
    if (!best || candidate.score < best.score) best = candidate;
  });
  return best;
};

const toWorldPointFromLogical = (logical: [number, number, number]): [number, number, number] => [
  logical[2],
  logical[1],
  logical[0],
];

const getAnchorDisplayLogical = (
  anchor: SnapAnchor3D,
  owner: AssemblyPart | undefined
): [number, number, number] => {
  if (owner?.type === "fin") {
    // Fin edge-center balls should sit on the true fin geometry points.
    return [...anchor.logical];
  }
  const radius = Number(owner?.params.radius ?? 0.5);
  const outward = Math.max(0.8, radius * 0.45);
  const direction = anchor.outwardSign;
  return [anchor.logical[0] + direction * outward, anchor.logical[1], anchor.logical[2]];
};
const isAdditionalTubeNested = (part: AssemblyPart) =>
  String(part.params.parentType ?? "").toLowerCase() === "additional tube";
const isStageInnerTube = (part: AssemblyPart) =>
  part.type === "inner" && String(part.params.parentType ?? "").toLowerCase() === "stage";
const getLogicalHitboxDims = (part: AssemblyPart): [number, number, number] => {
  const configuredScale = Number(
    part.params.logicalHitboxScale ?? part.params.logical_hitbox_scale ?? 1.35
  );
  const scale = Math.max(1.15, Math.min(1.8, configuredScale));
  const length = Math.max(0.6, Number(part.params.length ?? 6));
  const radius = Math.max(0.35, Number(part.params.radius ?? 1));
  if (part.type === "fin") {
    const span = Math.max(0.35, Number(part.params.span ?? 2));
    const root = Math.max(0.35, Number(part.params.root ?? 2));
    const tip = Math.max(0.35, Number(part.params.tip ?? 1.5));
    const sweep = Math.max(0, Number(part.params.sweep ?? 0));
    const xSize = Math.max(root, tip + sweep, root + sweep, 1.2);
    return [xSize * scale, span * scale, Math.max(radius * 1.2, span * 0.7, 1.0) * scale];
  }
  if (part.type === "nose") {
    return [length * scale, radius * 2 * scale, radius * 2 * scale];
  }
  return [length * scale, radius * 2 * scale, radius * 2 * scale];
};

const PartInstance3D: React.FC<{
  part: AssemblyPart;
  allParts: AssemblyPart[];
  selected: boolean;
  onSelect: () => void;
  onPositionChange: (position: [number, number, number]) => void;
  onDragState: (dragging: boolean) => void;
  shiftPressed: boolean;
}> = ({
  part,
  allParts,
  selected,
  onSelect,
  onPositionChange,
  onDragState,
  shiftPressed,
}) => {
  const groupRef = useRef<THREE.Group | null>(null);
  const controlsRef = useRef<TransformControlsImpl | null>(null);
  const lengthForPlacement = useMemo(() => Number(part.params.length ?? 0), [part.params.length]);
  const longitudinalOffset = useMemo(() => {
    if (part.type === "body" || part.type === "inner") return lengthForPlacement / 2;
    if (part.type === "nose") return 0;
    return 0;
  }, [part.type, lengthForPlacement]);
  const toWorldPosition = useCallback(
    (logical: [number, number, number]): [number, number, number] => [
      logical[2],
      logical[1],
      logical[0] + longitudinalOffset,
    ],
    [longitudinalOffset]
  );
  const toLogicalPosition = useCallback(
    (world: [number, number, number]): [number, number, number] => [
      world[2] - longitudinalOffset,
      world[1],
      world[0],
    ],
    [longitudinalOffset]
  );
  const snapLogicalPosition = useCallback(
    (logical: [number, number, number]): [number, number, number] => [
      Math.round(logical[0]),
      Math.round(logical[1]),
      Math.round(logical[2]),
    ],
    []
  );
  const finRoll = useMemo(() => {
    if (part.type !== "fin") return 0;
    return computeFinRollForPart(part, allParts);
  }, [allParts, part]);
  const interactionLocked = isAdditionalTubeNested(part) || isStageInnerTube(part);

  useEffect(() => {
    if (!controlsRef.current) return;
    const controls = controlsRef.current;
    const handleChange = () => {
      if (!selected) return;
      if (!groupRef.current) return;
      const { x, y, z } = groupRef.current.position;
      onPositionChange(snapLogicalPosition(toLogicalPosition([x, y, z])));
    };
    const handleDragging = (event: { value: boolean }) => {
      if (!selected) return;
      onDragState(event.value);
    };
    controls.addEventListener("objectChange", handleChange);
    controls.addEventListener("dragging-changed", handleDragging);
    return () => {
      controls.removeEventListener("objectChange", handleChange);
      controls.removeEventListener("dragging-changed", handleDragging);
    };
  }, [onDragState, onPositionChange, selected, snapLogicalPosition, toLogicalPosition]);

  useEffect(() => {
    if (!controlsRef.current) return;
    const controls = controlsRef.current;
    const suppressPlaneVisuals = () => {
      const controlsObject = controls as unknown as THREE.Object3D;
      controlsObject.traverse((obj) => {
        const mesh = obj as THREE.Mesh;
        if (!mesh.isMesh) return;
        const isPlaneHandle =
          ["XY", "YZ", "XZ", "XYZE", "E"].includes(mesh.name) ||
          mesh.geometry?.type === "PlaneGeometry";
        if (!isPlaneHandle) return;
        mesh.visible = true;
        const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
        materials.forEach((material) => {
          if (!material) return;
          material.transparent = true;
          material.opacity = 0;
          material.depthWrite = false;
          material.needsUpdate = true;
        });
      });
    };
    suppressPlaneVisuals();
    controls.addEventListener("change", suppressPlaneVisuals);
    return () => {
      controls.removeEventListener("change", suppressPlaneVisuals);
    };
  }, [selected]);

  const body = (
    <group
      ref={groupRef}
      position={toWorldPosition(part.position)}
      rotation={[
        part.rotation[0] + (part.flipX ? Math.PI : 0) + (part.flipZ ? -Math.PI / 2 : 0),
        part.rotation[1] + (part.flipY ? Math.PI : 0),
        part.rotation[2] + finRoll,
      ]}
      onClick={(event) => {
        if (shiftPressed) return;
        if (event.button !== 0) return;
        if (interactionLocked) return;
        event.stopPropagation();
        onSelect();
      }}
    >
      <RocketPartGroup
        part={
          part.type === "fin" && !part.finPlaced
            ? { ...part, params: { ...part.params, fin_count: 1, count: 1 } }
            : part
        }
        flipX={part.flipX}
        flipY={part.flipY}
      />
      <mesh>
        <boxGeometry args={getLogicalHitboxDims(part)} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>
    </group>
  );

  if (!selected) return body;

  return (
    <TransformControls
      ref={controlsRef}
      mode="translate"
      enabled={!interactionLocked}
      space="world"
      translationSnap={1}
      size={0.85}
      showX
      showY
      showZ
    >
      {body}
    </TransformControls>
  );
};

const OUTLINE_COLORS: Record<string, string> = {
  body: "#6bff9b",
  nose: "#00f3ff",
  fin: "#ffd700",
  inner: "#7cc7ff",
  parachute: "#ff9be4",
  telemetry: "#c7ff5a",
  mass: "#ff8f4d",
};

const buildBodyOutline = (length: number, radius: number) => [
  new THREE.Vector3(0, -radius, 0),
  new THREE.Vector3(length, -radius, 0),
  new THREE.Vector3(length, radius, 0),
  new THREE.Vector3(0, radius, 0),
  new THREE.Vector3(0, -radius, 0),
];

const buildNoseOutline = (length: number, radius: number, profile: NoseConeType) => {
  const points = generateNoseConePoints(profile, length, radius);
  const upper = points.map((p) => new THREE.Vector3(p.y, p.x, 0));
  const lower = points
    .slice()
    .reverse()
    .map((p) => new THREE.Vector3(p.y, -p.x, 0));
  return [...lower, ...upper, lower[0]];
};

const buildFinOutline = (root: number, tip: number, span: number, sweep: number) => {
  const shape = generateFinShape(root, tip, span, sweep);
  const pts = shape.map((p) => new THREE.Vector3(p.x, p.y, 0));
  pts.push(pts[0]);
  return pts;
};

const buildEllipticalFinOutline = (root: number, span: number) => {
  const rx = Math.max(root * 0.5, 0.1);
  const ry = Math.max(span * 0.5, 0.1);
  const steps = 36;
  const pts: THREE.Vector3[] = [];
  for (let i = 0; i <= steps; i += 1) {
    const t = (Math.PI * 2 * i) / steps;
    pts.push(new THREE.Vector3(rx + Math.cos(t) * rx, ry + Math.sin(t) * ry, 0));
  }
  return pts;
};

const parseFreeformPoints = (raw: unknown): Array<{ x: number; y: number }> | null => {
  if (typeof raw !== "string" || !raw.trim()) return null;
  try {
    const parsed = JSON.parse(raw) as Array<{ x?: unknown; y?: unknown }>;
    if (!Array.isArray(parsed)) return null;
    const points = parsed
      .map((p) => ({ x: Number(p?.x), y: Number(p?.y) }))
      .filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y));
    if (points.length < 3) return null;
    return points;
  } catch {
    return null;
  }
};

const buildFreeFormOutline = (points: Array<{ x: number; y: number }>) => {
  const pts = points.map((p) => new THREE.Vector3(p.x, p.y, 0));
  pts.push(new THREE.Vector3(points[0].x, points[0].y, 0));
  return pts;
};

const buildTubeFinOutline = (length: number, outerDiameter: number) => {
  const w = Math.max(length, 0.1);
  const h = Math.max(outerDiameter, 0.1);
  const rx = h * 0.5;
  const ry = rx;
  const left = 0;
  const right = w;
  const top = h * 0.5;
  const bottom = -h * 0.5;
  const steps = 14;
  const pts: THREE.Vector3[] = [];
  pts.push(new THREE.Vector3(left + rx, top, 0));
  pts.push(new THREE.Vector3(right - rx, top, 0));
  for (let i = 0; i <= steps; i += 1) {
    const t = (-Math.PI / 2) + (Math.PI * i) / steps;
    pts.push(new THREE.Vector3(right - rx + Math.cos(t) * rx, (top + bottom) * 0.5 + Math.sin(t) * ry, 0));
  }
  pts.push(new THREE.Vector3(left + rx, bottom, 0));
  for (let i = 0; i <= steps; i += 1) {
    const t = (Math.PI / 2) + (Math.PI * i) / steps;
    pts.push(new THREE.Vector3(left + rx + Math.cos(t) * rx, (top + bottom) * 0.5 + Math.sin(t) * ry, 0));
  }
  pts.push(pts[0]);
  return pts;
};

const PartInstance2D: React.FC<{
  part: AssemblyPart;
  allParts: AssemblyPart[];
  selected: boolean;
  onSelect: () => void;
  onPositionChange: (position: [number, number, number]) => void;
  onDragState: (dragging: boolean) => void;
  finSnapTargets: FinSnapTarget[];
  shiftPressed: boolean;
}> = ({
  part,
  allParts = [],
  selected,
  onSelect,
  onPositionChange,
  onDragState,
  finSnapTargets,
  shiftPressed,
}) => {
  const groupRef = useRef<THREE.Group | null>(null);
  const { camera, gl } = useThree();
  const draggingRef = useRef(false);
  const dragTargetRef = useRef<{ type: "group" | "fin"; index?: number }>({
    type: "group",
  });
  const offsetRef = useRef(new THREE.Vector3());
  const planeRef = useRef(new THREE.Plane(new THREE.Vector3(0, 0, 1), 0));
  const raycasterRef = useRef(new THREE.Raycaster());
  const pointerRef = useRef(new THREE.Vector2());
  const latestDragPositionRef = useRef<[number, number, number]>(part.position);
  const { type, params } = part;
  const interactionLocked = isAdditionalTubeNested(part) || isStageInnerTube(part);
  const preferredTargetId = useMemo(() => resolveFinPreferredTargetId(part), [part]);
  const radius = Number(params.radius ?? 0.5);
  const length = Number(params.length ?? 1);

  const outlines = useMemo(() => {
    if (type === "body" || type === "inner") {
      return [buildBodyOutline(length, radius)];
    }
    if (type === "nose") {
      const profile = String(params.profile ?? "OGIVE") as NoseConeType;
      return [buildNoseOutline(length, radius, profile)];
    }
    if (type === "fin") {
      const finType = String(params.fin_type ?? "trapezoidal").toLowerCase();
      const root = Number(params.root ?? 1);
      const tip = Number(params.tip ?? 0.5);
      const span = Number(params.span ?? 0.5);
      const sweep = Number(params.sweep ?? 0);
      if (finType === "elliptical") {
        return [buildEllipticalFinOutline(root, span)];
      }
      if (finType === "tube_fin") {
        const tubeLength = Number(params.tube_length ?? root ?? 4);
        const tubeOuter = Number(params.tube_outer_diameter ?? span ?? 2);
        return [buildTubeFinOutline(tubeLength, tubeOuter)];
      }
      if (finType === "free_form" || finType === "free form") {
        const freePoints = parseFreeformPoints(params.free_points);
        if (freePoints) return [buildFreeFormOutline(freePoints)];
      }
      return [buildFinOutline(root, tip, span, sweep)];
    }
    return [buildBodyOutline(length * 0.6, radius * 0.6)];
  }, [type, params, length, radius]);

  const finCount = Math.max(1, Number(params.fin_count ?? params.count ?? 1));

  const nearestTarget = useMemo(() => {
    const preferred = preferredTargetId
      ? finSnapTargets.find((target) => target.id === preferredTargetId)
      : null;
    if (preferred) return preferred;
    return nearestFinSnapTarget(part.position[0], part.position[1], finSnapTargets, false);
  }, [part.position, finSnapTargets, preferredTargetId]);

  const finProjection = useMemo(() => {
    if (type !== "fin") return outlines.map((outline) => ({ variant: outline, depthZ: 1 }));
    const span = Number(params.span ?? 0.5);
    const flipX = part.flipX ? -1 : 1;
    const flipY = part.flipY ? -1 : 1;
    const tubeRadius = nearestTarget?.radius ?? Math.max(0.5, span * 0.5);
    const basePhase = getFinBasePhase(part);
    const baseOutlines = outlines.map((outline) =>
      outline.map((p) => new THREE.Vector3(-p.x * flipX, p.y * flipY, p.z))
    );
    // Fin set is treated as one entity; per-fin offsets are intentionally ignored.
    const offsets = Array.from({ length: finCount }).map(() => [0, 0] as [number, number]);
    const projected = offsets.flatMap((offset, idx) => {
      const theta = basePhase + (Math.PI * 2 * idx) / finCount;
      const radialY = Math.cos(theta);
      const depthZ = Math.sin(theta);
      const rootY = part.position[1] + tubeRadius * radialY;
      return baseOutlines.map((base) => ({
        variant: base.map(
          (p) =>
            new THREE.Vector3(
              p.x + offset[0],
              rootY + p.y * radialY + offset[1],
              0
            )
        ),
        depthZ,
      }));
    });
    return projected;
  }, [
    type,
    outlines,
    part.flipX,
    part.flipY,
    part.finOffsets,
    finCount,
    params.span,
    params.position_relative,
    nearestTarget,
    part.position,
  ]);

  const visibleProjection =
    type === "fin" && !part.finPlaced ? finProjection.slice(0, 1) : finProjection;

  useEffect(() => {
    const handlePointerMove = (event: PointerEvent) => {
      try {
        if (!draggingRef.current) return;
        const rect = gl.domElement.getBoundingClientRect();
        pointerRef.current.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
        pointerRef.current.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
        raycasterRef.current.setFromCamera(pointerRef.current, camera);
        const intersection = new THREE.Vector3();
        raycasterRef.current.ray.intersectPlane(planeRef.current, intersection);
        const next = intersection.sub(offsetRef.current);
        const nextX =
          part.type === "fin" ? next.x : Math.round(next.x / SNAP_STEP_X) * SNAP_STEP_X;
        const nextY =
          part.type === "fin" ? next.y : Math.round(next.y / SNAP_STEP_Y) * SNAP_STEP_Y;
        latestDragPositionRef.current = [nextX, nextY, 0];
        onPositionChange([nextX, nextY, 0]);
      } catch (error) {
        console.error("2D drag move failed", error);
      }
    };

    const handlePointerUp = () => {
      try {
        if (!draggingRef.current) return;
        draggingRef.current = false;
        onDragState(false);
        if (dragTargetRef.current.type === "group" && part.type !== "fin") {
          const linearSnap = nearestLinearSnap(part, allParts, latestDragPositionRef.current);
          if (linearSnap) {
            onPositionChange([linearSnap.x, linearSnap.y, 0]);
          }
        }
      } catch (error) {
        console.error("2D drag end failed", error);
      }
    };

    const handlePointerCancel = () => {
      if (!draggingRef.current) return;
      draggingRef.current = false;
      onDragState(false);
    };

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp);
    window.addEventListener("pointercancel", handlePointerCancel);
    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
      window.removeEventListener("pointercancel", handlePointerCancel);
    };
  }, [
    camera,
    gl,
    onDragState,
    onPositionChange,
    part.id,
    part.position,
    part.type,
    part.finPlaced,
    finSnapTargets,
    preferredTargetId,
    allParts,
  ]);

  const color = OUTLINE_COLORS[type] ?? "#9ff5ff";

  const bounds = useMemo(() => {
    const xs = visibleProjection.flatMap((item) => item.variant.map((p) => p.x));
    const ys = visibleProjection.flatMap((item) => item.variant.map((p) => p.y));
    if (xs.length === 0 || ys.length === 0) {
      return { width: 2, height: 2 };
    }
    const width = Math.max(...xs) - Math.min(...xs);
    const height = Math.max(...ys) - Math.min(...ys);
    return {
      width: Math.max(width, 2),
      height: Math.max(height, 2),
    };
  }, [visibleProjection]);

  const body = (
    <group
      ref={groupRef}
      position={[part.position[0], part.position[1], 0]}
      onPointerDown={(event) => {
        if (shiftPressed) return;
        if (interactionLocked) {
          event.stopPropagation();
          onSelect();
          return;
        }
        if (event.button !== 0) return;
        event.stopPropagation();
        onSelect();
        if (!groupRef.current) return;
        dragTargetRef.current = { type: "group" };
        draggingRef.current = true;
        onDragState(true);
        latestDragPositionRef.current = [...part.position] as [number, number, number];
        offsetRef.current.copy(event.point).sub(groupRef.current.position);
      }}
      onPointerUp={(event) => {
        if (event.currentTarget.hasPointerCapture(event.pointerId)) {
          event.currentTarget.releasePointerCapture(event.pointerId);
        }
      }}
      onPointerCancel={(event) => {
        if (event.currentTarget.hasPointerCapture(event.pointerId)) {
          event.currentTarget.releasePointerCapture(event.pointerId);
        }
      }}
    >
      {visibleProjection.map(({ variant, depthZ }, idx) => (
        <group
          key={idx}
          onPointerDown={(event) => {
            if (shiftPressed) return;
            if (event.button !== 0) return;
            if (type !== "fin") return;
            event.stopPropagation();
            onSelect();
            if (!groupRef.current) return;
            dragTargetRef.current = { type: "fin", index: idx };
            draggingRef.current = true;
            onDragState(true);
            latestDragPositionRef.current = [...part.position] as [number, number, number];
            offsetRef.current.copy(event.point).sub(groupRef.current.position);
          }}
        >
          {selected && type === "fin" && (() => {
            const xs = variant.map((p) => p.x);
            const ys = variant.map((p) => p.y);
            const minX = Math.min(...xs);
            const maxX = Math.max(...xs);
            const minY = Math.min(...ys);
            const maxY = Math.max(...ys);
            const width = Math.max(maxX - minX, 1);
            const height = Math.max(maxY - minY, 1);
            const centerX = (minX + maxX) / 2;
            const centerY = (minY + maxY) / 2;
            return (
              <mesh position={[centerX, centerY, 0]}>
                <planeGeometry args={[width, height]} />
                <meshBasicMaterial transparent opacity={0} side={THREE.DoubleSide} />
              </mesh>
            );
          })()}
          <Line
            points={variant}
            color={type === "fin" && depthZ < 0 ? "#8a7b2a" : color}
            lineWidth={2}
            dashed={type === "fin" && depthZ < 0}
            dashSize={1.5}
            gapSize={1.1}
          />
        </group>
      ))}
      {selected && (
        <mesh>
          <planeGeometry args={[bounds.width, bounds.height]} />
          <meshBasicMaterial transparent opacity={0} side={THREE.DoubleSide} />
        </mesh>
      )}
    </group>
  );

  return body;
};

const SceneBackground: React.FC<{ viewMode: "3d" | "2d"; backgroundImageUrl?: string }> = ({
  viewMode,
  backgroundImageUrl,
}) => {
  const { gl, scene } = useThree();
  const textureRef = useRef<THREE.Texture | null>(null);
  useEffect(() => {
    if (viewMode === "3d" && backgroundImageUrl) {
      const loader = new THREE.TextureLoader();
      loader.load(backgroundImageUrl, (tex) => {
        tex.colorSpace = THREE.SRGBColorSpace;
        tex.wrapS = THREE.ClampToEdgeWrapping;
        tex.wrapT = THREE.ClampToEdgeWrapping;
        tex.minFilter = THREE.LinearFilter;
        tex.magFilter = THREE.LinearFilter;
        tex.generateMipmaps = false;
        textureRef.current = tex;
        scene.background = tex;
      });
      return;
    }
    scene.background = null;
    if (viewMode === "2d") {
      gl.setClearColor("#000000", 0);
      return;
    }
    gl.setClearColor("#020407", 1);
  }, [gl, scene, viewMode, backgroundImageUrl]);
  useEffect(() => () => {
    if (textureRef.current) {
      textureRef.current.dispose();
      textureRef.current = null;
    }
  }, []);
  return null;
};

const CameraRig: React.FC<{
  viewMode: "3d" | "2d";
  cameraMode: "orthographic" | "perspective";
  pose: CameraPose;
}> = ({ viewMode, cameraMode, pose }) => {
  const { camera } = useThree();

  useEffect(() => {
    const isOrtho = (camera as THREE.OrthographicCamera).isOrthographicCamera;
    if (isOrtho) {
      const ortho = camera as THREE.OrthographicCamera;
      ortho.position.set(pose.position[0], pose.position[1], pose.position[2]);
      ortho.zoom = pose.zoom ?? (viewMode === "2d" ? 12 : 16);
      ortho.near = 0.1;
      ortho.far = 5000;
      ortho.up.set(0, 1, 0);
      ortho.lookAt(pose.target[0], pose.target[1], pose.target[2]);
      ortho.updateProjectionMatrix();
      return;
    }

    const perspective = camera as THREE.PerspectiveCamera;
    perspective.position.set(pose.position[0], pose.position[1], pose.position[2]);
    perspective.fov = pose.fov ?? (viewMode === "2d" ? 28 : 45);
    perspective.near = 0.1;
    perspective.far = 5000;
    perspective.up.set(0, 1, 0);
    perspective.lookAt(pose.target[0], pose.target[1], pose.target[2]);
    perspective.updateProjectionMatrix();
  }, [camera, viewMode, cameraMode, pose]);

  return null;
};

const HoverTracker: React.FC<{
  viewMode: "3d" | "2d";
  onHoverPosition: (position: [number, number, number]) => void;
}> = ({ viewMode, onHoverPosition }) => {
  const { camera, gl } = useThree();
  const raycaster = useRef(new THREE.Raycaster());
  const pointer = useRef(new THREE.Vector2());
  const plane = useRef(new THREE.Plane(new THREE.Vector3(0, 0, 1), 0));

  useEffect(() => {
    const handleMove = (event: PointerEvent) => {
      const rect = gl.domElement.getBoundingClientRect();
      if (
        event.clientX < rect.left ||
        event.clientX > rect.right ||
        event.clientY < rect.top ||
        event.clientY > rect.bottom
      ) {
        return;
      }
      pointer.current.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.current.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.current.setFromCamera(pointer.current, camera);
      const intersection = new THREE.Vector3();
      if (viewMode === "2d") {
        plane.current.set(new THREE.Vector3(0, 0, 1), 0);
      } else {
        // Use world "ground" plane for stable 3D cursor-drop mapping.
        plane.current.set(new THREE.Vector3(0, 1, 0), 0);
      }
      if (!raycaster.current.ray.intersectPlane(plane.current, intersection)) return;
      if (viewMode === "2d") {
        onHoverPosition([intersection.x, intersection.y, 0]);
      } else {
        // Match PartInstance3D mapping: world[x,y,z] -> logical[z,y,x].
        onHoverPosition([intersection.z, intersection.y, intersection.x]);
      }
    };
    window.addEventListener("pointermove", handleMove);
    return () => window.removeEventListener("pointermove", handleMove);
  }, [camera, gl, onHoverPosition, viewMode]);

  return null;
};

export const Workspace: React.FC<{
  parts: AssemblyPart[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onPositionChange: (id: string, position: [number, number, number]) => void;
  cameraMode: "orthographic" | "perspective";
  viewMode: "3d" | "2d";
  onHoverPosition: (position: [number, number, number]) => void;
  backgroundImageUrl?: string;
}> = ({
  parts,
  selectedId,
  onSelect,
  onPositionChange,
  cameraMode,
  viewMode,
  onHoverPosition,
  backgroundImageUrl,
}) => {
  const makeSceneKey = useCallback(
    (mode: "3d" | "2d", cam: "orthographic" | "perspective") => `${mode}-${cam}`,
    []
  );
  const defaultPoseFor = useCallback(
    (mode: "3d" | "2d", cam: "orthographic" | "perspective"): CameraPose => {
      if (mode === "2d" && cam === "orthographic") {
        return { position: [0, 0, 80], target: [0, 0, 0], zoom: 12 };
      }
      if (mode === "2d" && cam === "perspective") {
        return { position: [0, 0, 120], target: [0, 0, 0], fov: 28 };
      }
      if (mode === "3d" && cam === "orthographic") {
        return { position: [80, 55, 80], target: [0, 0, 0], zoom: 16 };
      }
      return { position: [80, 55, 80], target: [0, 0, 0], fov: 45 };
    },
    []
  );

  const sceneKey = makeSceneKey(viewMode, cameraMode);
  const [cameraPoses, setCameraPoses] = useState<Record<string, CameraPose>>({});
  const pose = cameraPoses[sceneKey] ?? defaultPoseFor(viewMode, cameraMode);
  const [armedSnapAnchorId, setArmedSnapAnchorId] = useState<string | null>(null);
  const [armedFinRailTarget, setArmedFinRailTarget] = useState<ArmedFinRailTarget | null>(null);

  const [size, setSize] = useState({ width: 1, height: 1 });
  const [isDragging2d, setIsDragging2d] = useState(false);
  const [isDragging3d, setIsDragging3d] = useState(false);
  const [shiftPressed, setShiftPressed] = useState(false);
  const orbitRef = useRef<OrbitControlsImpl | null>(null);
  const gridConfig = useMemo(
    () =>
      viewMode === "3d"
        ? {
            cellColor: "#0a0a0a",
            sectionColor: "#000000",
          }
        : {
            cellColor: "#00f3ff",
            sectionColor: "#00f3ff",
          },
    [viewMode]
  );
  const grid = useMemo(
    () =>
      viewMode === "2d" ? (
        <Grid
          infiniteGrid
          cellSize={2}
          cellThickness={1.6}
          sectionSize={10}
          sectionThickness={2.2}
          fadeDistance={0}
          fadeStrength={0}
          cellColor={gridConfig.cellColor}
          sectionColor={gridConfig.sectionColor}
          renderOrder={10}
        />
      ) : null,
    [gridConfig, viewMode]
  );

  const useOrtho = cameraMode === "orthographic";

  const rocketComplete = useMemo(() => {
    const hasNose = parts.some((part) => part.type === "nose");
    const hasBody = parts.some((part) => part.type === "body");
    const hasMotor = parts.some((part) => part.type === "inner");
    return hasNose && hasBody && hasMotor;
  }, [parts]);

  const finSnapTargets = useMemo(() => {
    const bodyTargets = parts
      .filter((part) => part.type === "body")
      .map((part) => {
        const radius = Number(part.params.radius ?? 0.5);
        const length = Number(part.params.length ?? 0);
        const aftX = part.position[0] + length;
        const centerY = part.position[1];
        return {
          id: part.id,
          x: aftX,
          y: centerY,
          z: part.position[2] ?? 0,
          radius,
        } satisfies FinSnapTarget;
      });
    const targets = bodyTargets.length
      ? bodyTargets
      : parts
          .filter((part) => part.type === "inner")
          .map((part) => {
            const radius = Number(part.params.radius ?? 0.5);
            const length = Number(part.params.length ?? 0);
            const aftX = part.position[0] + length;
            const centerY = part.position[1];
            return {
              id: part.id,
              x: aftX,
              y: centerY,
              z: part.position[2] ?? 0,
              radius,
            } satisfies FinSnapTarget;
          });
    const dedup = new Map<string, FinSnapTarget>();
    targets.forEach((target) => {
      const snappedTarget = {
        ...target,
        x: Math.round(target.x),
        y: Math.round(target.y),
      };
      const key = `${snappedTarget.x}:${snappedTarget.y}`;
      if (!dedup.has(key)) dedup.set(key, snappedTarget);
    });
    return Array.from(dedup.values());
  }, [parts]);

  const showFinRecommendation =
    viewMode === "2d" &&
    rocketComplete &&
    finSnapTargets.length > 0 &&
    parts.some((part) => part.type === "fin" && !part.finPlaced);
  const activeFinForRail = useMemo(() => {
    if (viewMode !== "3d") return null;
    const selected = selectedId ? parts.find((part) => part.id === selectedId) : null;
    return selected?.type === "fin" ? selected : null;
  }, [parts, selectedId, viewMode]);
  const railLines3d = useMemo(() => {
    if (!activeFinForRail) return null;
    const parentHint = resolveFinPreferredTargetId(activeFinForRail);
    const parentBody =
      (parentHint && parts.find((part) => part.id === parentHint && part.type === "body")) ||
      parts.find((part) => part.type === "body");
    if (!parentBody) return null;
    const radius = Number(parentBody.params.radius ?? 0.5);
    const centerY = parentBody.position[1];
    const centerZ = parentBody.position[2];
    const finThickness = Number(activeFinForRail.params.thickness ?? 0.08);
    const surfaceRadius = Math.max(radius - Math.max(finThickness * 0.25, 0.02), 0.06);
    const linearParts = parts.filter((part) => isLinearSnapEligible(part));
    if (linearParts.length === 0) return null;
    let minX = Number.POSITIVE_INFINITY;
    let maxX = Number.NEGATIVE_INFINITY;
    linearParts.forEach((part) => {
      const [a, b] = getLinearEndpoints(part);
      minX = Math.min(minX, a, b);
      maxX = Math.max(maxX, a, b);
    });
    if (!Number.isFinite(minX) || !Number.isFinite(maxX) || maxX <= minX) return null;
    const root = Number(activeFinForRail.params.root ?? 0);
    const tip = Number(activeFinForRail.params.tip ?? 0);
    const sweep = Number(activeFinForRail.params.sweep ?? 0);
    const finDir = isLongitudinalFlipped(activeFinForRail) ? -1 : 1;
    const edgeCenterOffsets = [root * 0.5, sweep + tip * 0.5];
    const edgeCenterXs = edgeCenterOffsets.map((offset) =>
      Math.max(minX, Math.min(maxX, activeFinForRail.position[0] + offset * finDir))
    );
    const finCount = Math.max(
      2,
      Number(activeFinForRail.params.fin_count ?? activeFinForRail.params.count ?? 1)
    );
    const basePhase = getFinBasePhase(activeFinForRail);
    const rails = Array.from({ length: finCount }).map((_, idx) => {
      const theta = basePhase + (Math.PI * 2 * idx) / finCount;
      const y = centerY + surfaceRadius * Math.cos(theta);
      const z = centerZ + surfaceRadius * Math.sin(theta);
      return {
        key: `${activeFinForRail.id}:rail-${idx}`,
        finId: activeFinForRail.id,
        minX,
        maxX,
        y,
        z,
        startWorld: new THREE.Vector3(z, y, minX),
        endWorld: new THREE.Vector3(z, y, maxX),
        midWorld: new THREE.Vector3(z, y, (minX + maxX) / 2),
        balls: edgeCenterXs.map((edgeX, edgeIdx) => ({
          id: `${activeFinForRail.id}:rail-${idx}:edge-${edgeIdx}`,
          edgeOffset: edgeCenterOffsets[edgeIdx],
          world: new THREE.Vector3(z, y, edgeX),
        })),
        railLength: Math.max(maxX - minX, 0.001),
      };
    });
    return rails;
  }, [activeFinForRail, parts]);
  const snapAnchors3d = useMemo(() => {
    if (viewMode !== "3d") return [];
    return parts
      .filter((part) => isSnapAnchorOwnerEligible(part))
      .flatMap((part) => {
        if (part.type === "fin") {
          const [rootCenter, tipCenter] = computeFinEdgeCentersLogical(part, parts);
          return [
            {
              id: `${part.id}:fin-root-center`,
              ownerId: part.id,
              outwardSign: 0,
              logical: rootCenter,
            },
            {
              id: `${part.id}:fin-tip-center`,
              ownerId: part.id,
              outwardSign: 0,
              logical: tipCenter,
            },
          ] satisfies SnapAnchor3D[];
        }
        const length = getPartLength(part);
        const y = part.position[1];
        const z = part.position[2];
        const flipped = isLongitudinalFlipped(part);
        const x1 = part.position[0];
        const x2 =
          part.type === "nose"
            ? part.position[0] + (flipped ? -length : length)
            : part.position[0] + length;
        const mid = (x1 + x2) / 2;
        return [
          {
            id: `${part.id}:face-1`,
            ownerId: part.id,
            outwardSign: x1 <= mid ? -1 : 1,
            logical: [x1, y, z] as [number, number, number],
          },
          {
            id: `${part.id}:face-2`,
            ownerId: part.id,
            outwardSign: x2 <= mid ? -1 : 1,
            logical: [x2, y, z] as [number, number, number],
          },
        ] satisfies SnapAnchor3D[];
      });
  }, [parts, viewMode]);

  const snapAnchorsById = useMemo(
    () => new Map(snapAnchors3d.map((anchor) => [anchor.id, anchor])),
    [snapAnchors3d]
  );
  const partsById = useMemo(() => new Map(parts.map((part) => [part.id, part])), [parts]);

  const handleSnapAnchorClick = useCallback(
    (clickedAnchor: SnapAnchor3D) => {
      if (!armedSnapAnchorId) {
        setArmedSnapAnchorId(clickedAnchor.id);
        return;
      }
      if (armedSnapAnchorId === clickedAnchor.id) {
        setArmedSnapAnchorId(null);
        return;
      }

      const armedAnchor = snapAnchorsById.get(armedSnapAnchorId);
      if (!armedAnchor) {
        setArmedSnapAnchorId(clickedAnchor.id);
        return;
      }

      if (armedAnchor.ownerId === clickedAnchor.ownerId) {
        // Require second click to be on a different component.
        setArmedSnapAnchorId(clickedAnchor.id);
        return;
      }

      const movingPart = parts.find((part) => part.id === clickedAnchor.ownerId);
      if (!movingPart || !isSnapAnchorOwnerEligible(movingPart)) {
        setArmedSnapAnchorId(null);
        return;
      }

      // Move clicked component by exact anchor-to-anchor delta so the
      // first-clicked anchor remains fixed and the second-clicked anchor
      // lands exactly on it, regardless of orientation/flip semantics.
      const dx = armedAnchor.logical[0] - clickedAnchor.logical[0];
      const dy = armedAnchor.logical[1] - clickedAnchor.logical[1];
      const dz = armedAnchor.logical[2] - clickedAnchor.logical[2];
      const snapped: [number, number, number] = [
        movingPart.position[0] + dx,
        movingPart.position[1] + dy,
        movingPart.position[2] + dz,
      ];
      onPositionChange(movingPart.id, snapped);
      onSelect(movingPart.id);
      setArmedSnapAnchorId(null);
    },
    [armedSnapAnchorId, onPositionChange, onSelect, parts, snapAnchorsById]
  );

  useEffect(() => {
    if (!armedSnapAnchorId) return;
    if (viewMode !== "3d" || parts.length <= 1 || !snapAnchorsById.has(armedSnapAnchorId)) {
      setArmedSnapAnchorId(null);
    }
  }, [armedSnapAnchorId, parts.length, snapAnchorsById, viewMode]);
  useEffect(() => {
    if (!armedFinRailTarget) return;
    if (
      viewMode !== "3d" ||
      !railLines3d ||
      !railLines3d.some(
        (rail) =>
          rail.key === armedFinRailTarget.railKey && rail.finId === armedFinRailTarget.finId
      )
    ) {
      setArmedFinRailTarget(null);
    }
  }, [armedFinRailTarget, railLines3d, viewMode]);

  useEffect(() => {
    const handleDown = (event: KeyboardEvent) => {
      if (event.key === "Shift") setShiftPressed(true);
    };
    const handleUp = (event: KeyboardEvent) => {
      if (event.key === "Shift") setShiftPressed(false);
    };
    window.addEventListener("keydown", handleDown);
    window.addEventListener("keyup", handleUp);
    return () => {
      window.removeEventListener("keydown", handleDown);
      window.removeEventListener("keyup", handleUp);
    };
  }, []);

  useEffect(() => {
    if (!orbitRef.current) return;
    orbitRef.current.mouseButtons.LEFT =
      viewMode === "3d"
        ? shiftPressed
          ? THREE.MOUSE.PAN
          : THREE.MOUSE.ROTATE
        : shiftPressed
          ? THREE.MOUSE.PAN
          : THREE.MOUSE.NONE;
  }, [shiftPressed, viewMode]);

  return (
    <div
      className="module-r-workspace-canvas"
      style={
        viewMode === "2d"
          ? {
              backgroundColor: "#03080b",
              backgroundImage:
                "linear-gradient(rgba(0,243,255,0.22) 1px, transparent 1px), linear-gradient(90deg, rgba(195,255,80,0.15) 1px, transparent 1px)",
              backgroundSize: "24px 24px, 24px 24px",
            }
          : undefined
      }
    >
      <Canvas
        gl={{ alpha: true, antialias: true, powerPreference: "high-performance" }}
        dpr={[1, 1.25]}
        key={sceneKey}
        onPointerMissed={() => onSelect(null)}
        orthographic={useOrtho}
        camera={
          useOrtho
            ? ({
                position: pose.position,
                zoom: pose.zoom ?? (viewMode === "2d" ? 12 : 16),
                near: 0.1,
                far: 5000,
              } as THREE.OrthographicCamera)
            : ({
                position: pose.position,
                fov: pose.fov ?? (viewMode === "2d" ? 28 : 45),
                near: 0.1,
                far: 5000,
              } as THREE.PerspectiveCamera)
        }
        onCreated={({ gl, size: canvasSize }) => {
          if (viewMode === "2d") {
            gl.setClearColor("#000000", 0);
          } else {
            gl.setClearColor("#020407", 1);
          }
          gl.domElement.addEventListener("contextmenu", (event) => event.preventDefault());
          setSize({ width: canvasSize.width, height: canvasSize.height });
        }}
      >
        <CameraRig viewMode={viewMode} cameraMode={cameraMode} pose={pose} />
        <SceneBackground viewMode={viewMode} backgroundImageUrl={backgroundImageUrl} />
        <HoverTracker viewMode={viewMode} onHoverPosition={onHoverPosition} />
        {viewMode === "3d" && null}
        <ambientLight intensity={viewMode === "3d" ? 0.28 : 0.6} />
        {viewMode === "3d" && <hemisphereLight intensity={0.55} groundColor="#2b2b2b" />}
        <directionalLight
          position={viewMode === "3d" ? [45, 70, 30] : [10, 20, 10]}
          intensity={viewMode === "3d" ? 1.35 : 0.9}
          color={viewMode === "3d" ? "#ffffff" : "#f0ffff"}
        />
        {viewMode === "3d" && (
          <directionalLight position={[-35, 22, -28]} intensity={0.55} color="#cfd8ff" />
        )}
        {viewMode === "2d" ? grid : null}
        {showFinRecommendation && (
          <group>
            {finSnapTargets.map((target) => (
              <group key={target.id}>
                <Line
                  points={[
                    new THREE.Vector3(target.x - 2, target.y, 0),
                    new THREE.Vector3(target.x + 2, target.y, 0),
                  ]}
                  color="#00f3ff"
                  lineWidth={2}
                />
                <Line
                  points={[
                    new THREE.Vector3(target.x, target.y - 2, 0),
                    new THREE.Vector3(target.x, target.y + 2, 0),
                  ]}
                  color="#00f3ff"
                  lineWidth={2}
                />
              </group>
            ))}
          </group>
        )}
        {viewMode === "3d" && parts.length > 1 && snapAnchors3d.length > 0 && (
          <group>
            {snapAnchors3d.map((anchor) => {
              const owner = partsById.get(anchor.ownerId);
              const world = toWorldPointFromLogical(getAnchorDisplayLogical(anchor, owner));
              return (
                <mesh
                  key={anchor.id}
                  position={world}
                  onPointerDown={(event) => {
                    event.stopPropagation();
                    handleSnapAnchorClick(anchor);
                  }}
                >
                  <sphereGeometry args={[1.05, 24, 24]} />
                  <meshStandardMaterial
                    color={armedSnapAnchorId === anchor.id ? "#ff3344" : "#1fb6ff"}
                    emissive={armedSnapAnchorId === anchor.id ? "#ff3344" : "#1fb6ff"}
                    emissiveIntensity={0.8}
                  />
                </mesh>
              );
            })}
          </group>
        )}
        {viewMode === "3d" && railLines3d && (
          <group>
            {railLines3d.map((rail) => (
              <group key={rail.key}>
                <Line points={[rail.startWorld, rail.endWorld]} color="#37b7ff" lineWidth={2.6} />
                <mesh
                  position={rail.midWorld}
                  onPointerDown={(event) => {
                    event.stopPropagation();
                    const x = Math.max(rail.minX, Math.min(rail.maxX, event.point.z));
                    const fin = parts.find((part) => part.id === rail.finId);
                    if (!fin || fin.type !== "fin") return;
                    const finDir = isLongitudinalFlipped(fin) ? -1 : 1;
                    const snappedX =
                      armedFinRailTarget &&
                      armedFinRailTarget.finId === rail.finId &&
                      armedFinRailTarget.railKey === rail.key
                        ? x - armedFinRailTarget.edgeOffset * finDir
                        : snapFinXByParallelEdges(fin, x);
                    onPositionChange(rail.finId, [snappedX, rail.y, rail.z]);
                    onSelect(rail.finId);
                    setArmedFinRailTarget(null);
                  }}
                >
                  <boxGeometry args={[3.6, 3.6, rail.railLength]} />
                  <meshBasicMaterial transparent opacity={0} />
                </mesh>
                {rail.balls.map((ball) => (
                  <mesh
                    key={ball.id}
                    position={ball.world}
                    onPointerDown={(event) => {
                      event.stopPropagation();
                      onSelect(rail.finId);
                      setArmedFinRailTarget({
                        ballId: ball.id,
                        railKey: rail.key,
                        finId: rail.finId,
                        edgeOffset: ball.edgeOffset,
                      });
                    }}
                  >
                    <sphereGeometry args={[1.45, 28, 28]} />
                    <meshStandardMaterial
                      color={armedFinRailTarget?.ballId === ball.id ? "#ff3344" : "#37b7ff"}
                      emissive={armedFinRailTarget?.ballId === ball.id ? "#ff3344" : "#37b7ff"}
                      emissiveIntensity={0.9}
                    />
                  </mesh>
                ))}
              </group>
            ))}
          </group>
        )}
        <OrbitControls
          ref={orbitRef}
          enableRotate={viewMode === "3d"}
          enablePan
          enableZoom
          enableDamping={viewMode === "3d"}
          dampingFactor={0.08}
          screenSpacePanning={viewMode === "2d"}
          zoomSpeed={viewMode === "2d" ? 1.2 : 0.9}
          panSpeed={viewMode === "2d" ? 1.3 : 0.9}
          rotateSpeed={0.75}
          minPolarAngle={viewMode === "2d" ? Math.PI / 2 : 0}
          maxPolarAngle={viewMode === "2d" ? Math.PI / 2 : Math.PI}
          mouseButtons={{
            LEFT:
              viewMode === "3d"
                ? shiftPressed
                  ? THREE.MOUSE.PAN
                  : THREE.MOUSE.ROTATE
                : shiftPressed
                  ? THREE.MOUSE.PAN
                  : THREE.MOUSE.NONE,
            MIDDLE: viewMode === "3d" ? THREE.MOUSE.ROTATE : THREE.MOUSE.NONE,
            RIGHT: viewMode === "3d" ? THREE.MOUSE.PAN : THREE.MOUSE.NONE,
          }}
          onEnd={(event) => {
            const controls = event.target as unknown as {
              object: THREE.Camera;
              target: THREE.Vector3;
            };
            const cam = controls.object;
            const target = controls.target;
            const isOrtho = (cam as THREE.OrthographicCamera).isOrthographicCamera;
            const nextPose: CameraPose = {
              position: [cam.position.x, cam.position.y, cam.position.z],
              target: [target.x, target.y, target.z],
              zoom: isOrtho ? (cam as THREE.OrthographicCamera).zoom : undefined,
              fov: !isOrtho ? (cam as THREE.PerspectiveCamera).fov : undefined,
            };
            setCameraPoses((prev) => ({ ...prev, [sceneKey]: nextPose }));
          }}
          enabled={!isDragging2d && !isDragging3d}
        />

        {parts.map((part) =>
          viewMode === "2d" ? (
            <PartInstance2D
              key={part.id}
              part={part}
              allParts={parts}
              selected={part.id === selectedId}
              onSelect={() => onSelect(part.id)}
              onPositionChange={(position) => onPositionChange(part.id, position)}
              onDragState={setIsDragging2d}
              finSnapTargets={finSnapTargets}
              shiftPressed={shiftPressed}
            />
          ) : (
            <PartInstance3D
              key={part.id}
              part={part}
              allParts={parts}
              selected={part.id === selectedId}
              onSelect={() => onSelect(part.id)}
              onPositionChange={(position) => onPositionChange(part.id, position)}
              onDragState={setIsDragging3d}
              shiftPressed={shiftPressed}
            />
          )
        )}
      </Canvas>
    </div>
  );
};
