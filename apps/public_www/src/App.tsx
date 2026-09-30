import { lazy, Suspense } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { SiteLayout } from './components/site-layout'
import { HomePage } from './pages/home'

const LegalPage = lazy(() => import('./pages/legal').then((mod) => ({ default: mod.LegalPage })))
const NotFoundPage = lazy(() =>
  import('./pages/not-found').then((mod) => ({ default: mod.NotFoundPage })),
)
const WeChatPage = lazy(() => import('./pages/wechat').then((mod) => ({ default: mod.WeChatPage })))

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<SiteLayout />}>
          <Route index element={<HomePage />} />
          <Route
            path="privacy"
            element={
              <Suspense fallback={null}>
                <LegalPage kind="privacy" />
              </Suspense>
            }
          />
          <Route
            path="terms"
            element={
              <Suspense fallback={null}>
                <LegalPage kind="terms" />
              </Suspense>
            }
          />
          <Route
            path="wechat"
            element={
              <Suspense fallback={null}>
                <WeChatPage />
              </Suspense>
            }
          />
          <Route
            path="*"
            element={
              <Suspense fallback={null}>
                <NotFoundPage />
              </Suspense>
            }
          />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
