import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles/operational.css";
import "./styles/clone.css";

const container = document.getElementById("root");
if (!container) {
  throw new Error("#5298 clone: #root mount point is missing");
}

// The served revision is published so a verification run can prove that the
// server it talks to was built from the current working tree.
document.documentElement.dataset.revision = __APP_REVISION__;

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
