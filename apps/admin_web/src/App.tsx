import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./components/AuthProvider";
import { AuthenticatedShell } from "./components/AuthenticatedShell";
import { LazyPage } from "./components/LazyPage";
import { RequireAuth } from "./components/RequireAuth";
import { AuthCallbackPage } from "./pages/AuthCallbackPage";
import { BankingCallbackPage } from "./pages/BankingCallbackPage";
import { DashboardPage } from "./pages/DashboardPage";
import { FinancePage } from "./pages/FinancePage";
import { LinkedInCallbackPage } from "./pages/LinkedInCallbackPage";
import { LxSoftwarePage } from "./pages/LxSoftwarePage";
import { EvolveSproutsPage } from "./pages/EvolveSproutsPage";

const AssetsPage = lazy(() => import("./pages/AssetsPage").then((m) => ({ default: m.AssetsPage })));
const BankingPage = lazy(() => import("./pages/BankingPage").then((m) => ({ default: m.BankingPage })));
const SiuTinDeiPage = lazy(() => import("./pages/SiuTinDeiPage").then((m) => ({ default: m.SiuTinDeiPage })));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/auth/callback" element={<AuthCallbackPage />} />
            <Route element={<RequireAuth />}>
              <Route element={<AuthenticatedShell />}>
                <Route index element={<DashboardPage />} />
                <Route path="assets" element={<LazyPage><AssetsPage /></LazyPage>} />
                <Route path="finance" element={<FinancePage />} />
                <Route path="banking" element={<LazyPage><BankingPage /></LazyPage>} />
                <Route path="banking/callback" element={<BankingCallbackPage />} />
                <Route path="siu-tin-dei" element={<LazyPage><SiuTinDeiPage /></LazyPage>} />
                <Route path="evolve-sprouts" element={<EvolveSproutsPage />} />
                <Route path="lx-software" element={<LxSoftwarePage />} />
                <Route path="lx-software/linkedin/callback" element={<LinkedInCallbackPage />} />
              </Route>
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
}

export default App;
