import { describe, it, expect } from 'vitest'
import { codeFromInput, shareUrl } from './shareCode'

describe('shareCode', () => {
  it('extracts a code from a raw value or a share URL', () => {
    expect(codeFromInput('01234567')).toBe('01234567')
    expect(codeFromInput('  ABCD1234  ')).toBe('ABCD1234')
    expect(codeFromInput('https://x.test/manufacturing?job=01234567&foo=1')).toBe('01234567')
    expect(codeFromInput(shareUrl('07654321'))).toBe('07654321')
  })

  it('rejects junk / oversized input', () => {
    expect(codeFromInput('not a code with spaces')).toBe('')
    expect(codeFromInput('')).toBe('')
    expect(codeFromInput(null)).toBe('')
    expect(codeFromInput('thisistoolongtobeacode')).toBe('')
  })
})
