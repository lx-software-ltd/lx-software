import { Link } from 'react-router-dom'
import { AsciiDivider } from '../components/AsciiDivider'
import { CallToAction } from '../components/CallToAction'
import { Faq } from '../components/Faq'
import { defaultSiteContent, type ContentPage as ContentPageData } from '../lib/content'
import { usePageMeta } from '../lib/seo'

/** Renders one entry of `site.json` `pages`: a service page or the about page. */
export function ContentPage({ page }: { page: ContentPageData }) {
  const { chrome } = defaultSiteContent
  usePageMeta(page.metaTitle, `/${page.slug}`, page.description)

  return (
    <>
      <article className="section legal page container">
        <nav aria-label="Breadcrumb" className="breadcrumb">
          <Link to="/">{chrome.breadcrumbHome}</Link>
          <span aria-hidden="true"> / </span>
          <span aria-current="page">{page.navLabel}</span>
        </nav>
        <h1>{page.title}</h1>
        <p className="lede">{page.intro}</p>
        {page.sections.map((section) => (
          <section key={section.heading}>
            <h2>{section.heading}</h2>
            {section.paragraphs?.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}
            {section.bullets && section.bullets.length > 0 ? (
              <ul className="page-list">
                {section.bullets.map((bullet) => (
                  <li key={bullet}>{bullet}</li>
                ))}
              </ul>
            ) : null}
          </section>
        ))}
        <CallToAction page={page.slug} />
      </article>
      {page.faq && page.faq.length > 0 ? (
        <>
          <AsciiDivider />
          <Faq items={page.faq} />
        </>
      ) : null}
    </>
  )
}
