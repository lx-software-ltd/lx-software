import { lazy, Suspense } from 'react'
import { Route, Routes } from 'react-router-dom'
import { SiteLayout } from './components/site-layout'
import { defaultSiteContent } from './lib/content'
import { HomePage } from './pages/home'

const LegalPage = lazy(() => import('./pages/legal').then((mod) => ({ default: mod.LegalPage })))
const NotFoundPage = lazy(() =>
  import('./pages/not-found').then((mod) => ({ default: mod.NotFoundPage })),
)
const WeChatPage = lazy(() => import('./pages/wechat').then((mod) => ({ default: mod.WeChatPage })))
const ContentPage = lazy(() =>
  import('./pages/content-page').then((mod) => ({ default: mod.ContentPage })),
)

/**
 * Route table shared by the browser (`main.tsx`, inside a BrowserRouter) and
 * the build-time pre-render (`entry-server.tsx`, inside a StaticRouter).
 */
export function AppRoutes() {
  return (
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
        {defaultSiteContent.pages.map((page) => (
          <Route
            key={page.slug}
            path={page.slug}
            element={
              <Suspense fallback={null}>
                <ContentPage page={page} />
              </Suspense>
            }
          />
        ))}
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
  )
}
