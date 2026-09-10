export type NewsletterList = "parents" | "providers";
export type NewsletterLang = "en" | "zh-HK";

export async function subscribeToNewsletter(input: {
  readonly list: NewsletterList;
  readonly email: string;
  readonly lang: NewsletterLang;
}): Promise<void> {
  const base = String(import.meta.env.VITE_PUBLIC_API_URL || "").replace(/\/$/, "");
  if (!base) {
    throw new Error("Newsletter signup is not configured (VITE_PUBLIC_API_URL).");
  }
  const response = await fetch(`${base}/public/newsletter/subscribe`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!response.ok) {
    throw new Error(`Subscribe failed: ${response.status}`);
  }
}
