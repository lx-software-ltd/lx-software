import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => ({
  base: "/",
  build: {
    outDir: "dist",
  },
  plugins: [react()],
  // Pin the flag so production builds replace it with "0" and drop the mock
  // chunk. Mock mode (`npm run dev:mock`, `build:mock`) stays "1".
  define: {
    "import.meta.env.VITE_ADMIN_MOCK": JSON.stringify(mode === "mock" ? "1" : "0"),
  },
}));
