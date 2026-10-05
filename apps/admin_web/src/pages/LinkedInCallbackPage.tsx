import { useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useLinkedIn } from "../hooks/useLinkedIn";
import { useRunOncePerPageLoad } from "../hooks/useRunOncePerPageLoad";
import { getAdminApiErrorMessage } from "../lib/apiAdminClient";

/**
 * Landing page for the LinkedIn redirect (`/lx-software/linkedin/callback?code=…&state=…`).
 * Exchanges the one-time code, then returns to the LinkedIn settings section.
 */
export function LinkedInCallbackPage() {
  const navigate = useNavigate();
  const { completeAuth } = useLinkedIn();

  const params = useMemo(() => new URLSearchParams(window.location.search), []);
  const code = params.get("code");
  const state = params.get("state");
  const oauthError = params.get("error");

  useRunOncePerPageLoad("linkedin-callback", () => {
    if (!code || !state) return;
    completeAuth.mutate(
      { code, state },
      { onSuccess: () => navigate("/lx-software?tab=linkedin&section=settings", { replace: true }) },
    );
  });

  const errorMessage = !code || !state
    ? oauthError
      ? `LinkedIn did not authorize the connection (${oauthError}).`
      : "Missing authorization code. Connect again from LinkedIn settings."
    : completeAuth.isError
      ? (getAdminApiErrorMessage(completeAuth.error) ?? "Could not complete the LinkedIn connection.")
      : null;

  if (errorMessage) {
    return (
      <div>
        <div className="alert alert-danger" role="alert">
          {errorMessage}
        </div>
        <Link className="btn btn-outline-secondary btn-sm" to="/lx-software?tab=linkedin&section=settings">
          Back to LinkedIn
        </Link>
      </div>
    );
  }

  return <p className="text-muted">Completing LinkedIn connection…</p>;
}
