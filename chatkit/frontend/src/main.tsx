import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";
import "./dark.css";

document.documentElement.dataset.theme = localStorage.getItem("chat-tcg-theme") === "dark" ? "dark" : "light";

const container = document.getElementById("root");
if (!container) {
  throw new Error("Root element with id 'root' not found");
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>
);



import "./builder.css";
