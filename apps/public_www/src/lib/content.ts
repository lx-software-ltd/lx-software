import bundled from '../content/site.json' with { type: 'json' }

export interface Service {
  title: string
  description: string
  /** In-site route of the page that expands on this service. */
  href?: string
}

export interface PageSection {
  heading: string
  paragraphs?: string[]
  bullets?: string[]
}

/** A standalone content page: a service page or the about page. */
export interface ContentPage {
  slug: string
  navLabel: string
  title: string
  metaTitle: string
  description: string
  intro: string
  /** Title of the `whatIDo.services` entry this page describes, if any. */
  service?: string
  sections: PageSection[]
  faq?: FaqItem[]
}

export interface CallToAction {
  heading: string
  body: string
  label: string
  href: string
}

export interface ProjectItem {
  title: string
  description: string
  ascii?: string[]
  logo?: string
  url?: string
  status?: string
}

export interface FaqItem {
  q: string
  a: string
}

export interface LegalSection {
  heading: string
  paragraphs: string[]
}

export interface LegalDocument {
  title: string
  updated: string
  sections: LegalSection[]
}

export interface SiteChrome {
  skipToContent: string
  notConfigured: string
  menu: string
  close: string
  carouselPrev: string
  carouselNext: string
  carouselPrevLabel: string
  carouselNextLabel: string
  carouselLabel: string
  faqHeading: string
  notFoundTitle: string
  notFoundDescription: string
  notFoundBody: string
  notFoundBack: string
  updated: string
  readMore: string
  pagesLabel: string
  breadcrumbHome: string
}

export interface SiteContent {
  site: {
    name: string
    owner: string
    role: string
    title: string
    url: string
    email: string
    tagline: string
    description: string
    keywords: string[]
    updated: string
  }
  chrome: SiteChrome
  hero: {
    kicker: string
    headline: string
    summary: string
    scrollLabel: string
  }
  whoIAm: {
    heading: string
    paragraphs: string[]
  }
  whatIDo: {
    heading: string
    intro: string
    services: Service[]
    skills: string[]
  }
  projects: {
    heading: string
    intro: string
    items: ProjectItem[]
  }
  contact: {
    heading: string
    intro: string
  }
  cta: CallToAction
  faq: FaqItem[]
  pages: ContentPage[]
  legal: {
    privacy: LegalDocument
    terms: LegalDocument
  }
}

/** Rejects a content module that is missing a key `SiteContent` requires. */
export function asSiteContent(value: SiteContent): SiteContent {
  return value
}

export const defaultSiteContent = asSiteContent(bundled)

export function findPage(content: SiteContent, slug: string): ContentPage | undefined {
  return content.pages.find((page) => page.slug === slug)
}
