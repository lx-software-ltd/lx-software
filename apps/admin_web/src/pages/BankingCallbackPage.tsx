import { useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useBankSync } from "../hooks/useBankSync";
import { useRunOncePerPageLoad } from "../hooks/useRunOncePerPageLoad";
import { getAdminApiErrorMessage } from "../lib/apiAdminClient";

/**
 * Landing page for the Enable Banking redirect (`/banking/callback?code=…&state=…`).
 * Exchanges the one-time code for a stored session, then returns to /banking.
 */
export function BankingCallbackPage() {
  const navigate = useNavigate();
  const { completeAuth } = useBankSync();

  const params = useMemo(
    () => new URLSearchParams(window.location.search),
    [],
  );
  const code = params.get("code");
  const state = params.get("state");
  const bankError = params.get("error");

  useRunOncePerPageLoad("banking-callback", () => {
    if (!code || !state) return;
    completeAuth.mutate(
      { code, state },
      { onSuccess: () => navigate("/banking", { replace: true }) },
    );
  });

  const errorMessage = !code || !state
    ? bankError
      ? `The bank did not authorize the connection (${bankError}).`
      : "Missing authorization code; restart the bank link."
    : completeAuth.isError
      ? (getAdminApiErrorMessage(completeAuth.error) ??
        "Could not complete the bank link.")
      : null;

  if (errorMessage) {
    return (
      <div>
        <div className="alert alert-danger" role="alert">
          {errorMessage}
        </div>
        <Link className="btn btn-outline-secondary btn-sm" to="/banking">
          Back to Banking
        </Link>
      </div>
    );
  }

  return <p className="text-muted">Completing bank connection…</p>;
}
