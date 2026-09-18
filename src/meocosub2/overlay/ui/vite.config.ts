import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { resolve, dirname } from "node:path";
import fs from "node:fs";

const here = dirname(fileURLToPath(import.meta.url));
const staticDir = resolve(here, "..", "static");

const cleanAssets = {
  name: "clean-assets",
  apply: "build" as const,
  writeBundle(options: { dir?: string }, bundle: Record<string, { fileName: string }>) {
    const assetsPath = resolve(options.dir ?? staticDir, "assets");
    if (!fs.existsSync(assetsPath)) return;
    const emitted = new Set(
      Object.values(bundle)
        .map((c) => c.fileName)
        .filter((f) => f.startsWith("assets/"))
        .map((f) => f.slice("assets/".length)),
    );
    for (const file of fs.readdirSync(assetsPath)) {
      if (!emitted.has(file)) {
        fs.rmSync(resolve(assetsPath, file), { force: true });
      }
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
