import React from "react";
import { createRoot } from "react-dom/client";
import AppElectron from "./App.electron";

const container = document.getElementById("root");

if (!container) {
  throw new Error("Root element not found");
}

createRoot(container).render(<AppElectron />);
