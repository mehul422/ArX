import { HashRouter as Router, Route, Routes } from "react-router-dom";
import ArxInterface from "./components/ArxInterface";
import BodyTubesPage from "./features/rocketBuilder/pages/BodyTubesPage";
import FinsPage from "./features/rocketBuilder/pages/FinsPage";
import ModuleRIndex from "./features/rocketBuilder/pages/ModuleRIndex";
import NoseConesPage from "./features/rocketBuilder/pages/NoseConesPage";
import PositioningPage from "./features/rocketBuilder/pages/PositioningPage";

const AppElectron = () => (
  <Router>
    <Routes>
      <Route path="/" element={<ArxInterface />} />
      <Route path="*" element={<ArxInterface />} />
      <Route path="/module-r" element={<ModuleRIndex />} />
      <Route path="/module-r/body-tubes" element={<BodyTubesPage />} />
      <Route path="/module-r/nose-cones" element={<NoseConesPage />} />
      <Route path="/module-r/fins" element={<FinsPage />} />
      <Route path="/module-r/positioning" element={<PositioningPage />} />
    </Routes>
  </Router>
);

export default AppElectron;
