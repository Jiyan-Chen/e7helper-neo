import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { Background } from "./components/shell/Background";
import { ConnectGate } from "./components/shell/ConnectGate";
import { queryClient } from "./lib/query";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <Background />
      <ConnectGate>
        <App />
      </ConnectGate>
    </QueryClientProvider>
  </StrictMode>,
);
