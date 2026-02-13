const textureAssets = import.meta.glob("./textures/**/*.{png,jpg,jpeg,webp,avif}", {
  eager: true,
  import: "default",
}) as Record<string, string>;

const textureUrl = (path: string) => {
  const normalized = path.startsWith("./") ? path : `./${path}`;
  return textureAssets[normalized] || normalized;
};

export type MaterialEntry = {
  type: "color" | "metal" | "texture";
  value: string;
  color?: string;
  roughness?: number;
  metalness?: number;
  opacity?: number;
  transparent?: boolean;
  map?: string;
  normalMap?: string;
  roughnessMap?: string;
  metalnessMap?: string;
  aoMap?: string;
  repeat?: [number, number];
  density_kg_m3?: number;
};

export const MATERIAL_DB: Record<string, MaterialEntry> = {
  // --- WOODS (Render as Solid Colors) ---
  Balsa: { type: "color", value: "#FFE4C4", roughness: 0.8, density_kg_m3: 160 },
  Basswood: { type: "color", value: "#F5F5DC", roughness: 0.8, density_kg_m3: 500 },
  "Plywood (Birch)": {
    type: "color",
    value: "#DEB887",
    roughness: 0.9,
    density_kg_m3: 600,
  },
  Spruce: { type: "color", value: "#D2B48C", roughness: 0.8, density_kg_m3: 450 },
  MDF: { type: "color", value: "#8B4513", roughness: 0.9, density_kg_m3: 700 },

  // --- PLASTICS (Texture Based) ---
  ABS: {
    type: "texture",
    value: "plastic",
    color: "#1C1C1C",
    roughness: 0.4,
    map: textureUrl("./textures/Plastic001/Plastic001_1K-PNG_Color.png"),
    normalMap: textureUrl("./textures/Plastic001/Plastic001_1K-PNG_NormalGL.png"),
    roughnessMap: textureUrl("./textures/Plastic001/Plastic001_1K-PNG_Roughness.png"),
    repeat: [2, 2],
    density_kg_m3: 1040,
  },
  PLA: {
    type: "texture",
    value: "plastic",
    color: "#FF4500",
    roughness: 0.5,
    map: textureUrl("./textures/Plastic002/Plastic002_1K-PNG_Color.png"),
    normalMap: textureUrl("./textures/Plastic002/Plastic002_1K-PNG_NormalGL.png"),
    roughnessMap: textureUrl("./textures/Plastic002/Plastic002_1K-PNG_Roughness.png"),
    repeat: [2, 2],
    density_kg_m3: 1240,
  },
  PVC: {
    type: "texture",
    value: "plastic",
    color: "#F5F5F5",
    roughness: 0.3,
    map: textureUrl("./textures/Plastic003/Plastic003_1K-PNG_Color.png"),
    normalMap: textureUrl("./textures/Plastic003/Plastic003_1K-PNG_NormalGL.png"),
    roughnessMap: textureUrl("./textures/Plastic003/Plastic003_1K-PNG_Roughness.png"),
    repeat: [2, 2],
    density_kg_m3: 1400,
  },
  Polycarbonate: {
    type: "texture",
    value: "plastic",
    color: "#A0E0FF",
    roughness: 0.1,
    opacity: 0.6,
    transparent: true,
    map: textureUrl("./textures/Plastic004/Plastic004_1K-PNG_Color.png"),
    normalMap: textureUrl("./textures/Plastic004/Plastic004_1K-PNG_NormalGL.png"),
    roughnessMap: textureUrl("./textures/Plastic004/Plastic004_1K-PNG_Roughness.png"),
    repeat: [2, 2],
    density_kg_m3: 1200,
  },
  Polystyrene: {
    type: "texture",
    value: "plastic",
    color: "#E0E0E0",
    roughness: 0.5,
    map: textureUrl("./textures/Plastic005/Plastic005_1K-PNG_Color.png"),
    normalMap: textureUrl("./textures/Plastic005/Plastic005_1K-PNG_NormalGL.png"),
    roughnessMap: textureUrl("./textures/Plastic005/Plastic005_1K-PNG_Roughness.png"),
    repeat: [2, 2],
    density_kg_m3: 1050,
  },
  Polyethylene: {
    type: "texture",
    value: "plastic",
    color: "#ECECEC",
    roughness: 0.45,
    map: textureUrl("./textures/Plastic006/Plastic006_1K-PNG_Color.png"),
    normalMap: textureUrl("./textures/Plastic006/Plastic006_1K-PNG_NormalGL.png"),
    roughnessMap: textureUrl("./textures/Plastic006/Plastic006_1K-PNG_Roughness.png"),
    repeat: [2, 2],
    density_kg_m3: 950,
  },
  Nylon: {
    type: "texture",
    value: "plastic",
    color: "#FDF5E6",
    roughness: 0.4,
    map: textureUrl("./textures/Plastic007/Plastic007_1K-PNG_Color.png"),
    normalMap: textureUrl("./textures/Plastic007/Plastic007_1K-PNG_NormalGL.png"),
    roughnessMap: textureUrl("./textures/Plastic007/Plastic007_1K-PNG_Roughness.png"),
    repeat: [2, 2],
    density_kg_m3: 1150,
  },
  Delrin: {
    type: "texture",
    value: "plastic",
    color: "#FFFFFF",
    roughness: 0.3,
    map: textureUrl("./textures/Plastic008/Plastic008_1K-PNG_Color.png"),
    normalMap: textureUrl("./textures/Plastic008/Plastic008_1K-PNG_NormalGL.png"),
    roughnessMap: textureUrl("./textures/Plastic008/Plastic008_1K-PNG_Roughness.png"),
    repeat: [2, 2],
    density_kg_m3: 1410,
  },
  Teflon: {
    type: "texture",
    value: "plastic",
    color: "#F8F8FF",
    roughness: 0.2,
    map: textureUrl("./textures/Plastic009/Plastic009_1K-PNG_Color.png"),
    normalMap: textureUrl("./textures/Plastic009/Plastic009_1K-PNG_NormalGL.png"),
    roughnessMap: textureUrl("./textures/Plastic009/Plastic009_1K-PNG_Roughness.png"),
    repeat: [2, 2],
    density_kg_m3: 2200,
  },

  // --- METALS (PBR Physics) ---
  Aluminum: {
    type: "metal",
    value: "aluminum",
    metalness: 1.0,
    roughness: 0.3,
    color: "#C0C0C0",
    map: textureUrl("./textures/Metal006/Metal006_1K-PNG_Color.png"),
    normalMap: textureUrl("./textures/Metal006/Metal006_1K-PNG_NormalGL.png"),
    roughnessMap: textureUrl("./textures/Metal006/Metal006_1K-PNG_Roughness.png"),
    metalnessMap: textureUrl("./textures/Metal006/Metal006_1K-PNG_Metalness.png"),
    repeat: [1, 1],
    density_kg_m3: 2700,
  },
  "Aluminum 6061-T6": {
    type: "metal",
    value: "aluminum",
    metalness: 1.0,
    roughness: 0.25,
    color: "#C8C8C8",
    map: textureUrl("./textures/Metal006/Metal006_1K-PNG_Color.png"),
    normalMap: textureUrl("./textures/Metal006/Metal006_1K-PNG_NormalGL.png"),
    roughnessMap: textureUrl("./textures/Metal006/Metal006_1K-PNG_Roughness.png"),
    metalnessMap: textureUrl("./textures/Metal006/Metal006_1K-PNG_Metalness.png"),
    repeat: [1, 1],
    density_kg_m3: 2700,
  },
  Titanium: {
    type: "metal",
    value: "titanium",
    metalness: 1.0,
    roughness: 0.4,
    color: "#A9A9A9",
    map: textureUrl("./textures/Metal012/Metal012_1K-PNG_Color.png"),
    normalMap: textureUrl("./textures/Metal012/Metal012_1K-PNG_NormalGL.png"),
    roughnessMap: textureUrl("./textures/Metal012/Metal012_1K-PNG_Roughness.png"),
    metalnessMap: textureUrl("./textures/Metal012/Metal012_1K-PNG_Metalness.png"),
    repeat: [1, 1],
    density_kg_m3: 4500,
  },
  "Steel (Stainless)": {
    type: "metal",
    value: "steel",
    metalness: 1.0,
    roughness: 0.35,
    color: "#778899",
    map: textureUrl("./textures/Metal009/Metal009_1K-PNG_Color.png"),
    normalMap: textureUrl("./textures/Metal009/Metal009_1K-PNG_NormalGL.png"),
    roughnessMap: textureUrl("./textures/Metal009/Metal009_1K-PNG_Roughness.png"),
    metalnessMap: textureUrl("./textures/Metal009/Metal009_1K-PNG_Metalness.png"),
    repeat: [1, 1],
    density_kg_m3: 8000,
  },
  "Steel (Mild)": {
    type: "metal",
    value: "steel",
    metalness: 1.0,
    roughness: 0.55,
    color: "#6D7C86",
    map: textureUrl("./textures/Metal001/Metal001_1K-PNG_Color.png"),
    normalMap: textureUrl("./textures/Metal001/Metal001_1K-PNG_NormalGL.png"),
    roughnessMap: textureUrl("./textures/Metal001/Metal001_1K-PNG_Roughness.png"),
    metalnessMap: textureUrl("./textures/Metal001/Metal001_1K-PNG_Metalness.png"),
    repeat: [1, 1],
    density_kg_m3: 7850,
  },
  Brass: {
    type: "metal",
    value: "brass",
    metalness: 1.0,
    roughness: 0.2,
    color: "#B5A642",
    map: textureUrl("./textures/Metal008/Metal008_1K-PNG_Color.png"),
    normalMap: textureUrl("./textures/Metal008/Metal008_1K-PNG_NormalGL.png"),
    roughnessMap: textureUrl("./textures/Metal008/Metal008_1K-PNG_Roughness.png"),
    metalnessMap: textureUrl("./textures/Metal008/Metal008_1K-PNG_Metalness.png"),
    repeat: [1, 1],
    density_kg_m3: 8500,
  },
  Copper: {
    type: "metal",
    value: "copper",
    metalness: 1.0,
    roughness: 0.3,
    color: "#B87333",
    map: textureUrl("./textures/Metal013/Metal013_1K-PNG_Color.png"),
    normalMap: textureUrl("./textures/Metal013/Metal013_1K-PNG_NormalGL.png"),
    roughnessMap: textureUrl("./textures/Metal013/Metal013_1K-PNG_Roughness.png"),
    metalnessMap: textureUrl("./textures/Metal013/Metal013_1K-PNG_Metalness.png"),
    repeat: [1, 1],
    density_kg_m3: 8960,
  },

  // --- COMPOSITES (Texture Based) ---
  "Carbon Fiber": {
    type: "texture",
    value: "carbon_fiber",
    color: "#111111",
    roughness: 0.3,
    map: textureUrl("./textures/Fabric004/Fabric004_1K-PNG_Color.png"),
    normalMap: textureUrl("./textures/Fabric004/Fabric004_1K-PNG_NormalGL.png"),
    roughnessMap: textureUrl("./textures/Fabric004/Fabric004_1K-PNG_Roughness.png"),
    metalnessMap: textureUrl("./textures/Fabric004/Fabric004_1K-PNG_Metalness.png"),
    repeat: [2, 2],
    density_kg_m3: 1600,
  },
  Fiberglass: {
    type: "texture",
    value: "fiberglass",
    color: "#C7D0C8",
    roughness: 0.45,
    opacity: 1.0,
    transparent: false,
    map: textureUrl("./textures/Fabric030/Fabric030_1K-PNG_Color.png"),
    normalMap: textureUrl("./textures/Fabric030/Fabric030_1K-PNG_NormalGL.png"),
    roughnessMap: textureUrl("./textures/Fabric030/Fabric030_1K-PNG_Roughness.png"),
    aoMap: textureUrl("./textures/Fabric030/Fabric030_1K-PNG_AmbientOcclusion.png"),
    repeat: [2, 2],
    density_kg_m3: 1850,
  },
  "Aramid Fiber": {
    type: "texture",
    value: "aramid",
    color: "#C2A875",
    roughness: 0.45,
    map: textureUrl("./textures/Fabric056/Fabric056_1K-PNG_Color.png"),
    normalMap: textureUrl("./textures/Fabric056/Fabric056_1K-PNG_NormalGL.png"),
    roughnessMap: textureUrl("./textures/Fabric056/Fabric056_1K-PNG_Roughness.png"),
    repeat: [2, 2],
    density_kg_m3: 1440,
  },
  Phenolic: {
    type: "texture",
    value: "phenolic",
    color: "#6E4A2E",
    roughness: 0.85,
    map: textureUrl("./textures/Paper006/Paper006_1K-JPG_Color.jpg"),
    normalMap: textureUrl("./textures/Paper006/Paper006_1K-JPG_NormalGL.jpg"),
    roughnessMap: textureUrl("./textures/Paper006/Paper006_1K-JPG_Roughness.jpg"),
    repeat: [2, 2],
    density_kg_m3: 1350,
  },

  // --- PAPER (Texture/Color Hybrid) ---
  Cardboard: {
    type: "texture",
    value: "cardboard",
    color: "#8D6F55",
    roughness: 1.0,
    map: textureUrl("./textures/Cardboard004/Cardboard004_1K-PNG_Color.png"),
    normalMap: textureUrl("./textures/Cardboard004/Cardboard004_1K-PNG_NormalGL.png"),
    roughnessMap: textureUrl("./textures/Cardboard004/Cardboard004_1K-PNG_Roughness.png"),
    repeat: [2, 2],
    density_kg_m3: 700,
  },
  "Kraft Paper": {
    type: "texture",
    value: "paper",
    color: "#D2691E",
    roughness: 1.0,
    map: textureUrl("./textures/Paper002/Paper002_1K-JPG_Color.jpg"),
    normalMap: textureUrl("./textures/Paper002/Paper002_1K-JPG_NormalGL.jpg"),
    roughnessMap: textureUrl("./textures/Paper002/Paper002_1K-JPG_Roughness.jpg"),
    repeat: [2, 2],
    density_kg_m3: 800,
  },
  "Hard Paper": {
    type: "texture",
    value: "paper",
    color: "#B7844A",
    roughness: 0.9,
    map: textureUrl("./textures/Paper004/Paper004_1K-JPG_Color.jpg"),
    normalMap: textureUrl("./textures/Paper004/Paper004_1K-JPG_NormalGL.jpg"),
    roughnessMap: textureUrl("./textures/Paper004/Paper004_1K-JPG_Roughness.jpg"),
    repeat: [2, 2],
    density_kg_m3: 900,
  },
  // Common UI aliases kept for backward compatibility with older forms/storage payloads.
  Plywood: {
    type: "color",
    value: "#DEB887",
    roughness: 0.9,
    density_kg_m3: 600,
  },
  Plastic: {
    type: "texture",
    value: "plastic",
    color: "#1C1C1C",
    roughness: 0.4,
    map: textureUrl("./textures/Plastic001/Plastic001_1K-PNG_Color.png"),
    normalMap: textureUrl("./textures/Plastic001/Plastic001_1K-PNG_NormalGL.png"),
    roughnessMap: textureUrl("./textures/Plastic001/Plastic001_1K-PNG_Roughness.png"),
    repeat: [2, 2],
    density_kg_m3: 1040,
  },
  Steel: {
    type: "metal",
    value: "steel",
    metalness: 1.0,
    roughness: 0.45,
    color: "#778899",
    map: textureUrl("./textures/Metal009/Metal009_1K-PNG_Color.png"),
    normalMap: textureUrl("./textures/Metal009/Metal009_1K-PNG_NormalGL.png"),
    roughnessMap: textureUrl("./textures/Metal009/Metal009_1K-PNG_Roughness.png"),
    metalnessMap: textureUrl("./textures/Metal009/Metal009_1K-PNG_Metalness.png"),
    repeat: [1, 1],
    density_kg_m3: 8000,
  },
} as const;

const familyDefaults: Record<string, MaterialEntry> = {
  metal: MATERIAL_DB.Aluminum,
  composite: MATERIAL_DB["Carbon Fiber"],
  plastic: MATERIAL_DB.ABS,
  wood: MATERIAL_DB.Balsa,
  paper: MATERIAL_DB.Cardboard,
};

export const resolveCustomMaterialVisual = (name?: string | null): MaterialEntry => {
  if (!name) return MATERIAL_DB.Aluminum;
  const normalized = name.toLowerCase();
  if (MATERIAL_DB[name]) return MATERIAL_DB[name];
  if (/(carbon|fiber|glass|fiberglass)/.test(normalized)) return familyDefaults.composite;
  if (/(aluminum|aluminium|steel|titanium|brass|copper|metal)/.test(normalized))
    return familyDefaults.metal;
  if (/(pla|abs|pvc|poly|nylon|delrin|teflon|plastic)/.test(normalized))
    return familyDefaults.plastic;
  if (/(balsa|wood|spruce|plywood|mdf|basswood)/.test(normalized))
    return familyDefaults.wood;
  if (/(paper|cardboard|kraft|phenolic)/.test(normalized)) return familyDefaults.paper;
  return familyDefaults.metal;
};
