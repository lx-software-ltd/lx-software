export interface AdminConfig {
  readonly clientId: string;
  readonly cognitoDomain: string;
  readonly redirectUri: string;
  readonly apiBaseUrl: string;
}

export function getAdminConfig(): AdminConfig {
  const clientId = import.meta.env.VITE_COGNITO_CLIENT_ID ?? "";
  // CognitoDomain from the lxsoftware stack is an https origin. Callers
  // append /oauth2/* and /logout, and logout passes the result to `new URL`.
  const cognitoDomain = (import.meta.env.VITE_COGNITO_DOMAIN ?? "").replace(
    /\/$/,
    ""
  );
  const redirectUri = import.meta.env.VITE_COGNITO_REDIRECT_URI ?? "";
  const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? "").replace(
    /\/$/,
    ""
  );

  if (!clientId || !cognitoDomain || !redirectUri) {
    throw new Error(
      "Missing Cognito VITE_ configuration. Copy .env.example to .env and set values."
    );
  }

  return {
    clientId,
    cognitoDomain,
    redirectUri,
    apiBaseUrl,
  };
}
