import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const bridgePort = process.env.BRIDGE_PORT || '8787'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    proxy: {
      '/api': {
        target: `http://127.0.0.1:${bridgePort}`,
        changeOrigin: true,
      },
    },
  },
})
