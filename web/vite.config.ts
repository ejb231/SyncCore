import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': { target: 'https://localhost:8443', secure: false },
      '/health': { target: 'https://localhost:8443', secure: false },
    },
  },
})
