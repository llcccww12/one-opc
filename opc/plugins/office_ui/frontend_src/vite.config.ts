import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: './',
  server: {
    proxy: {
      '/ws': {
        target: 'http://localhost:8765',
        ws: true,
      },
      '/api': {
        target: 'http://localhost:8765',
      },
    },
  },
  build: {
    outDir: '../frontend_dist',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks: {
          phaser: ['phaser'],
        },
      },
    },
  },
})

