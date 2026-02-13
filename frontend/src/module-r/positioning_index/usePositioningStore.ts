import { create } from "zustand";
import { AssemblyPart, RocketPartData } from "./types";

const POSITIONING_PERSIST_KEY = "arx_module_r_positioning_state";

const loadPersistedState = (): Pick<
  PositioningState,
  "assembly" | "history" | "lastDropPosition" | "selectedId"
> => {
  try {
    const raw = window.localStorage.getItem(POSITIONING_PERSIST_KEY);
    if (!raw) {
      return {
        assembly: [],
        history: [],
        lastDropPosition: [0, 0, 0],
        selectedId: null,
      };
    }
    const parsed = JSON.parse(raw) as {
      assembly?: AssemblyPart[];
      history?: AssemblyPart[];
      lastDropPosition?: [number, number, number];
      selectedId?: string | null;
    };
    const validDrop =
      Array.isArray(parsed.lastDropPosition) &&
      parsed.lastDropPosition.length === 3 &&
      parsed.lastDropPosition.every((v) => Number.isFinite(Number(v)))
        ? (parsed.lastDropPosition as [number, number, number])
        : [0, 0, 0];
    return {
      assembly: Array.isArray(parsed.assembly) ? parsed.assembly : [],
      history: Array.isArray(parsed.history) ? parsed.history : [],
      lastDropPosition: validDrop,
      selectedId: typeof parsed.selectedId === "string" ? parsed.selectedId : null,
    };
  } catch {
    return {
      assembly: [],
      history: [],
      lastDropPosition: [0, 0, 0],
      selectedId: null,
    };
  }
};

const persistState = (
  state: Pick<PositioningState, "assembly" | "history" | "lastDropPosition" | "selectedId">
) => {
  try {
    window.localStorage.setItem(POSITIONING_PERSIST_KEY, JSON.stringify(state));
  } catch {
    // Ignore storage write failures; runtime state still works.
  }
};

interface PositioningState {
  availableParts: RocketPartData[];
  assembly: AssemblyPart[];
  history: AssemblyPart[];
  lastDropPosition: [number, number, number];
  selectedId: string | null;
  setAvailableParts: (parts: RocketPartData[]) => void;
  syncAssemblyFromCatalog: (parts: RocketPartData[]) => void;
  addToAssembly: (part: RocketPartData, position?: [number, number, number]) => void;
  setLastDropPosition: (position: [number, number, number]) => void;
  updatePartPosition: (id: string, position: [number, number, number]) => void;
  selectPart: (id: string | null) => void;
  clearAssembly: () => void;
  undoLast: () => void;
  flipPart: (id: string, axis: "x" | "y" | "z") => void;
  setFinPlaced: (id: string) => void;
  updateFinOffset: (id: string, index: number, offset: [number, number]) => void;
}

const resolveParentBodyId = (rawParent: unknown): string => {
  const parent = String(rawParent ?? "");
  if (!parent) return "";
  if (parent.startsWith("body-")) return parent;
  if (parent.startsWith("stage-")) return parent.replace("stage-", "body-");
  if (parent.startsWith("additional-")) {
    const parts = parent.split("-");
    return parts.length === 2 ? parent : `additional-${parts[1] || "1"}`;
  }
  return parent;
};
const isAdditionalTubeChild = (part: { params: Record<string, unknown> }) =>
  String(part.params.parentType ?? "").toLowerCase() === "additional tube";
const parentKey = (part: { params: Record<string, unknown> }) =>
  String(part.params.parent ?? "");

export const usePositioningStore = create<PositioningState>((set, get) => ({
  availableParts: [],
  ...loadPersistedState(),
  setAvailableParts: (parts) => set(() => ({ availableParts: parts })),
  syncAssemblyFromCatalog: (parts) =>
    set((state) => {
      const catalog = new Map(parts.map((part) => [part.id, part]));
      return {
        assembly: state.assembly.map((placed) => {
          const source = catalog.get(placed.id);
          if (!source) return placed;
          return {
            ...placed,
            label: source.label,
            type: source.type,
            internal: source.internal,
            params: { ...source.params },
          };
        }),
      };
    }),
  setLastDropPosition: (position) =>
    set((state) => {
      const next = { ...state, lastDropPosition: position };
      persistState(next);
      return { lastDropPosition: position };
    }),
  addToAssembly: (part, positionOverride) =>
    set((state) => {
      let position: [number, number, number] = positionOverride ?? state.lastDropPosition;
      const parentId = resolveParentBodyId(part.params.parent);
      if (part.type === "inner" && parentId) {
        const parent = state.assembly.find((item) => item.id === parentId);
        if (parent) {
          position = [...parent.position] as [number, number, number];
        }
      }
      if (isAdditionalTubeChild(part) && parentId) {
        const parent = state.assembly.find((item) => item.id === parentId);
        position = parent ? [...parent.position] as [number, number, number] : [0, 0, 0];
      }
      if (part.type === "fin" && parentId && positionOverride === undefined) {
        const parent = state.assembly.find((item) => item.id === parentId);
        if (parent) {
          const parentLen = Number(parent.params.length ?? 0);
          const rootChord = Number(part.params.root ?? 0);
          const plusOffset = Number(part.params.plus_offset ?? 0);
          const relativeTo = String(part.params.position_relative ?? "bottom").toLowerCase();
          const baseX =
            relativeTo === "top"
              ? parent.position[0] + Math.max(parentLen - rootChord - plusOffset, 0)
              : parent.position[0] + plusOffset;
          position = [baseX, parent.position[1], parent.position[2]];
        }
      }
      const finRotationDeg = Number(part.params.rotation_deg ?? 0);
      const entry: AssemblyPart = {
        ...part,
        position,
        rotation: [0, 0, Number.isFinite(finRotationDeg) ? (finRotationDeg * Math.PI) / 180 : 0],
        flipX: false,
        flipY: false,
        flipZ: false,
        finOffsets: part.type === "fin" ? [] : undefined,
        finPlaced: part.type === "fin" ? false : undefined,
      };
      const shouldAutoNestChildren =
        part.type === "body" && String(part.id).startsWith("additional-");
      if (shouldAutoNestChildren) {
        const existingIds = new Set(state.assembly.map((item) => item.id));
        const children = state.availableParts
          .filter((candidate) => isAdditionalTubeChild(candidate) && parentKey(candidate) === part.id)
          .filter((candidate) => !existingIds.has(candidate.id))
          .map((child) => {
            const childRotationDeg = Number(child.params.rotation_deg ?? 0);
            return {
              ...child,
              position: [...position] as [number, number, number],
              rotation: [
                0,
                0,
                Number.isFinite(childRotationDeg) ? (childRotationDeg * Math.PI) / 180 : 0,
              ] as [number, number, number],
              flipX: false,
              flipY: false,
              flipZ: false,
            } as AssemblyPart;
          });
        const assembly = [...state.assembly, entry, ...children];
        const history = [...state.history, entry];
        persistState({
          assembly,
          history,
          lastDropPosition: state.lastDropPosition,
          selectedId: entry.id,
        });
        return {
          assembly,
          history,
          selectedId: entry.id,
        };
      }
      const assembly = [...state.assembly, entry];
      const history = [...state.history, entry];
      persistState({
        assembly,
        history,
        lastDropPosition: state.lastDropPosition,
        selectedId: entry.id,
      });
      return {
        assembly,
        history,
        selectedId: entry.id,
      };
    }),
  updatePartPosition: (id, position) =>
    set((state) => {
      const assembly = state.assembly.map((part) => {
        if (part.id === id) {
          if (part.type === "inner") {
            const parentId =
              typeof part.params.parent === "string" ? String(part.params.parent) : "";
            const parent = state.assembly.find((item) => item.id === parentId);
            return parent ? { ...part, position: [...parent.position] } : { ...part, position };
          }
          if (isAdditionalTubeChild(part) && typeof part.params.parent === "string") {
            const parent = state.assembly.find((item) => item.id === String(part.params.parent));
            return parent ? { ...part, position: [...parent.position] } : { ...part, position: [0, 0, 0] };
          }
          return { ...part, position };
        }
        if (
          (part.type === "inner" || isAdditionalTubeChild(part)) &&
          typeof part.params.parent === "string"
        ) {
          const parentId = String(part.params.parent);
          if (parentId === id) {
            return { ...part, position: [...position] };
          }
        }
        return part;
      });
      persistState({
        assembly,
        history: state.history,
        lastDropPosition: state.lastDropPosition,
        selectedId: state.selectedId,
      });
      return { assembly };
    }),
  selectPart: (id) =>
    set((state) => {
      persistState({
        assembly: state.assembly,
        history: state.history,
        lastDropPosition: state.lastDropPosition,
        selectedId: id,
      });
      return { selectedId: id };
    }),
  clearAssembly: () =>
    set((state) => {
      persistState({
        assembly: [],
        history: [],
        lastDropPosition: state.lastDropPosition,
        selectedId: null,
      });
      return { assembly: [], history: [], selectedId: null };
    }),
  undoLast: () =>
    set((state) => {
      const last = state.history[state.history.length - 1];
      if (!last) return state;
      const removeIds = new Set<string>([last.id]);
      if (last.type === "body" && String(last.id).startsWith("additional-")) {
        state.assembly.forEach((part) => {
          if (isAdditionalTubeChild(part) && parentKey(part) === last.id) {
            removeIds.add(part.id);
          }
        });
      }
      const assembly = state.assembly.filter((part) => !removeIds.has(part.id));
      const history = state.history.slice(0, -1);
      const selectedId =
        state.selectedId && removeIds.has(state.selectedId) ? null : state.selectedId;
      persistState({
        assembly,
        history,
        lastDropPosition: state.lastDropPosition,
        selectedId,
      });
      return { assembly, history, selectedId };
    }),
  flipPart: (id, axis) =>
    set((state) => {
      const assembly = state.assembly.map((part) => {
        if (part.id !== id) return part;
        if (axis === "x") return { ...part, flipX: !part.flipX };
        if (axis === "y") return { ...part, flipY: !part.flipY };
        return { ...part, flipZ: !part.flipZ };
      });
      persistState({
        assembly,
        history: state.history,
        lastDropPosition: state.lastDropPosition,
        selectedId: state.selectedId,
      });
      return { assembly };
    }),
  setFinPlaced: (id) =>
    set((state) => {
      const assembly = state.assembly.map((part) =>
        part.id === id ? { ...part, finPlaced: true } : part
      );
      persistState({
        assembly,
        history: state.history,
        lastDropPosition: state.lastDropPosition,
        selectedId: state.selectedId,
      });
      return { assembly };
    }),
  updateFinOffset: (id, index, offset) =>
    set((state) => {
      const assembly = state.assembly.map((part) => {
        if (part.id !== id || part.type !== "fin") return part;
        const existing = part.finOffsets || [];
        const next = [...existing];
        next[index] = offset;
        return { ...part, finOffsets: next };
      });
      persistState({
        assembly,
        history: state.history,
        lastDropPosition: state.lastDropPosition,
        selectedId: state.selectedId,
      });
      return { assembly };
    }),
}));
