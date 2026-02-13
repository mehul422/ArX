import { create } from "zustand";

export type DesignMode = "MANUAL" | "AUTO";

export type StepKey = "bodyTubes" | "noseCones" | "fins";

export interface AssemblyDraft {
  bodyTubes: Array<Record<string, unknown>>;
  noseCones: Array<Record<string, unknown>>;
  fins: Array<Record<string, unknown>>;
}

export interface RocketBuilderState {
  globalWidth: number | null;
  isWidthLocked: boolean;
  designMode: DesignMode | null;
  steps: Record<StepKey, boolean>;
  assemblyDraft: AssemblyDraft;
  setGlobalWidth: (width: number) => void;
  setDesignMode: (mode: DesignMode) => void;
  setStepComplete: (step: StepKey, complete?: boolean) => void;
  isPositioningUnlocked: () => boolean;
  reset: () => void;
}

const initialSteps: Record<StepKey, boolean> = {
  bodyTubes: false,
  noseCones: false,
  fins: false,
};

const initialDraft: AssemblyDraft = {
  bodyTubes: [],
  noseCones: [],
  fins: [],
};

export const useRocketBuilderStore = create<RocketBuilderState>((set, get) => ({
  globalWidth: null,
  isWidthLocked: false,
  designMode: null,
  steps: { ...initialSteps },
  assemblyDraft: { ...initialDraft },
  setGlobalWidth: (width) =>
    set(() => ({
      globalWidth: width,
      isWidthLocked: true,
    })),
  setDesignMode: (mode) => set(() => ({ designMode: mode })),
  setStepComplete: (step, complete = true) =>
    set((state) => ({
      steps: {
        ...state.steps,
        [step]: complete,
      },
    })),
  isPositioningUnlocked: () => {
    const { steps } = get();
    return Boolean(steps.bodyTubes && steps.noseCones && steps.fins);
  },
  reset: () =>
    set(() => ({
      globalWidth: null,
      isWidthLocked: false,
      designMode: null,
      steps: { ...initialSteps },
      assemblyDraft: { ...initialDraft },
    })),
}));
