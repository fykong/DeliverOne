import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app/App";
import { ConfirmProvider } from "./shared/ConfirmDialog";
import "./app/styles.css";

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConfirmProvider>
      <App />
    </ConfirmProvider>
  </React.StrictMode>
);
