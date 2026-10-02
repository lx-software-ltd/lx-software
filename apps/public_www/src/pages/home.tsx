import { AsciiDivider } from '../components/AsciiDivider'
import { ContactIcons } from '../components/ContactIcons'
import { Faq } from '../components/Faq'
import { ProjectCarousel } from '../components/ProjectCarousel'
import { trackEvent } from '../lib/analytics'
import { defaultSiteContent } from '../lib/content'
import { usePageMeta } from '../lib/seo'
import { useSections } from '../lib/sections'

export function HomePage() {
  const content = defaultSiteContent
  const { scrollTo } = useSections()

  usePageMeta(content.site.title, '/', content.site.description)

  return (
    <>
      <section className="hero container" id="top">
        <p className="visually-hidden">
          Background: a slowed, silent night harbour, shown in full without cropping.
        </p>
        <h1>
          <span className="kicker">{content.hero.kicker}</span>
          <span className="cursor" aria-hidden="true" />
          <span className="headline">{content.hero.headline}</span>
        </h1>
        <p className="lede">{content.hero.summary}</p>
        <a
          className="scroll-cue"
          href="#who-i-am"
          onClick={(event) => {
            if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) {
              return
            }
            event.preventDefault()
            trackEvent({ event: 'nav_click', section: 'who-i-am' })
            scrollTo('who-i-am')
          }}
        >
          [ {content.hero.scrollLabel} ]
        </a>
      </section>

      <AsciiDivider />

      <section className="section" id="who-i-am" aria-labelledby="who-heading">
        <div className="container">
          <h2 id="who-heading">{content.whoIAm.heading}</h2>
          {content.whoIAm.paragraphs.map((paragraph) => (
            <p key={paragraph}>{paragraph}</p>
          ))}
        </div>
      </section>

      <AsciiDivider />

      <section className="section" id="what-i-do" aria-labelledby="do-heading">
        <div className="container">
          <h2 id="do-heading">{content.whatIDo.heading}</h2>
          <p>{content.whatIDo.intro}</p>
          <div className="cards">
            {content.whatIDo.services.map((service) => (
              <article key={service.title} className="card-block">
                <h3>{service.title}</h3>
                <p>{service.description}</p>
              </article>
            ))}
          </div>
          <ul className="skills" aria-label="Skills">
            {content.whatIDo.skills.map((skill) => (
              <li key={skill}>[ {skill} ]</li>
            ))}
          </ul>
        </div>
      </section>

      <AsciiDivider />

      <section className="section" id="projects" aria-labelledby="projects-heading">
        <div className="container">
          <h2 id="projects-heading">{content.projects.heading}</h2>
          <p>{content.projects.intro}</p>
          <ProjectCarousel items={content.projects.items} />
        </div>
      </section>

      <AsciiDivider />

      <section className="section" id="contact" aria-labelledby="contact-heading">
        <div className="container">
          <h2 id="contact-heading">{content.contact.heading}</h2>
          <p>{content.contact.intro}</p>
          <address>
            <ContactIcons />
          </address>
        </div>
      </section>

      <AsciiDivider />
      <Faq items={content.faq} />
    </>
  )
}
