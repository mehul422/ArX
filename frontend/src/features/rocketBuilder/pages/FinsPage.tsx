import { Link } from "react-router-dom";
import { useRocketBuilderStore } from "../useRocketBuilderStore";

const FinsPage = () => {
  const { setStepComplete, steps } = useRocketBuilderStore();

  return (
    <div style={{ padding: "24px" }}>
      <h1>Fins</h1>
      <p>Define fin sets and attach them to body tubes.</p>
      <div style={{ display: "flex", gap: "8px" }}>
        <button onClick={() => setStepComplete("fins", true)}>
          Mark Complete
        </button>
        <button onClick={() => setStepComplete("fins", false)}>
          Mark Incomplete
        </button>
      </div>
      <div>Status: {steps.fins ? "Complete" : "Pending"}</div>
      <p>
        <Link to="/module-r">Back to Dashboard</Link>
      </p>
    </div>
  );
};

export default FinsPage;
