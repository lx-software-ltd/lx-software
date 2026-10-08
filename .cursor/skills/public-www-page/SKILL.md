---
name: public-www-page
description: Add or edit a public website page so content, SEO routes, and pre-render stay in step.
---

# Public website page

1. Put copy in `apps/public_www/src/content/site.json`. Service and about pages are `pages[]`.
2. Register the route in `scripts/site-seo.ts` when it is a new path.
3. Keep `src/lib/content.test.ts` assertions on slugs and lengths passing.
4. Render the same markup on the server and the client. Browser APIs go through `useSyncExternalStore` with a server snapshot.
5. `npm run build` must emit the route with an `<h1>` and inline CSS.
6. Deploy uploads the page under its extensionless S3 key. Do not add a new extensionless key without that upload path in `scripts/deploy/deploy-public-website.sh`.
