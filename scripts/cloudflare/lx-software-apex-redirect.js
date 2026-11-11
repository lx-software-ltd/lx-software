/**
 * Send every request on the proxied apex to the www CloudFront hostname.
 *
 * Single Redirects run before Workers and match the apex on both
 * schemes. Keep that rule's destination as concat(www host, request
 * path), never a literal star path. This Worker is the fallback 301
 * when that redirect is absent.
 *
 * Publish: python3 scripts/cloudflare/publish-apex-redirect.py apply
 */

export const CANONICAL_HOST = "www.lx-software.com";

export function canonicalUrl(href) {
  const url = new URL(href);
  url.protocol = "https:";
  url.hostname = CANONICAL_HOST;
  url.port = "";
  return url.toString();
}

export default {
  async fetch(request) {
    return Response.redirect(canonicalUrl(request.url), 301);
  },
};
