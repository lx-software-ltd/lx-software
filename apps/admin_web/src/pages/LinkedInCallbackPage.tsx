import { useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useLinkedIn } from "../hooks/useLinkedIn";
import { useRunOncePerPageLoad } from "../hooks/useRunOncePerPageLoad";
import { getAdminApiErrorMessage } from "../lib/apiAdminClient";

/**
 * Known LinkedIn redirect `error` codes. An empty code means the redirect
 * carried no error. Anything else uses a fixed sentence.
 */
const REDIRECT_NOTICES: Record<string, string> = {
  "": "",
  user_cancelled_login: "The LinkedIn connection was cancelled.",
  user_cancelled_authorize: "The LinkedIn connection was cancelled.",
  unauthorized_scope_error:
    "LinkedIn refused a requested permission. Connect again without company pages, or approve Community Management on the LinkedIn app.",
};

const UNKNOWN_REDIRECT_NOTICE = "LinkedIn did not authorize the connection.";

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
  const redirectError = params.get("error");

  useRunOncePerPageLoad("linkedin-callback", () => {
    if (!code || !state) return;
    completeAuth.mutate(
      { code, state },
      { onSuccess: () => navigate("/lx-software?tab=linkedin&section=settings", { replace: true }) },
    );
  });

  const redirectNotice = REDIRECT_NOTICES[redirectError ?? ""] ?? UNKNOWN_REDIRECT_NOTICE;
  const errorMessage = !code || !state
    ? redirectNotice || "Missing authorization code. Connect again from LinkedIn settings."
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
