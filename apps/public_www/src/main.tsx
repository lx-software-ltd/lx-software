import { StrictMode } from 'react'
import { createRoot, hydrateRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import '@fontsource/ibm-plex-mono/latin-400.css'
import '@fontsource/ibm-plex-mono/latin-700.css'
import { whenDeferredCssApplied } from './lib/deferredCss'
import './index.css'
import { AppRoutes } from './App.tsx'
import { installGtm } from './lib/gtm.ts'

installGtm<HTMLScriptElement>(import.meta.env.VITE_GTM_ID, window, document)

const root = document.getElementById('root')
if (root) {
  const app = (
    <StrictMode>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </StrictMode>
  )
  void whenDeferredCssApplied().then(() => {
    // The production build ships every route pre-rendered into #root
    // (vite.config.ts `prerenderPages`); the dev server starts empty.
    if (root.hasChildNodes()) {
      hydrateRoot(root, app)
    } else {
      createRoot(root).render(app)
    }
  })
}
