import { describe, expect, it } from 'vitest'
import { linkedinUrl } from './linkedin'

describe('linkedinUrl', () => {
  it('returns an empty string when unset', () => {
    expect(linkedinUrl(undefined)).toBe('')
    expect(linkedinUrl('  ')).toBe('')
    expect(linkedinUrl('/')).toBe('')
  })

  it('expands a bare slug or in/ path', () => {
    expect(linkedinUrl('sample-owner')).toBe('https://www.linkedin.com/in/sample-owner')
    expect(linkedinUrl('/in/sample-owner/')).toBe('https://www.linkedin.com/in/sample-owner')
    expect(linkedinUrl('company/example-studio')).toBe(
      'https://www.linkedin.com/company/example-studio',
    )
  })

  it('normalises a full URL and drops tracking parameters', () => {
    expect(linkedinUrl('http://hk.linkedin.com/in/sample-owner/?utm=x#top')).toBe(
      'https://hk.linkedin.com/in/sample-owner',
    )
  })

  it('rejects hosts that are not linkedin.com', () => {
    expect(linkedinUrl('https://example.com/in/sample-owner')).toBe('')
    expect(linkedinUrl('https://notlinkedin.com/in/x')).toBe('')
  })
})
