import { describe, expect, it } from 'vitest'
import { closestAvailableNoonSlot, endDateAfterStartDateChange } from './CalendarNewEventView'
import type { GoogleCalendarEvent } from './phase4Api'

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


function timedEvent(start: string, end: string, status: string | null = "confirmed"): GoogleCalendarEvent {
  return {
    id: "event_test",
    summary: "Busy",
    description: null,
    location: null,
    html_link: null,
    start: { dateTime: start },
    end: { dateTime: end },
    status,
    created: null,
    updated: null,
  }
}

describe("calendar event noon availability", () => {
  it("uses noon when the selected day is open", () => {
    expect(closestAvailableNoonSlot([], "2026-08-15")).toEqual({
      startTime: "12:00",
      endTime: "13:00",
    })
  })

  it("chooses the closest later one-hour slot when noon is occupied", () => {
    const events = [
      timedEvent("2026-08-15T12:00:00+09:00", "2026-08-15T13:00:00+09:00"),
    ]
    expect(closestAvailableNoonSlot(events, "2026-08-15")).toEqual({
      startTime: "13:00",
      endTime: "14:00",
    })
  })

  it("ignores cancelled events", () => {
    const events = [
      timedEvent(
        "2026-08-15T12:00:00+09:00",
        "2026-08-15T13:00:00+09:00",
        "cancelled",
      ),
    ]
    expect(closestAvailableNoonSlot(events, "2026-08-15").startTime).toBe("12:00")
  })
})
