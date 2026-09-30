/**
 * Normalises the LinkedIn build-time value. Accepts a full profile URL or a
 * bare `in/<slug>` / `<slug>` and returns an https URL without query or hash.
 * Anything that is not a linkedin.com host yields ''.
 */
export function linkedinUrl(raw: string | undefined): string {
  const value = (raw ?? '').trim()
  if (!value) return ''
  if (/^https?:\/\//i.test(value)) {
    try {
      const url = new URL(value)
      if (!/(^|\.)linkedin\.com$/i.test(url.hostname)) return ''
      url.protocol = 'https:'
      url.search = ''
      url.hash = ''
      return url.toString().replace(/\/$/, '')
    } catch {
      return ''
    }
  }
  const slug = value.replace(/^\/+/, '').replace(/\/+$/, '')
  if (!slug) return ''
  const path = /^(in|company)\//i.test(slug) ? slug : `in/${slug}`
  return `https://www.linkedin.com/${path}`
}
