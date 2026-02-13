import * as THREE from "three";

export type NoseConeType = "OGIVE" | "PARABOLIC" | "CONICAL" | "ELLIPTICAL";

export const toNumber = (value?: string | null) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
};

export const generateNoseConePoints = (
  type: NoseConeType,
  length: number,
  radius: number,
  segments = 48
) => {
  const pts: THREE.Vector2[] = [];
  for (let i = 0; i <= segments; i += 1) {
    const x = (i / segments) * length;
    const t = length > 0 ? x / length : 0;
    let r = radius;

    switch (type) {
      case "CONICAL":
        r = radius * t;
        break;
      case "ELLIPTICAL":
        r =
          radius *
          Math.sqrt(Math.max(0, 1 - Math.pow((length - x) / Math.max(length, 1), 2)));
        break;
      case "PARABOLIC":
        r = radius * Math.sqrt(Math.max(0, t));
        break;
      case "OGIVE":
      default: {
        const rho = (radius * radius + length * length) / Math.max(2 * radius, 1e-4);
        r =
          Math.sqrt(Math.max(0, rho * rho - Math.pow(length - x, 2))) -
          (rho - radius);
        break;
      }
    }

    pts.push(new THREE.Vector2(r, x));
  }

  return pts;
};

export const generateFinShape = (
  rootChord: number,
  tipChord: number,
  span: number,
  sweep: number
) => {
  return [
    new THREE.Vector2(0, 0),
    new THREE.Vector2(rootChord, 0),
    new THREE.Vector2(sweep + tipChord, span),
    new THREE.Vector2(sweep, span),
  ];
};
