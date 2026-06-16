import { describe, expect, it } from 'vitest'
import { toJstIsoDateTime } from './phase4Api'

describe('calendar datetime API formatting', () => {
  it('normalizes datetime-local values to the canonical JST offset form', () => {
    expect(toJstIsoDateTime('2026-06-10T10:00')).toBe('2026-06-10T10:00:00+09:00')
    expect(toJstIsoDateTime('2026-06-10T10:00:30')).toBe(
      '2026-06-10T10:00:30+09:00',
    )
  })

  it('keeps already offset-qualified datetime values', () => {
    expect(toJstIsoDateTime('2026-06-10T10:00:00+09:00')).toBe(
      '2026-06-10T10:00:00+09:00',
    )
  })
})
