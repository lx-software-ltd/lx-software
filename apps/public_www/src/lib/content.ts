import bundled from '../../public/content.json'

export interface Service {
  title: string
  description: string
}

export interface ProjectItem {
  title: string
  description: string
  ascii: string[]
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

export interface SiteContent {
  keyboardSections: boolean
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
  faq: FaqItem[]
  legal: {
    privacy: LegalDocument
    terms: LegalDocument
  }
}

export const defaultSiteContent = bundled as SiteContent

export async function fetchSiteContent(): Promise<SiteContent> {
  const response = await fetch('/content.json')
  if (!response.ok) {
    throw new Error(`Failed to fetch site content: ${response.status}`)
  }
  return response.json() as Promise<SiteContent>
}
