export type PartType =
  | "body"
  | "nose"
  | "fin"
  | "inner"
  | "parachute"
  | "mass"
  | "telemetry";

export interface RocketPartParams {
  manualOverrideMass?: number;
  isOverrideActive?: boolean;
  logicalHitboxScale?: number;
  manual_override_mass?: number;
  manual_override_mass_lb?: number;
  is_override_active?: boolean;
  logical_hitbox_scale?: number;
  parentType?: string;
  [key: string]: number | string | boolean | undefined;
}

export interface RocketPartData {
  id: string;
  type: PartType;
  label: string;
  params: RocketPartParams;
  internal?: boolean;
}

export interface AssemblyPart extends RocketPartData {
  position: [number, number, number];
  rotation: [number, number, number];
  flipX?: boolean;
  flipY?: boolean;
  flipZ?: boolean;
  finOffsets?: Array<[number, number]>;
  finPlaced?: boolean;
}
