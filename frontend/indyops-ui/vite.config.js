import { defineConfig } from 'vite'
import react, { reactCompilerPreset } from '@vitejs/plugin-react'
import babel from '@rolldown/plugin-babel'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    babel({ presets: [reactCompilerPreset()] })
  ],
  server: {
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
  build: {
    rolldownOptions: {
      output: {
        // Plotly (~4MB) is only used by the lazy Analysis + Market pages. Pin it
        // to its own chunk so it stays out of the entry bundle and is fetched
        // on demand the first time either of those routes is opened.
        advancedChunks: {
          groups: [{ name: 'plotly', test: /plotly/ }],
        },
      },
    },
  },
})
