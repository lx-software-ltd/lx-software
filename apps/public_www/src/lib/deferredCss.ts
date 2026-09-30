/** Applies stylesheets that were shipped as `media="print"` so they would not block the poster. */
export function whenDeferredCssApplied(): Promise<void> {
  const links = document.querySelectorAll<HTMLLinkElement>('link[data-defer-css]')
  const pending: Promise<void>[] = []
  links.forEach((link) => {
    link.media = 'all'
    if (link.sheet) return
    pending.push(
      new Promise((resolve) => {
        let settled = false
        const done = () => {
          if (settled) return
          settled = true
          resolve()
        }
        link.addEventListener('load', done, { once: true })
        link.addEventListener('error', done, { once: true })
        if (link.sheet) done()
        window.setTimeout(done, 3000)
      }),
    )
  })
  return Promise.all(pending).then(() => undefined)
}
