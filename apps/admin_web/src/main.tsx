import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "bootstrap/dist/css/bootstrap.min.css";
import "bootstrap-icons/font/bootstrap-icons.css";
import "@fontsource-variable/inter/wght.css";
import "./index.css";
import App from "./App.tsx";
import { isAdminMockEnabled } from "./lib/mock/isAdminMockEnabled";

async function bootstrap(): Promise<void> {
  if (isAdminMockEnabled()) {
    const { installAdminMockSession } = await import("./lib/mock/mockAdminApi");
    installAdminMockSession();
  }
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

void bootstrap();
