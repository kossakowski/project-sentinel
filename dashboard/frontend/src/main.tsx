import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { App } from "./App";
import "./styles/index.css";

const container = document.getElementById("root");
if (!container) {
  throw new Error("Missing #root container in index.html");
}

// Opt into React Router v7 behaviour now so the migration is silent — kills
// the dev-time warnings vitest emits about future flags.
const routerFutureFlags = {
  v7_startTransition: true,
  v7_relativeSplatPath: true,
};

createRoot(container).render(
  <StrictMode>
    <BrowserRouter future={routerFutureFlags}>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
