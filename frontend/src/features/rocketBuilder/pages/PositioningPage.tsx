import { Link } from "react-router-dom";
import { useRocketBuilderStore } from "../useRocketBuilderStore";

const PositioningPage = () => {
  const { isPositioningUnlocked } = useRocketBuilderStore();

  if (!isPositioningUnlocked()) {
    return (
      <div style={{ padding: "24px" }}>
        <h1>Positioning Workspace</h1>
        <p>This module is locked until Body Tubes, Nose Cones, and Fins are complete.</p>
        <p>
          <Link to="/module-r">Back to Dashboard</Link>
        </p>
      </div>
    );
  }

  return (
    <div style={{ padding: "24px" }}>
      <h1>Positioning Workspace</h1>
      <p>Drag and drop components to define the stack order.</p>
      <p>
        <Link to="/module-r">Back to Dashboard</Link>
      </p>
    </div>
  );
};

export default PositioningPage;
