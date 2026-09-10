import { defineConfig } from "vite";
import preact from "@preact/preset-vite";

// servido pelo FastAPI/StaticFiles em /iptv/ (mesmo caminho do frontend antigo)
export default defineConfig({
  // durante a migração o app v2 vive em /iptv/v2/ e convive com o frontend
  // antigo em /iptv/. Vira /iptv/ quando os 4 passos estiverem prontos.
  base: "/iptv/v2/",
  plugins: [preact()],
  build: {
    outDir: "dist",
    target: "es2020",
    // hls.js sai do bundle inicial (só carrega quando dá play)
    chunkSizeWarningLimit: 900,
  },
  server: { port: 5174 },
});
