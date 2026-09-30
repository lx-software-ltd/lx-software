/** Built stylesheet links download early but do not block the poster paint. */
export function deferStylesheetLinks(html: string): string {
  return html.replace(/<link rel="stylesheet"([^>]*?)>/g, (tag) => {
    if (tag.includes('data-defer-css') || tag.includes('data-static-css') || tag.includes('media="print"')) return tag
    const href = /href="([^"]+\.css)"/.exec(tag)?.[1]
    if (!href) return tag
    const deferred = tag.replace(
      'rel="stylesheet"',
      'rel="stylesheet" media="print" data-defer-css',
    )
    return [
      `    <link rel="preload" href="${href}" as="style" crossorigin />`,
      deferred,
      `    <noscript><link rel="stylesheet" data-static-css href="${href}" /></noscript>`,
    ].join('\n')
  })
}

/** Same-origin font preloads. `crossorigin` is required or the preload is wasted. */
export function fontPreloadTags(fileNames: readonly string[]): string {
  return fileNames
    .filter((name) => name.endsWith('.woff2'))
    .map(
      (name) =>
        `    <link rel="preload" href="/${name}" as="font" type="font/woff2" crossorigin />`,
    )
    .join('\n')
}
