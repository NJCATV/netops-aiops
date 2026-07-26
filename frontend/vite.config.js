import vue from "@vitejs/plugin-vue";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  return {
    base: env.VITE_BASE_PATH || "/",
    plugins: [vue()],
    server: {
      host: "0.0.0.0",
      port: 5772,
      proxy: {
        "/api": "http://127.0.0.1:8080",
      },
    },
    preview: {
      host: "0.0.0.0",
      port: 5772,
    },
  };
});
