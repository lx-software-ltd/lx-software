import { defaultSiteContent, type LegalDocument } from '../lib/content'
import { usePageMeta } from '../lib/seo'

export function LegalPage({ kind }: { kind: 'privacy' | 'terms' }) {
  const content = defaultSiteContent
  const doc: LegalDocument = content.legal[kind]
  const path = kind === 'privacy' ? '/privacy' : '/terms'

  usePageMeta(
    `${doc.title} — ${content.site.name}`,
    path,
    doc.sections[0]?.paragraphs[0] ?? content.site.description,
  )

  return (
    <article className="section legal container">
      <h1>{doc.title}</h1>
      <p className="updated">Updated {doc.updated}</p>
      {doc.sections.map((section) => (
        <section key={section.heading}>
          <h2>{section.heading}</h2>
          {section.paragraphs.map((paragraph) => (
            <p key={paragraph}>{paragraph}</p>
          ))}
        </section>
      ))}
    </article>
  )
}
