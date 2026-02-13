import React, { useMemo } from "react";
import * as THREE from "three";
import { useTexture } from "@react-three/drei";
import { generateFinShape, generateNoseConePoints, NoseConeType } from "./geometryUtils";
import { MATERIAL_DB, MaterialEntry, resolveCustomMaterialVisual } from "./materials";
import { RocketPartData } from "./types";

const AXIS_ROTATION: [number, number, number] = [Math.PI / 2, 0, 0];

const buildLathe = (points: THREE.Vector2[]) =>
  new THREE.LatheGeometry(points, 48);

const buildFin = (root: number, tip: number, span: number, sweep: number, thickness: number) => {
  const shape = new THREE.Shape(generateFinShape(root, tip, span, sweep));
  const geometry = new THREE.ExtrudeGeometry(shape, { depth: thickness, bevelEnabled: false });
  // Center thickness around local Z=0 so radial placement stays visually stable.
  geometry.translate(0, 0, -thickness / 2);
  return geometry;
};

const buildEllipticalFin = (root: number, span: number, thickness: number) => {
  const rx = Math.max(root * 0.5, 0.1);
  const ry = Math.max(span * 0.5, 0.1);
  const shape = new THREE.Shape();
  shape.absellipse(rx, ry, rx, ry, Math.PI, Math.PI * 2, false, 0);
  const geometry = new THREE.ExtrudeGeometry(shape, { depth: thickness, bevelEnabled: false });
  geometry.translate(-rx, -ry, -thickness / 2);
  return geometry;
};

const buildFreeFormFin = (
  root: number,
  tip: number,
  span: number,
  sweep: number,
  thickness: number
) => {
  const shape = new THREE.Shape();
  shape.moveTo(0, 0);
  shape.lineTo(root, 0);
  shape.quadraticCurveTo(root * 0.75, span * 0.55, sweep + tip, span);
  shape.quadraticCurveTo(sweep * 0.45, span * 0.85, 0, span * 0.6);
  shape.lineTo(0, 0);
  const geometry = new THREE.ExtrudeGeometry(shape, { depth: thickness, bevelEnabled: false });
  geometry.translate(0, 0, -thickness / 2);
  return geometry;
};

const buildTubeFin = (length: number, outerDiameter: number, innerDiameter: number) => {
  const outerRadius = Math.max(outerDiameter * 0.5, 0.05);
  const innerRadius = Math.max(0, Math.min(innerDiameter * 0.5, outerRadius - 0.01));
  const shape = new THREE.Shape();
  shape.absarc(0, 0, outerRadius, 0, Math.PI * 2, false);
  if (innerRadius > 0.001) {
    const hole = new THREE.Path();
    hole.absarc(0, 0, innerRadius, 0, Math.PI * 2, true);
    shape.holes.push(hole);
  }
  const geometry = new THREE.ExtrudeGeometry(shape, {
    depth: Math.max(length, 0.05),
    bevelEnabled: false,
  });
  geometry.rotateY(Math.PI / 2);
  geometry.translate(0, 0, -Math.max(length, 0.05) / 2);
  return geometry;
};

const parseFreeformPoints = (raw: unknown): Array<{ x: number; y: number }> | null => {
  if (typeof raw !== "string" || !raw.trim()) return null;
  try {
    const parsed = JSON.parse(raw) as Array<{ x?: unknown; y?: unknown }>;
    if (!Array.isArray(parsed)) return null;
    const points = parsed
      .map((p) => ({ x: Number(p?.x), y: Number(p?.y) }))
      .filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y));
    return points.length >= 3 ? points : null;
  } catch {
    return null;
  }
};

const buildFreeFormFinFromPoints = (points: Array<{ x: number; y: number }>, thickness: number) => {
  const shape = new THREE.Shape();
  shape.moveTo(points[0].x, points[0].y);
  points.slice(1).forEach((p) => shape.lineTo(p.x, p.y));
  shape.lineTo(points[0].x, points[0].y);
  const geometry = new THREE.ExtrudeGeometry(shape, { depth: thickness, bevelEnabled: false });
  geometry.translate(0, 0, -thickness / 2);
  return geometry;
};

const applyTextureSettings = (
  texture?: THREE.Texture,
  repeat?: [number, number],
  isColorMap = false
) => {
  if (!texture) return;
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  if (isColorMap) texture.colorSpace = THREE.SRGBColorSpace;
  if (repeat) texture.repeat.set(repeat[0], repeat[1]);
  texture.needsUpdate = true;
};

const ensureUv2 = (geometry: THREE.BufferGeometry) => {
  const uv = geometry.getAttribute("uv");
  if (uv && !geometry.getAttribute("uv2")) {
    geometry.setAttribute("uv2", uv);
  }
  return geometry;
};

const ColorMaterial: React.FC<{
  entry: MaterialEntry;
  internal?: boolean;
  flipX?: boolean;
  flipY?: boolean;
}> = ({ entry, internal }) => {
  const transparent = Boolean(entry.transparent ?? internal);
  return (
    <meshStandardMaterial
      color={entry.value}
      metalness={0}
      roughness={entry.roughness ?? 0.7}
      transparent={transparent}
      opacity={entry.opacity ?? (internal ? 0.45 : 1)}
      wireframe={Boolean(internal && entry.opacity === undefined)}
      side={transparent ? THREE.DoubleSide : THREE.FrontSide}
      depthWrite={!transparent}
      alphaTest={transparent ? 0.02 : 0}
    />
  );
};

const TextureMaterial: React.FC<{
  entry: MaterialEntry;
  internal?: boolean;
  flipX?: boolean;
  flipY?: boolean;
}> = ({ entry, internal, flipX, flipY }) => {
  const textureUrls = useMemo(() => {
    const urls: Record<string, string> = {};
    if (entry.map) urls.map = entry.map;
    if (entry.normalMap) urls.normalMap = entry.normalMap;
    if (entry.roughnessMap) urls.roughnessMap = entry.roughnessMap;
    if (entry.metalnessMap) urls.metalnessMap = entry.metalnessMap;
    if (entry.aoMap) urls.aoMap = entry.aoMap;
    return urls;
  }, [entry]);

  const textures = useTexture(textureUrls);

  useMemo(() => {
    applyTextureSettings(textures.map, entry.repeat, true);
    applyTextureSettings(textures.normalMap, entry.repeat);
    applyTextureSettings(textures.roughnessMap, entry.repeat);
    applyTextureSettings(textures.metalnessMap, entry.repeat);
    applyTextureSettings(textures.aoMap, entry.repeat);
  }, [textures, entry.repeat]);

  const transparent = Boolean(entry.transparent ?? internal);
  return (
    <meshStandardMaterial
      color={entry.color}
      map={textures.map}
      normalMap={textures.normalMap}
      roughnessMap={textures.roughnessMap}
      metalnessMap={textures.metalnessMap}
      aoMap={textures.aoMap}
      metalness={entry.metalness ?? 0.2}
      roughness={entry.roughness ?? 0.5}
      transparent={transparent}
      opacity={entry.opacity ?? (internal ? 0.45 : 1)}
      wireframe={Boolean(internal && entry.opacity === undefined)}
      side={transparent ? THREE.DoubleSide : THREE.FrontSide}
      depthWrite={!transparent}
      alphaTest={transparent ? 0.02 : 0}
      normalScale={
        textures.normalMap
          ? new THREE.Vector2(flipX ? -1 : 1, flipY ? -1 : 1)
          : undefined
      }
    />
  );
};

const RocketMaterial: React.FC<{
  entry: MaterialEntry;
  internal?: boolean;
  flipX?: boolean;
  flipY?: boolean;
}> = ({ entry, internal, flipX, flipY }) => {
  if (entry.type === "color") {
    return <ColorMaterial entry={entry} internal={internal} flipX={flipX} flipY={flipY} />;
  }
  return <TextureMaterial entry={entry} internal={internal} flipX={flipX} flipY={flipY} />;
};

export const RocketPart: React.FC<{
  part: RocketPartData;
  flipX?: boolean;
  flipY?: boolean;
}> = ({ part, flipX, flipY }) => {
  const { type, params, internal } = part;
  const radius = Number(params.radius ?? 0.5);
  const length = Number(params.length ?? 1);
  const materialName = String(params.material ?? "");
  const materialEntry =
    (materialName && MATERIAL_DB[materialName as keyof typeof MATERIAL_DB]) ||
    resolveCustomMaterialVisual(materialName);
  const bodyGeometry = useMemo(
    () => ensureUv2(new THREE.CylinderGeometry(radius, radius, length, 48)),
    [radius, length]
  );
  const noseGeometry = useMemo(() => {
    const profile = String(params.profile ?? "OGIVE") as NoseConeType;
    const points = generateNoseConePoints(profile, length, radius);
    return ensureUv2(buildLathe(points));
  }, [params.profile, length, radius]);
  const finGeometry = useMemo(() => {
    const finType = String(params.fin_type ?? "trapezoidal").toLowerCase();
    const root = Number(params.root ?? 1);
    const tip = Number(params.tip ?? 0.5);
    const span = Number(params.span ?? 0.5);
    const sweep = Number(params.sweep ?? 0);
    const rawThickness = Number(params.thickness ?? 0.08);
    const thickness = Math.max(0.02, Math.min(rawThickness, Math.max(span * 0.2, 0.06)));
    const freePoints = parseFreeformPoints(params.free_points);
    if (finType === "elliptical") return ensureUv2(buildEllipticalFin(root, span, thickness));
    if ((finType === "free_form" || finType === "free form") && freePoints)
      return ensureUv2(buildFreeFormFinFromPoints(freePoints, thickness));
    if (finType === "free_form" || finType === "free form")
      return ensureUv2(buildFreeFormFin(root, tip, span, sweep, thickness));
    return ensureUv2(buildFin(root, tip, span, sweep, thickness));
  }, [
    params.fin_type,
    params.root,
    params.tip,
    params.span,
    params.sweep,
    params.thickness,
    params.free_points,
  ]);
  const tubeFinGeometry = useMemo(() => {
    const lengthIn = Number(params.tube_length ?? params.root ?? 4);
    const outerIn = Number(params.tube_outer_diameter ?? params.span ?? 2);
    const innerIn = Number(params.tube_inner_diameter ?? Math.max(outerIn - 0.2, 0));
    return ensureUv2(buildTubeFin(lengthIn, outerIn, innerIn));
  }, [params.tube_length, params.root, params.tube_outer_diameter, params.span, params.tube_inner_diameter]);
  const defaultGeometry = useMemo(
    () => ensureUv2(new THREE.CylinderGeometry(radius * 0.7, radius * 0.7, length, 24)),
    [radius, length]
  );

  if (type === "body") {
    return (
      <mesh geometry={bodyGeometry}>
        <RocketMaterial entry={materialEntry} internal={internal} flipX={flipX} flipY={flipY} />
      </mesh>
    );
  }

  if (type === "nose") {
    return (
      <mesh geometry={noseGeometry}>
        <RocketMaterial entry={materialEntry} internal={internal} flipX={flipX} flipY={flipY} />
      </mesh>
    );
  }

  if (type === "fin") {
    const finType = String(params.fin_type ?? "trapezoidal").toLowerCase();
    const bodyRadius = Number(params.radius ?? 0.5);
    const finCount = Math.max(1, Number(params.fin_count ?? params.count ?? 1));
    const rawThickness = Number(params.thickness ?? 0.08);
    const radialInset = Math.max(rawThickness * 0.5, bodyRadius * 0.025);
    if (finType === "tube_fin") {
      const outerDiameter = Number(params.tube_outer_diameter ?? params.span ?? 2);
      const outerRadius = Math.max(outerDiameter * 0.5, 0.05);
      const ringRadius = Math.max(bodyRadius + outerRadius - Math.max(rawThickness * 0.2, 0.01), 0);
      const tubeMesh = (
        <mesh geometry={tubeFinGeometry} position={[ringRadius, 0, 0]}>
          <RocketMaterial entry={materialEntry} internal={internal} flipX={flipX} flipY={flipY} />
        </mesh>
      );
      if (finCount === 1) return tubeMesh;
      return (
        <group>
          {Array.from({ length: finCount }).map((_, idx) => (
            <group key={idx} rotation={[0, ((Math.PI * 2) / finCount) * idx, 0]}>
              {tubeMesh}
            </group>
          ))}
        </group>
      );
    }
    const finMesh = (
      <mesh
        geometry={finGeometry}
        // Canonical fin frame:
        // - root chord aligned with rocket longitudinal axis
        // - span projects radially from body surface
        // This matches OpenRocket-like finset semantics.
        rotation={[0, 0, -Math.PI / 2]}
        position={[Math.max(bodyRadius - radialInset, 0), 0, 0]}
      >
        <RocketMaterial entry={materialEntry} internal={internal} flipX={flipX} flipY={flipY} />
      </mesh>
    );
    if (finCount === 1) {
      return finMesh;
    }
    return (
      <group>
        {Array.from({ length: finCount }).map((_, idx) => (
          <group key={idx} rotation={[0, ((Math.PI * 2) / finCount) * idx, 0]}>
            {finMesh}
          </group>
        ))}
      </group>
    );
  }

  return (
    <mesh geometry={defaultGeometry}>
      <RocketMaterial entry={materialEntry} internal={internal} flipX={flipX} flipY={flipY} />
    </mesh>
  );
};

export const RocketPartGroup: React.FC<{
  part: RocketPartData;
  flipX?: boolean;
  flipY?: boolean;
}> = ({ part, flipX, flipY }) => (
  <group rotation={AXIS_ROTATION}>
    <RocketPart part={part} flipX={flipX} flipY={flipY} />
  </group>
);
