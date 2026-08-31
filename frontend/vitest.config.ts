import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Separate from vite.config.ts (dev-server proxy setup) -- vitest only
// needs the React plugin + jsdom environment for chart-primitive component
// tests. No source under src/ imports this file directly.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['src/**/*.test.tsx', 'src/**/*.test.ts'],
    setupFiles: ['./vitest.setup.ts'],
  },
})
