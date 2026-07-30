import { describe, expect, it } from 'vitest'
import { endDateAfterStartDateChange } from './CalendarNewEventView'

describe('calendar event date following', () => {
  it('keeps a same-day event on the newly selected start date', () => {
    expect(endDateAfterStartDateChange('2026-07-30', '2026-08-15', '2026-07-30')).toBe(
      '2026-08-15',
    )
  })

  it('moves the end date backward together with the start date', () => {
    expect(endDateAfterStartDateChange('2026-08-15', '2026-08-10', '2026-08-15')).toBe(
      '2026-08-10',
    )
  })

  it('preserves the day span of a multi-day event', () => {
    expect(endDateAfterStartDateChange('2026-07-30', '2026-08-15', '2026-08-01')).toBe(
      '2026-08-17',
    )
  })

  it('initializes an empty end date from the selected start date', () => {
    expect(endDateAfterStartDateChange('2026-07-30', '2026-08-15', '')).toBe(
      '2026-08-15',
    )
  })
})
