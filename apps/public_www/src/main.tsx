import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource/ibm-plex-mono/latin-400.css'
import '@fontsource/ibm-plex-mono/latin-700.css'
import 'bootstrap/dist/css/bootstrap-grid.css'
import './index.css'
import App from './App.tsx'
import { installGtm } from './lib/gtm.ts'

installGtm<HTMLScriptElement>(import.meta.env.VITE_GTM_ID, window, document)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
