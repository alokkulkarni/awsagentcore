import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const proxyTarget = env.AGENT_API_URL || env.VITE_API_URL || 'http://localhost:8100';

  return {
    plugins: [react()],
    // Second HTML entry: the MSAL popup redirect bridge page (Teams sign-in)
    build: {
      rollupOptions: {
        input: {
          main: 'index.html',
          authRedirect: 'auth-redirect.html',
        },
      },
    },
    optimizeDeps: {
      include: ['@azure/msal-browser', '@azure/msal-browser/redirect-bridge'],
    },
    server: {
      // Listens on localhost by default; the Docker container overrides with
      // `--host 0.0.0.0` on the CLI (compose maps the port to 127.0.0.1 on the host).
      host: 'localhost',
      port: 5274,
      // Explicit allow-list keeps Vite's Host-header (DNS-rebinding) protection on
      allowedHosts: ['localhost', '127.0.0.1'],
      proxy: {
        '/api': {
          target: proxyTarget,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, ''),
        },
      },
    },
  };
});
