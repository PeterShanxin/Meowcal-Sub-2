import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { resolve, dirname } from "node:path";
import fs from "node:fs";

const here = dirname(fileURLToPath(import.meta.url));
const staticDir = resolve(here, "..", "static");

const cleanAssets = {
  name: "clean-assets",
  buildStart() {
    const assetsPath = resolve(staticDir, "assets");
    if (fs.existsSync(assetsPath)) {
      fs.rmSync(assetsPath, { recursive: true, force: true });
    }
  },
};

export default defineConfig({
  plugins: [react(), cleanAssets],
  base: "/static/",
  build: {
    outDir: staticDir,
    emptyOutDir: false,
    assetsDir: "assets",
    rollupOptions: {
      output: {
        entryFileNames: "assets/[name]-[hash].js",
        chunkFileNames: "assets/[name]-[hash].js",
        assetFileNames: "assets/[name]-[hash][extname]",
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8765",
      "/ws": { target: "ws://127.0.0.1:8765", ws: true },
    },
  },
});
