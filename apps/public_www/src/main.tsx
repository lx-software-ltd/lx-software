import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource/ibm-plex-mono/latin-400.css'
import '@fontsource/ibm-plex-mono/latin-700.css'
import { whenDeferredCssApplied } from './lib/deferredCss'
import './index.css'
import App from './App.tsx'

const root = document.getElementById('root')
if (root) {
  void whenDeferredCssApplied().then(() => {
    createRoot(root).render(
      <StrictMode>
        <App />
      </StrictMode>,
    )
  })
}
