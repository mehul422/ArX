export type MissionTargetObjective = {
  name: "apogee_ft" | "max_velocity_m_s";
  target: number;
  units: string;
  tolerance_pct?: number;
  weight?: number;
};

export type MissionTargetPayload = {
  objectives: MissionTargetObjective[];
  constraints: {
    max_pressure_psi: number;
    max_kn: number;
    max_vehicle_length_in: number;
    max_stage_length_ratio: number;
  };
  vehicle: {
    ref_diameter_in: number;
    rocket_length_in: number;
    total_mass_lb: number;
  };
  stage_count?: 1 | 2;
  separation_delay_s?: number;
  ignition_delay_s?: number;
  launch_altitude_ft?: number;
  rod_length_ft?: number;
  temperature_f?: number;
  wind_speed_mph?: number;
  launch_angle_deg?: number;
  fast_mode?: boolean;
  split_ratios?: number[];
  allowed_propellants?: {
    families?: string[];
    names?: string[];
    preset_path?: string | null;
  };
  solver_config?: {
    split_ratios?: number[];
    design_space?: {
      diameter_scales: number[];
      length_scales: number[];
      core_scales: number[];
      throat_scales: number[];
      exit_scales: number[];
      grain_count?: number;
    };
    cd_max?: number;
    mach_max?: number;
    cd_ramp?: boolean;
    total_mass_lb?: number;
    separation_delay_s?: number;
    ignition_delay_s?: number;
    tolerance_pct?: number;
  };
};

type MissionTargetJob = {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  result?: Record<string, unknown> | null;
  error?: { code?: string; message?: string; details?: Record<string, unknown> } | null;
};

const API_BASE =
  (import.meta as { env?: Record<string, string> }).env?.VITE_API_BASE_URL ||
  "";

export const submitMissionTarget = async (
  payload: MissionTargetPayload
): Promise<MissionTargetJob> => {
  const response = await fetch(`${API_BASE}/api/v1/optimize/mission-target/target-only`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`Mission target submit failed: ${response.status} ${detail}`);
  }
  return response.json();
};

export const fetchMissionTargetJob = async (jobId: string): Promise<MissionTargetJob> => {
  const response = await fetch(`${API_BASE}/api/v1/optimize/mission-target/${jobId}`);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`Mission target status failed: ${response.status} ${detail}`);
  }
  return response.json();
};

export const pollMissionTargetJob = async (
  jobId: string,
  options?: { intervalMs?: number; timeoutMs?: number }
): Promise<MissionTargetJob> => {
  const intervalMs = options?.intervalMs ?? 2000;
  const timeoutMs = options?.timeoutMs ?? 10 * 60 * 1000;
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const job = await fetchMissionTargetJob(jobId);
    if (job.status === "completed" || job.status === "failed") {
      return job;
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  throw new Error("Mission target polling timed out.");
};
