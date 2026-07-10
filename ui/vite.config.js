import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig(function (_a) {
    var mode = _a.mode;
    var env = loadEnv(mode, ".", "");
    var proxyTarget = env.VITE_PROXY_TARGET || "http://localhost:8787";
    return {
        plugins: [react()],
        server: {
            port: 5173,
            proxy: {
                "/api": proxyTarget
            }
        }
    };
});
