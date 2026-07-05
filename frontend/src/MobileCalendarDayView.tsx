import { useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties, TouchEvent } from 'react'
import { t } from './i18n'
import { AppLink } from './navigation'
import { getGoogleGmailStatus, listCalendarDbEvents, listGoogleCalendars } from './phase4Api'
import type { GoogleCalendarEvent, GoogleCalendarListItem } from './phase4Api'
import './MobileTopView.css'
import './MobileCalendarDayView.css'

const CALENDAR_SOURCE_STORAGE_KEY = 'caseclosed.calendar.selectedCalendarIds'
const DAY_GRID_HOUR_HEIGHT = 48
const DAY_GRID_START_MINUTES = 6 * 60
const DAY_GRID_END_MINUTES = 21 * 60

function jstDateToday() {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Tokyo',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
    .formatToParts(new Date())
    .reduce<Record<string, string>>((values, part) => {
      values[part.type] = part.value
      return values
    }, {})

  return `${parts.year}-${parts.month}-${parts.day}`
}

function jstTimeParts(date: Date) {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Tokyo',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  })
    .formatToParts(date)
    .reduce<Record<string, string>>((values, part) => {
      values[part.type] = part.value
      return values
    }, {})
}

function validDateOrToday(value: string | null) {
  return value !== null && /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : jstDateToday()
}

function dateParts(date: string) {
  const [year, month, day] = date.split('-').map(Number)
  return { year, month, day }
}

function formatDate(year: number, month: number, day: number) {
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

function addDays(date: string, amount: number) {
  const { year, month, day } = dateParts(date)
  const nextDate = new Date(Date.UTC(year, month - 1, day + amount))
  return formatDate(nextDate.getUTCFullYear(), nextDate.getUTCMonth() + 1, nextDate.getUTCDate())
}

function startOfDate(date: string) {
  return `${date}T00:00:00+09:00`
}

function startOfNextDate(date: string) {
  return `${addDays(date, 1)}T00:00:00+09:00`
}

function eventStartValue(event: GoogleCalendarEvent) {
  return typeof event.start.dateTime === 'string'
    ? event.start.dateTime
    : typeof event.start.date === 'string'
      ? event.start.date
      : ''
}

function eventEndValue(event: GoogleCalendarEvent) {
  return typeof event.end.dateTime === 'string'
    ? event.end.dateTime
    : typeof event.end.date === 'string'
      ? event.end.date
      : ''
}

function eventDisplayDates(event: GoogleCalendarEvent) {
  const startDate = eventStartValue(event).slice(0, 10)
  if (startDate === '') return []
  const isAllDay = typeof event.start.date === 'string' && typeof event.start.dateTime !== 'string'
  const endDate = typeof event.end.date === 'string' ? event.end.date.slice(0, 10) : ''
  if (!isAllDay || endDate === '' || endDate <= addDays(startDate, 1)) return [startDate]
  const dates: string[] = []
  for (let date = startDate; date < endDate; date = addDays(date, 1)) {
    dates.push(date)
  }
  return dates
}

function eventTime(event: GoogleCalendarEvent) {
  const startValue = eventStartValue(event)
  const endValue = eventEndValue(event)
  if (startValue.length <= 10) return t('calendar.allDay')
  const endTime = endValue.length > 10 ? endValue.slice(11, 16) : ''
  return endTime === '' ? startValue.slice(11, 16) : `${startValue.slice(11, 16)}-${endTime}`
}

function eventStartMinutes(event: GoogleCalendarEvent) {
  const value = typeof event.start.dateTime === 'string' ? event.start.dateTime : ''
  if (value.length <= 10) return null
  const hour = Number(value.slice(11, 13))
  const minute = Number(value.slice(14, 16))
  return Number.isFinite(hour) && Number.isFinite(minute) ? hour * 60 + minute : null
}

function eventEndMinutes(event: GoogleCalendarEvent) {
  const value = typeof event.end.dateTime === 'string' ? event.end.dateTime : ''
  if (value.length <= 10) return null
  const hour = Number(value.slice(11, 13))
  const minute = Number(value.slice(14, 16))
  return Number.isFinite(hour) && Number.isFinite(minute) ? hour * 60 + minute : null
}

function eventStartSortKey(event: GoogleCalendarEvent) {
  const start = eventStartValue(event)
  const value = start.length <= 10 ? `${start}T00:00:00+09:00` : start
  const time = Date.parse(value)
  return Number.isFinite(time) ? time : Number.POSITIVE_INFINITY
}

function eventEndSortKey(event: GoogleCalendarEvent) {
  const end = eventEndValue(event)
  const value = end.length <= 10 ? `${end}T00:00:00+09:00` : end
  const time = Date.parse(value)
  return Number.isFinite(time) ? time : Number.POSITIVE_INFINITY
}

function isEventPast(event: GoogleCalendarEvent, now: Date) {
  return eventEndSortKey(event) < now.getTime()
}

function isAttendanceOptional(event: GoogleCalendarEvent) {
  const value = (event.attendance_requirement ?? '').toLowerCase().trim()
  return ['optional', 'not_required', 'unnecessary', 'no_attendance'].includes(value)
}

function sortEvents(events: GoogleCalendarEvent[]) {
  return [...events].sort(
    (left, right) =>
      eventStartSortKey(left) - eventStartSortKey(right) ||
      eventEndSortKey(left) - eventEndSortKey(right) ||
      (left.summary || '').localeCompare(right.summary || ''),
  )
}

function displayDate(date: string) {
  const [year, month, day] = date.split('-').map(Number)
  const value = new Date(Date.UTC(year, month - 1, day))
  return new Intl.DateTimeFormat('ja-JP', {
    timeZone: 'UTC',
    month: 'long',
    day: 'numeric',
    weekday: 'short',
  }).format(value)
}

function eventHref(event: GoogleCalendarEvent, date: string) {
  if (event.id === null) return `/m/calendar?date=${date}`
  const returnTo = `/m/calendar?date=${date}`
  return `/calendar/events/${encodeURIComponent(event.id)}?return_to=${encodeURIComponent(returnTo)}`
}

function calendarSourceTone(calendarId: string | null | undefined, calendars: GoogleCalendarListItem[]) {
  const id = calendarId ?? 'primary'
  const calendar = calendars.find((item) => item.id === id)
  return calendar?.primary === true || id === 'primary' ? 'main' : 'secondary'
}


function initialSelectedCalendarIds() {
  try {
    const rawValue = window.localStorage.getItem(CALENDAR_SOURCE_STORAGE_KEY)
    if (rawValue === null) return ['primary']
    const parsedValue: unknown = JSON.parse(rawValue)
    if (
      Array.isArray(parsedValue) &&
      parsedValue.every((item) => typeof item === 'string') &&
      parsedValue.length > 0
    ) {
      return parsedValue
    }
  } catch {
    // Fall back to the primary calendar if local storage is unavailable or stale.
  }
  return ['primary']
}

type PositionedEvent = {
  event: GoogleCalendarEvent
  top: number
  height: number
  laneOffsetRatio: number
  laneWidthRatio: number
  laneCount: number
  isShort: boolean
}

function positionTimedEvents(events: GoogleCalendarEvent[]): PositionedEvent[] {
  const base = events
    .map((event) => {
      const start = eventStartMinutes(event)
      const end = eventEndMinutes(event)
      if (start === null || end === null) return null
      if (end <= DAY_GRID_START_MINUTES || start >= DAY_GRID_END_MINUTES) return null
      const clampedStart = Math.max(start, DAY_GRID_START_MINUTES)
      const clampedEnd = Math.min(Math.max(end, start + 15), DAY_GRID_END_MINUTES)
      return {
        event,
        startMinute: clampedStart,
        endMinute: clampedEnd,
        top: ((clampedStart - DAY_GRID_START_MINUTES) / 60) * DAY_GRID_HOUR_HEIGHT,
        height: Math.max(22, ((clampedEnd - clampedStart) / 60) * DAY_GRID_HOUR_HEIGHT - 4),
        isShort: clampedEnd - clampedStart < 60,
      }
    })
    .filter((item): item is NonNullable<typeof item> => item !== null)
    .sort(
      (left, right) =>
        left.startMinute - right.startMinute ||
        right.endMinute - right.startMinute - (left.endMinute - left.startMinute),
    )

  const clusters: typeof base[] = []
  base.forEach((item) => {
    const activeCluster = clusters.at(-1)
    if (activeCluster === undefined || item.startMinute >= Math.max(...activeCluster.map((event) => event.endMinute))) {
      clusters.push([item])
    } else {
      activeCluster.push(item)
    }
  })

  return clusters.flatMap((cluster) => {
    const laneEnds: number[] = []
    const withLanes = cluster.map((item) => {
      let lane = laneEnds.findIndex((endMinute) => endMinute <= item.startMinute)
      if (lane < 0) lane = laneEnds.length
      laneEnds[lane] = item.endMinute
      return { ...item, lane }
    })
    const laneCount = Math.max(1, laneEnds.length)
    const hasOptional = withLanes.some((item) => isAttendanceOptional(item.event))
    const hasRequired = withLanes.some((item) => !isAttendanceOptional(item.event))
    const laneHasRequired = Array.from({ length: laneCount }, (_, lane) =>
      withLanes.some((item) => item.lane === lane && !isAttendanceOptional(item.event)),
    )
    const laneWeights =
      laneCount === 2 && hasOptional && hasRequired
        ? laneHasRequired.map((hasRequiredEvent) => (hasRequiredEvent ? 3 : 1))
        : Array.from({ length: laneCount }, () => 1)
    const totalWeight = laneWeights.reduce((sum, value) => sum + value, 0)
    const laneOffsets = laneWeights.map((_, lane) =>
      laneWeights.slice(0, lane).reduce((sum, value) => sum + value, 0),
    )
    return withLanes.map((item) => ({
      event: item.event,
      top: item.top,
      height: item.height,
      laneCount,
      laneOffsetRatio: laneOffsets[item.lane] / totalWeight,
      laneWidthRatio: laneWeights[item.lane] / totalWeight,
      isShort: item.isShort,
    }))
  })
}

export default function MobileCalendarDayView() {
  const today = useMemo(() => jstDateToday(), [])
  const [date, setDate] = useState(() => validDateOrToday(new URLSearchParams(window.location.search).get('date')))
  const [now, setNow] = useState(() => new Date())
  const [events, setEvents] = useState<GoogleCalendarEvent[]>([])
  const [calendars, setCalendars] = useState<GoogleCalendarListItem[]>([])
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const touchStartXRef = useRef<number | null>(null)
  const touchStartYRef = useRef<number | null>(null)

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (params.get('date') !== date) {
      params.set('date', date)
      window.history.replaceState({}, '', `/m/calendar?${params.toString()}`)
    }
  }, [date])

  useEffect(() => {
    const timerId = window.setInterval(() => setNow(new Date()), 60000)
    return () => window.clearInterval(timerId)
  }, [])

  useEffect(() => {
    let isMounted = true
    setIsLoading(true)
    setError(null)
    Promise.all([getGoogleGmailStatus(), listGoogleCalendars()])
      .then(async ([status, calendarItems]) => {
        if (!isMounted) return
        setCalendars(calendarItems)
        if (status.connected !== true || status.calendar_read_enabled !== true) {
          setEvents([])
          setError(status.connected === true ? t('mobile.calendar.readScopeMissing') : t('mobile.google.notConnected'))
          return
        }

        const validIds = new Set(calendarItems.map((calendar) => calendar.id))
        const primaryCalendarId = calendarItems.find((calendar) => calendar.primary)?.id ?? 'primary'
        const localIds = initialSelectedCalendarIds()
        const serverIds = status.calendar_auto_sync.calendar_ids
        const candidateIds = localIds.length === 1 && localIds[0] === 'primary' ? serverIds : localIds
        const nextCalendarIds = candidateIds.filter((id) => validIds.has(id))
        if (nextCalendarIds.length === 0) {
          nextCalendarIds.push(primaryCalendarId)
        }

        const page = await listCalendarDbEvents({
          calendar_id: nextCalendarIds,
          time_min: startOfDate(date),
          time_max: startOfNextDate(date),
        })
        if (!isMounted) return
        setEvents(sortEvents(page.items.filter((event) => eventDisplayDates(event).includes(date))))
      })
      .catch((requestError) => {
        if (!isMounted) return
        setError(requestError instanceof Error ? requestError.message : t('mobile.calendar.loadFailed'))
      })
      .finally(() => {
        if (isMounted) setIsLoading(false)
      })
    return () => {
      isMounted = false
    }
  }, [date])

  const allDayEvents = useMemo(
    () => events.filter((event) => eventStartMinutes(event) === null || eventEndMinutes(event) === null),
    [events],
  )
  const timedEvents = useMemo(
    () => events.filter((event) => eventStartMinutes(event) !== null && eventEndMinutes(event) !== null),
    [events],
  )
  const positionedEvents = useMemo(() => positionTimedEvents(timedEvents), [timedEvents])
  const hours = useMemo(
    () => Array.from({ length: (DAY_GRID_END_MINUTES - DAY_GRID_START_MINUTES) / 60 }, (_, index) => 6 + index),
    [],
  )
  const currentTimeParts = jstTimeParts(now)
  const currentMinuteOfDay = Number(currentTimeParts.hour ?? 0) * 60 + Number(currentTimeParts.minute ?? 0)
  const shouldShowNowLine =
    date === today && currentMinuteOfDay >= DAY_GRID_START_MINUTES && currentMinuteOfDay <= DAY_GRID_END_MINUTES
  const nowLineTop = ((currentMinuteOfDay - DAY_GRID_START_MINUTES) / 60) * DAY_GRID_HOUR_HEIGHT

  function moveDate(amount: number) {
    setDate((current) => addDays(current, amount))
  }

  function handleTouchStart(event: TouchEvent<HTMLElement>) {
    const touch = event.touches[0]
    touchStartXRef.current = touch.clientX
    touchStartYRef.current = touch.clientY
  }

  function handleTouchEnd(event: TouchEvent<HTMLElement>) {
    const startX = touchStartXRef.current
    const startY = touchStartYRef.current
    touchStartXRef.current = null
    touchStartYRef.current = null
    if (startX === null || startY === null) return
    const touch = event.changedTouches[0]
    const dx = touch.clientX - startX
    const dy = touch.clientY - startY
    if (Math.abs(dx) < 54 || Math.abs(dx) < Math.abs(dy) * 1.4) return
    moveDate(dx < 0 ? 1 : -1)
  }

  return (
    <main className="mobile-shell mobile-calendar-shell" onTouchEnd={handleTouchEnd} onTouchStart={handleTouchStart}>
      <header className="mobile-topbar mobile-calendar-topbar">
        <div>
          <p>{t('calendar.heading')}</p>
          <h1>{displayDate(date)}</h1>
        </div>
        <AppLink className="mobile-topbar-link" href="/m?view=mobile">
          {t('top.heading')}
        </AppLink>
      </header>

      <nav aria-label="Day navigation" className="mobile-day-switcher">
        <button type="button" onClick={() => moveDate(-1)}>{t('common.previousDay')}</button>
        <button type="button" onClick={() => setDate(today)}>{t('calendar.today')}</button>
        <button type="button" onClick={() => moveDate(1)}>{t('common.nextDay')}</button>
      </nav>

      <p className="mobile-swipe-hint">{t('mobile.swipeDayHint')}</p>

      {error !== null && <p className="mobile-alert" role="alert">{error}</p>}
      {isLoading ? <p className="mobile-loading">{t('common.loading')}</p> : null}

      {!isLoading && error === null ? (
        <>

          {events.length === 0 ? (
            <section className="mobile-panel">
              <p className="mobile-empty">{t('mobile.calendar.emptyDay')}</p>
            </section>
          ) : null}

          {allDayEvents.length > 0 ? (
            <section className="mobile-calendar-all-day" aria-label={t('calendar.allDay')}>
              <h2>{t('calendar.allDay')}</h2>
              <div>
                {allDayEvents.map((event) => (
                  <AppLink
                    className={`mobile-calendar-all-day-chip source-${calendarSourceTone(event.calendar_source_id, calendars)}${
                      isEventPast(event, now) || isAttendanceOptional(event) ? ' is-muted' : ''
                    }`}
                    href={eventHref(event, date)}
                    key={event.id ?? `${event.summary}-${eventTime(event)}`}
                  >
                    {event.summary || t('mobile.noTitle')}
                  </AppLink>
                ))}
              </div>
            </section>
          ) : null}

          <section className="mobile-day-timeline" aria-label={t('mobile.calendar.dayTimeline')}>
            <div className="mobile-day-grid" style={{ '--mobile-day-grid-height': `${hours.length * DAY_GRID_HOUR_HEIGHT}px` } as CSSProperties}>
              {shouldShowNowLine ? <span aria-hidden="true" className="mobile-calendar-now-line" style={{ top: `${nowLineTop}px` }} /> : null}
              {hours.map((hour) => (
                <div className="mobile-day-row" key={hour}>
                  <time>{String(hour).padStart(2, '0')}:00</time>
                  <span />
                </div>
              ))}
              {positionedEvents.map(({ event, top, height, laneCount, laneOffsetRatio, laneWidthRatio, isShort }) => {
                const title = event.summary || t('mobile.noTitle')
                return (
                  <AppLink
                    className={`mobile-day-event source-${calendarSourceTone(event.calendar_source_id, calendars)}${
                      laneCount > 1 || isShort ? ' is-narrow' : ''
                    }${isEventPast(event, now) || isAttendanceOptional(event) ? ' is-muted' : ''}`}
                    href={eventHref(event, date)}
                    key={event.id ?? `${eventStartValue(event)}-${title}`}
                    style={{
                      top: `${top}px`,
                      left: `calc(48px + ((100% - 48px) * ${laneOffsetRatio}) + 3px)`,
                      width: `calc(((100% - 48px) * ${laneWidthRatio}) - 6px)`,
                      height: `${height}px`,
                    }}
                  >
                    <strong>{title}</strong>
                    <span>{eventTime(event)}</span>
                  </AppLink>
                )
              })}
            </div>
          </section>

          {events.length > 0 ? (
            <section className="mobile-panel mobile-calendar-day-section">
              <h2>{t('mobile.calendar.listHeading')}</h2>
              <ol className="mobile-agenda-list mobile-day-agenda-list">
                {events.map((event) => (
                  <li key={event.id ?? `${event.summary}-${eventTime(event)}`}>
                    <AppLink href={eventHref(event, date)}>
                      <time>{eventTime(event)}</time>
                      <strong>{event.summary || t('mobile.noTitle')}</strong>
                    </AppLink>
                  </li>
                ))}
              </ol>
            </section>
          ) : null}
        </>
      ) : null}

      <nav aria-label="Mobile navigation" className="mobile-nav-grid">
        <AppLink href="/m?view=mobile">{t('top.heading')}</AppLink>
        <AppLink href="/today">{t('nav.today')}</AppLink>
        <AppLink href={`/calendar?date=${date}`}>PC {t('calendar.heading')}</AppLink>
      </nav>
    </main>
  )
}
