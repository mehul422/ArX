import { Link } from "react-router-dom";
import { useRocketBuilderStore } from "../useRocketBuilderStore";

const ModuleRIndex = () => {
  const {
    globalWidth,
    isWidthLocked,
    designMode,
    steps,
    setGlobalWidth,
    setDesignMode,
    isPositioningUnlocked,
    reset,
  } = useRocketBuilderStore();

  return (
    <div style={{ padding: "24px" }}>
      <h1>Module R — Flight-Ready Rocket Builder</h1>

      <section style={{ marginTop: "20px" }}>
        <h2>Step 1: Set Global Width</h2>
        <p>The width is immutable once set.</p>
        <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
          <input
            type="number"
            placeholder="Rocket diameter (m)"
            disabled={isWidthLocked}
            defaultValue={globalWidth ?? undefined}
            onBlur={(event) => {
              const value = Number(event.currentTarget.value);
              if (!Number.isNaN(value) && value > 0) {
                setGlobalWidth(value);
              }
            }}
          />
          <button onClick={reset}>Reset</button>
        </div>
        <div>Current width: {globalWidth ?? "unset"}</div>
      </section>

      <section style={{ marginTop: "24px" }}>
        <h2>Entry Path</h2>
        <div style={{ display: "flex", gap: "12px" }}>
          <button onClick={() => setDesignMode("MANUAL")}>Manual</button>
          <button onClick={() => setDesignMode("AUTO")}>Auto (.ric)</button>
        </div>
        <div>Selected mode: {designMode ?? "none"}</div>
      </section>

      {designMode === "AUTO" ? (
        <section style={{ marginTop: "24px" }}>
          <h2>Automated Import</h2>
          <p>Upload a .ric file and set constraints for auto-build.</p>
          <div style={{ display: "grid", gap: "8px", maxWidth: "420px" }}>
            <input type="file" accept=".ric" />
            <input type="number" placeholder="Upper bound length (m)" />
            <input type="number" placeholder="Upper bound mass (kg)" />
            <input type="number" placeholder="Target apogee (m)" />
            <label>
              <input type="checkbox" /> Include ballast
            </label>
            <label>
              <input type="checkbox" /> Include telemetry
            </label>
            <label>
              <input type="checkbox" /> Include parachute
            </label>
            <button>Submit Auto-Build</button>
          </div>
        </section>
      ) : null}

      <section style={{ marginTop: "24px" }}>
        <h2>Dashboard</h2>
        <ul>
          <li>
            Body Tubes: {steps.bodyTubes ? "Complete" : "Pending"} —{" "}
            <Link to="/module-r/body-tubes">Open</Link>
          </li>
          <li>
            Nose Cones: {steps.noseCones ? "Complete" : "Pending"} —{" "}
            <Link to="/module-r/nose-cones">Open</Link>
          </li>
          <li>
            Fins: {steps.fins ? "Complete" : "Pending"} —{" "}
            <Link to="/module-r/fins">Open</Link>
          </li>
          <li>
            Positioning: {isPositioningUnlocked() ? "Unlocked" : "Locked"} —{" "}
            <Link to="/module-r/positioning">Open</Link>
          </li>
        </ul>
      </section>
    </div>
  );
};

export default ModuleRIndex;
