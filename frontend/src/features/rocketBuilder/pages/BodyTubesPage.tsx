import { Link } from "react-router-dom";
import { useRocketBuilderStore } from "../useRocketBuilderStore";

const BodyTubesPage = () => {
  const { setStepComplete, steps } = useRocketBuilderStore();

  return (
    <div style={{ padding: "24px" }}>
      <h1>Body Tubes</h1>
      <p>Motor mounts and additional body tubes configuration will live here.</p>
      <div style={{ display: "flex", gap: "8px" }}>
        <button onClick={() => setStepComplete("bodyTubes", true)}>
          Mark Complete
        </button>
        <button onClick={() => setStepComplete("bodyTubes", false)}>
          Mark Incomplete
        </button>
      </div>
      <div>Status: {steps.bodyTubes ? "Complete" : "Pending"}</div>
      <p>
        <Link to="/module-r">Back to Dashboard</Link>
      </p>
    </div>
  );
};

export default BodyTubesPage;
