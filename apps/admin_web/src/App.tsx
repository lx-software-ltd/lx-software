import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./components/AuthProvider";
import { AuthenticatedShell } from "./components/AuthenticatedShell";
import { RequireAuth } from "./components/RequireAuth";
import { AssetsPage } from "./pages/AssetsPage";
import { AuthCallbackPage } from "./pages/AuthCallbackPage";
import { BankingCallbackPage } from "./pages/BankingCallbackPage";
import { BankingPage } from "./pages/BankingPage";
import { DashboardPage } from "./pages/DashboardPage";
import { FinancePage } from "./pages/FinancePage";
import { LxSoftwarePage } from "./pages/LxSoftwarePage";
import { SiuTinDeiPage } from "./pages/SiuTinDeiPage";

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
                <Route path="assets" element={<AssetsPage />} />
                <Route path="finance" element={<FinancePage />} />
                <Route path="banking" element={<BankingPage />} />
                <Route path="banking/callback" element={<BankingCallbackPage />} />
                <Route path="siu-tin-dei" element={<SiuTinDeiPage />} />
                <Route path="lx-software" element={<LxSoftwarePage />} />
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
