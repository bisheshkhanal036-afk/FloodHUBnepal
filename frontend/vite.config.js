import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    // Vite's dev server rejects requests whose Host header it doesn't
    // recognize by default; host.docker.internal is how a sibling
    // container (e.g. a Playwright container used to smoke-test this
    // app) reaches this one through Docker Desktop's gateway, alongside
    // the usual localhost/127.0.0.1 a host-machine browser uses.
    allowedHosts: ['localhost', '127.0.0.1', 'host.docker.internal'],
  },
})
