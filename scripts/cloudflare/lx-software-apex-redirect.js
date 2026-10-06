/**
 * Send every request on the proxied apex to the www CloudFront hostname.
 *
 * A Cloudflare Page Rule used to forward to a literal star path, so
 * `/about` on the apex became a star path on www. This Worker wins over
 * that rule on the apex wildcard route.
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
