import { Link } from "react-router-dom";
import { useRocketBuilderStore } from "../useRocketBuilderStore";

const NoseConesPage = () => {
  const { setStepComplete, steps } = useRocketBuilderStore();

  return (
    <div style={{ padding: "24px" }}>
      <h1>Nose Cones</h1>
      <p>Configure nose cone geometry and materials here.</p>
      <div style={{ display: "flex", gap: "8px" }}>
        <button onClick={() => setStepComplete("noseCones", true)}>
          Mark Complete
        </button>
        <button onClick={() => setStepComplete("noseCones", false)}>
          Mark Incomplete
        </button>
      </div>
      <div>Status: {steps.noseCones ? "Complete" : "Pending"}</div>
      <p>
        <Link to="/module-r">Back to Dashboard</Link>
      </p>
    </div>
  );
};

export default NoseConesPage;
