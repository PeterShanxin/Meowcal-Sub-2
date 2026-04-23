import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app";
import { applyFontScale } from "./lib/font-scale";
import "./styles/theme.css";

applyFontScale();

const container = document.getElementById("root");
if (!container) {
  throw new Error("Root element #root not found");
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
