export const pageSections = [
  { id: 'who-i-am', label: 'Who I Am' },
  { id: 'what-i-do', label: 'What I Do' },
  { id: 'projects', label: 'Projects' },
  { id: 'contact', label: 'Contact Me' },
] as const

export type SectionId = (typeof pageSections)[number]['id']
