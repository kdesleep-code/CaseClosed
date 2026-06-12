import { useEffect, useMemo, useState } from 'react'
import type { DragEvent } from 'react'
import {
  getGoogleGmailStatus,
  listCalendarDbEvents,
  listGoogleCalendars,
  moveCalendarDbEvent,
  syncGoogleCalendarEvents,
} from './phase4Api'
import type { GoogleCalendarEvent, GoogleCalendarListItem } from './phase4Api'
import { t } from './i18n'
import { AppLink } from './navigation'

type CalendarEventWithSource = GoogleCalendarEvent & {
  calendar_source_id?: string | null
}

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

function dateParts(date: string) {
  const [year, month, day] = date.split('-').map(Number)
  return { year, month, day }
}

function formatCalendarDate(year: number, month: number, day: number) {
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

function addMonths(date: string, amount: number) {
  const { year, month } = dateParts(date)
  const nextDate = new Date(Date.UTC(year, month - 1 + amount, 1))
  return formatCalendarDate(nextDate.getUTCFullYear(), nextDate.getUTCMonth() + 1, 1)
}

function addDays(date: string, amount: number) {
  const { year, month, day } = dateParts(date)
  const nextDate = new Date(Date.UTC(year, month - 1, day + amount))
  return formatCalendarDate(
    nextDate.getUTCFullYear(),
    nextDate.getUTCMonth() + 1,
    nextDate.getUTCDate(),
  )
}

function monthRange(date: string) {
  const { year, month } = dateParts(date)
  const start = formatCalendarDate(year, month, 1)
  const nextMonth = addMonths(start, 1)
  return {
    start,
    end: nextMonth,
    timeMin: `${start}T00:00:00+09:00`,
    timeMax: `${nextMonth}T00:00:00+09:00`,
  }
}

function weekRange(date: string) {
  const { year, month, day } = dateParts(date)
  const current = new Date(Date.UTC(year, month - 1, day))
  const start = new Date(current)
  start.setUTCDate(current.getUTCDate() - current.getUTCDay())
  const end = new Date(start)
  end.setUTCDate(start.getUTCDate() + 7)
  return {
    start: formatCalendarDate(
      start.getUTCFullYear(),
      start.getUTCMonth() + 1,
      start.getUTCDate(),
    ),
    end: formatCalendarDate(end.getUTCFullYear(), end.getUTCMonth() + 1, end.getUTCDate()),
  }
}

function weekDays(date: string) {
  const range = weekRange(date)
  const { year, month, day } = dateParts(range.start)
  const start = new Date(Date.UTC(year, month - 1, day))
  return Array.from({ length: 7 }, (_, index) => {
    const next = new Date(start)
    next.setUTCDate(start.getUTCDate() + index)
    return formatCalendarDate(
      next.getUTCFullYear(),
      next.getUTCMonth() + 1,
      next.getUTCDate(),
    )
  })
}

function calendarDays(date: string) {
  const { year, month } = dateParts(date)
  const firstDay = new Date(Date.UTC(year, month - 1, 1))
  const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate()
  return [
    ...Array.from({ length: firstDay.getUTCDay() }, () => null),
    ...Array.from({ length: daysInMonth }, (_, index) =>
      formatCalendarDate(year, month, index + 1),
    ),
  ]
}

function calendarEventDate(event: GoogleCalendarEvent) {
  const start = event.start
  const value =
    typeof start.dateTime === 'string'
      ? start.dateTime
      : typeof start.date === 'string'
        ? start.date
        : ''
  return value.slice(0, 10)
}

function calendarSourceTone(calendarId: string, calendars: GoogleCalendarListItem[]) {
  const calendar = calendars.find((item) => item.id === calendarId)
  return calendar?.primary === true || calendarId === 'primary' ? 'main' : 'secondary'
}

function calendarEventDisplayDates(event: GoogleCalendarEvent) {
  const startDate = calendarEventDate(event)
  if (startDate === '') {
    return []
  }
  const start = event.start
  const end = event.end
  const isAllDay = typeof start.date === 'string' && typeof start.dateTime !== 'string'
  const endDate = typeof end.date === 'string' ? end.date.slice(0, 10) : ''
  if (!isAllDay || endDate === '' || endDate <= addDays(startDate, 1)) {
    return [startDate]
  }
  const dates: string[] = []
  for (let date = startDate; date < endDate; date = addDays(date, 1)) {
    dates.push(date)
  }
  return dates
}

function calendarEventTime(event: GoogleCalendarEvent) {
  const start = event.start
  const end = event.end
  const startValue =
    typeof start.dateTime === 'string'
      ? start.dateTime
      : typeof start.date === 'string'
        ? start.date
        : ''
  const endValue =
    typeof end.dateTime === 'string'
      ? end.dateTime
      : typeof end.date === 'string'
        ? end.date
        : ''
  if (startValue.length <= 10) {
    return t('calendar.allDay')
  }
  const startTime = startValue.slice(11, 16)
  const endTime = endValue.length > 10 ? endValue.slice(11, 16) : ''
  return endTime === '' ? startTime : `${startTime}-${endTime}`
}

function calendarEventStartMinutes(event: GoogleCalendarEvent) {
  const value = typeof event.start.dateTime === 'string' ? event.start.dateTime : ''
  if (value.length <= 10) {
    return null
  }
  const hour = Number(value.slice(11, 13))
  const minute = Number(value.slice(14, 16))
  if (!Number.isFinite(hour) || !Number.isFinite(minute)) {
    return null
  }
  return hour * 60 + minute
}

function calendarEventEndMinutes(event: GoogleCalendarEvent) {
  const value = typeof event.end.dateTime === 'string' ? event.end.dateTime : ''
  if (value.length <= 10) {
    return null
  }
  const hour = Number(value.slice(11, 13))
  const minute = Number(value.slice(14, 16))
  if (!Number.isFinite(hour) || !Number.isFinite(minute)) {
    return null
  }
  return hour * 60 + minute
}

function calendarEventStartSortKey(event: GoogleCalendarEvent) {
  const start = event.start
  const value =
    typeof start.dateTime === 'string'
      ? start.dateTime
      : typeof start.date === 'string'
        ? `${start.date}T00:00:00+09:00`
        : ''
  const time = Date.parse(value)
  return Number.isFinite(time) ? time : Number.POSITIVE_INFINITY
}

function calendarEventEndSortKey(event: GoogleCalendarEvent) {
  const end = event.end
  const value =
    typeof end.dateTime === 'string'
      ? end.dateTime
      : typeof end.date === 'string'
        ? `${end.date}T00:00:00+09:00`
        : ''
  const time = Date.parse(value)
  return Number.isFinite(time) ? time : Number.POSITIVE_INFINITY
}

function isCalendarEventPast(event: GoogleCalendarEvent, now: Date) {
  return calendarEventEndSortKey(event) < now.getTime()
}

function isCalendarEventAttendanceOptional(event: GoogleCalendarEvent) {
  const value = (event.attendance_requirement ?? '').toLowerCase().trim()
  return ['optional', 'not_required', 'unnecessary', 'no_attendance'].includes(value)
}

const WEEK_GRID_HEADER_HEIGHT = 48
const WEEK_GRID_HOUR_HEIGHT = 45
const WEEK_GRID_START_MINUTES = 6 * 60
const WEEK_GRID_END_MINUTES = 21 * 60
const WEEK_GRID_DROP_STEP_MINUTES = 15

function formatMinutes(minutes: number) {
  const hour = Math.floor(minutes / 60)
  const minute = minutes % 60
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`
}

function formatJstLocalDateTime(date: Date) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Tokyo',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  })
    .formatToParts(date)
    .reduce<Record<string, string>>((values, part) => {
      values[part.type] = part.value
      return values
    }, {})
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`
}
const CALENDAR_SOURCE_STORAGE_KEY = 'caseclosed.calendar.selectedCalendarIds'

function initialSelectedCalendarIds() {
  try {
    const rawValue = window.localStorage.getItem(CALENDAR_SOURCE_STORAGE_KEY)
    if (rawValue === null) {
      return ['primary']
    }
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

function CalendarView() {
  const today = useMemo(() => jstDateToday(), [])
  const [now, setNow] = useState(() => new Date())
  const [calendarMonth, setCalendarMonth] = useState(today.slice(0, 7) + '-01')
  const [selectedDate, setSelectedDate] = useState(today)
  const [events, setEvents] = useState<CalendarEventWithSource[]>([])
  const [calendars, setCalendars] = useState<GoogleCalendarListItem[]>([])
  const [selectedCalendarIds, setSelectedCalendarIds] = useState<string[]>(
    initialSelectedCalendarIds,
  )
  const [isCalendarSourceOpen, setIsCalendarSourceOpen] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [isSyncing, setIsSyncing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [canRead, setCanRead] = useState(false)
  const [feedback, setFeedback] = useState<string | null>(null)
  const [dragPreview, setDragPreview] = useState<{
    dayIndex: number
    top: number
    height: number
    label: string
  } | null>(null)
  const [draggedEventId, setDraggedEventId] = useState<string | null>(null)
  const [dragGrabOffsetMinutes, setDragGrabOffsetMinutes] = useState(0)

  const selectedMonthDays = useMemo(() => calendarDays(calendarMonth), [calendarMonth])
  const selectedWeekDays = useMemo(() => weekDays(selectedDate), [selectedDate])
  const weekLabel = `${selectedWeekDays[0]} - ${selectedWeekDays[6]}`
  const weekHours = useMemo(
    () => Array.from({ length: 16 }, (_, index) => 6 + index),
    [],
  )
  const eventsByDate = useMemo(() => {
    const grouped = new Map<string, CalendarEventWithSource[]>()
    events.forEach((event) => {
      calendarEventDisplayDates(event).forEach((date) => {
        grouped.set(date, [...(grouped.get(date) ?? []), event])
      })
    })
    return grouped
  }, [events])
  const selectedEventOccurrences = selectedWeekDays.flatMap((date) =>
    (eventsByDate.get(date) ?? []).map((event) => ({ event, displayDate: date })),
  )
  const selectedEvents = selectedEventOccurrences.map((occurrence) => occurrence.event)
  const currentTimeParts = jstTimeParts(now)
  const currentMinuteOfDay =
    Number(currentTimeParts.hour ?? 0) * 60 + Number(currentTimeParts.minute ?? 0)
  const shouldShowNowLine =
    selectedWeekDays.includes(today) &&
    currentMinuteOfDay >= WEEK_GRID_START_MINUTES &&
    currentMinuteOfDay <= WEEK_GRID_END_MINUTES
  const nowLineTop =
    WEEK_GRID_HEADER_HEIGHT +
    ((currentMinuteOfDay - WEEK_GRID_START_MINUTES) / 60) * WEEK_GRID_HOUR_HEIGHT
  const todayColumnIndex = selectedWeekDays.indexOf(today)
  const positionedWeekEventBase = selectedEventOccurrences
    .map(({ event, displayDate }) => {
      const date = displayDate
      const dayIndex = selectedWeekDays.indexOf(date)
      if (dayIndex < 0) {
        return null
      }
      const start = calendarEventStartMinutes(event)
      const end = calendarEventEndMinutes(event)
      const isAllDay = start === null || end === null
      const rawStart = start ?? WEEK_GRID_START_MINUTES
      const rawEnd = end ?? Math.min(rawStart + 60, WEEK_GRID_END_MINUTES)
      if (rawEnd <= WEEK_GRID_START_MINUTES || rawStart >= WEEK_GRID_END_MINUTES) {
        return null
      }
      const clampedStart = Math.max(rawStart, WEEK_GRID_START_MINUTES)
      const clampedEnd = Math.min(Math.max(rawEnd, rawStart + 15), WEEK_GRID_END_MINUTES)
      const top =
        WEEK_GRID_HEADER_HEIGHT +
        ((clampedStart - WEEK_GRID_START_MINUTES) / 60) * WEEK_GRID_HOUR_HEIGHT
      const height = Math.max(
        18,
        ((clampedEnd - clampedStart) / 60) * WEEK_GRID_HOUR_HEIGHT - 4,
      )
      return {
        event,
        dayIndex,
        startMinute: clampedStart,
        endMinute: clampedEnd,
        top: isAllDay ? WEEK_GRID_HEADER_HEIGHT + 4 : top,
        height: isAllDay
          ? ((WEEK_GRID_END_MINUTES - WEEK_GRID_START_MINUTES) / 60) *
              WEEK_GRID_HOUR_HEIGHT -
            8
          : height,
        isAllDay,
        isShort: !isAllDay && clampedEnd - clampedStart < 60,
      }
    })
    .filter((item): item is NonNullable<typeof item> => item !== null)
  const positionedWeekEvents = [
    ...positionedWeekEventBase
      .filter((item) => item.isAllDay)
      .map((item) => ({ ...item, lane: 0, laneCount: 1, laneOffsetRatio: 0, laneWidthRatio: 1 })),
    ...selectedWeekDays.flatMap((_, dayIndex) => {
      const dayEvents = positionedWeekEventBase
        .filter((item) => item.dayIndex === dayIndex && !item.isAllDay)
        .sort(
          (left, right) =>
            left.startMinute - right.startMinute ||
            right.endMinute - right.startMinute - (left.endMinute - left.startMinute),
        )
      const clusters: typeof dayEvents[] = []
      dayEvents.forEach((item) => {
        const activeCluster = clusters.at(-1)
        if (
          activeCluster === undefined ||
          item.startMinute >= Math.max(...activeCluster.map((event) => event.endMinute))
        ) {
          clusters.push([item])
        } else {
          activeCluster.push(item)
        }
      })

      return clusters.flatMap((cluster) => {
        const laneEnds: number[] = []
        const withLanes = cluster.map((item) => {
          let lane = laneEnds.findIndex((endMinute) => endMinute <= item.startMinute)
          if (lane < 0) {
            lane = laneEnds.length
          }
          laneEnds[lane] = item.endMinute
          return { ...item, lane }
        })
        const laneCount = Math.max(1, laneEnds.length)
        const hasOptional = withLanes.some((item) => isCalendarEventAttendanceOptional(item.event))
        const hasRequired = withLanes.some((item) => !isCalendarEventAttendanceOptional(item.event))
        const laneHasRequired = Array.from({ length: laneCount }, (_, lane) =>
          withLanes.some(
            (item) => item.lane === lane && !isCalendarEventAttendanceOptional(item.event),
          ),
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
          ...item,
          laneCount,
          laneOffsetRatio: laneOffsets[item.lane] / totalWeight,
          laneWidthRatio: laneWeights[item.lane] / totalWeight,
        }))
      })
    }),
  ]
  const upcomingEvents = events
    .filter((event) => calendarEventEndSortKey(event) >= now.getTime())
    .sort(
      (left, right) =>
        calendarEventStartSortKey(left) - calendarEventStartSortKey(right) ||
        (left.summary || '').localeCompare(right.summary || ''),
    )
    .slice(0, 5)
  const selectedCalendarIdSet = useMemo(
    () => new Set(selectedCalendarIds),
    [selectedCalendarIds],
  )

  async function loadMonthEvents() {
    setError(null)
    setIsLoading(true)
    try {
      const status = await getGoogleGmailStatus()
      setCanRead(status.calendar_read_enabled === true)
      if (status.connected !== true || status.calendar_read_enabled !== true) {
        setEvents([])
        setError(
          status.connected === true
            ? t('calendar.scopeMissing')
          : t('calendar.notConnected'),
        )
        return
      }
      const calendarItems = await listGoogleCalendars()
      setCalendars(calendarItems)
      const validIds = new Set(calendarItems.map((calendar) => calendar.id))
      const nextCalendarIds = selectedCalendarIds.filter((id) => validIds.has(id))
      if (nextCalendarIds.length === 0) {
        const fallbackId =
          calendarItems.find((calendar) => calendar.primary)?.id ??
          calendarItems[0]?.id ??
          'primary'
        nextCalendarIds.push(fallbackId)
      }
      if (nextCalendarIds.join('\n') !== selectedCalendarIds.join('\n')) {
        setSelectedCalendarIds(nextCalendarIds)
      }
      const queryCalendarIds = [...nextCalendarIds]
      const includesPrimaryCalendar = calendarItems.some(
        (calendar) => calendar.primary === true && nextCalendarIds.includes(calendar.id),
      )
      if (includesPrimaryCalendar && !queryCalendarIds.includes('primary')) {
        queryCalendarIds.push('primary')
      }
      const range = monthRange(calendarMonth)
      const eventPages = await listCalendarDbEvents({
        calendar_id: queryCalendarIds,
        time_min: range.timeMin,
        time_max: range.timeMax,
      })
      setEvents(
        eventPages.items
          .sort((left, right) => calendarEventDate(left).localeCompare(calendarEventDate(right))),
      )
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('app.requestFailed'))
    } finally {
      setIsLoading(false)
    }
  }

  async function syncVisibleCalendars() {
    setError(null)
    setFeedback(null)
    setIsSyncing(true)
    try {
      const result = await syncGoogleCalendarEvents({
        calendar_ids: selectedCalendarIds,
        base_date: calendarMonth,
        month_count: 3,
      })
      setFeedback(
        t('calendar.sync.done', {
          imported: String(result.imported_count),
          updated: String(result.updated_count),
        }),
      )
      await loadMonthEvents()
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('app.requestFailed'))
    } finally {
      setIsSyncing(false)
    }
  }

  function weekDropTargetFromDrag(event: DragEvent<HTMLDivElement>, calendarEvent: GoogleCalendarEvent) {
    const startTime = calendarEventStartSortKey(calendarEvent)
    const endTime = calendarEventEndSortKey(calendarEvent)
    if (!Number.isFinite(startTime) || !Number.isFinite(endTime) || endTime <= startTime) {
      return null
    }
    if (calendarEventStartMinutes(calendarEvent) === null || calendarEventEndMinutes(calendarEvent) === null) {
      return null
    }
    const durationMinutes = Math.max(15, Math.round((endTime - startTime) / 60000))
    const grid = event.currentTarget
    const rect = grid.getBoundingClientRect()
    const columnWidth = (rect.width - 58) / 7
    const relativeX = event.clientX - rect.left - 58 + grid.scrollLeft
    const relativeY =
      event.clientY -
      rect.top -
      WEEK_GRID_HEADER_HEIGHT +
      grid.scrollTop -
      (dragGrabOffsetMinutes / 60) * WEEK_GRID_HOUR_HEIGHT
    const dayIndex = Math.floor(relativeX / columnWidth)
    if (dayIndex < 0 || dayIndex >= selectedWeekDays.length || relativeY < 0) {
      return null
    }
    const rawMinutes = WEEK_GRID_START_MINUTES + (relativeY / WEEK_GRID_HOUR_HEIGHT) * 60
    let nextStartMinutes =
      Math.round(rawMinutes / WEEK_GRID_DROP_STEP_MINUTES) * WEEK_GRID_DROP_STEP_MINUTES
    const latestStart = Math.max(
      WEEK_GRID_START_MINUTES,
      WEEK_GRID_END_MINUTES - durationMinutes,
    )
    nextStartMinutes = Math.min(Math.max(nextStartMinutes, WEEK_GRID_START_MINUTES), latestStart)
    const nextDate = selectedWeekDays[dayIndex]
    const nextStart = `${nextDate}T${formatMinutes(nextStartMinutes)}`
    const nextEnd = formatJstLocalDateTime(
      new Date(Date.parse(`${nextStart}:00+09:00`) + durationMinutes * 60_000),
    )
    const top =
      WEEK_GRID_HEADER_HEIGHT +
      ((nextStartMinutes - WEEK_GRID_START_MINUTES) / 60) * WEEK_GRID_HOUR_HEIGHT
    return {
      dayIndex,
      top,
      height: Math.max(18, (durationMinutes / 60) * WEEK_GRID_HOUR_HEIGHT - 4),
      nextStart,
      nextEnd,
      label: `${formatMinutes(nextStartMinutes)}-${nextEnd.slice(11, 16)}`,
    }
  }

  function handleWeekEventDragOver(event: DragEvent<HTMLDivElement>) {
    const eventId = event.dataTransfer.getData('text/calendar-event-id') || draggedEventId
    if (eventId === null) return
    const calendarEvent = events.find((item) => item.id === eventId)
    if (calendarEvent === undefined || calendarEvent.id === null) return
    const target = weekDropTargetFromDrag(event, calendarEvent)
    if (target === null) {
      setDragPreview(null)
      return
    }
    event.preventDefault()
    event.dataTransfer.dropEffect = 'move'
    setDragPreview({
      dayIndex: target.dayIndex,
      top: target.top,
      height: target.height,
      label: target.label,
    })
  }

  async function handleWeekEventDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    const eventId = event.dataTransfer.getData('text/calendar-event-id') || draggedEventId
    setDraggedEventId(null)
    setDragGrabOffsetMinutes(0)
    if (eventId === null) return
    const calendarEvent = events.find((item) => item.id === eventId)
    if (calendarEvent === undefined || calendarEvent.id === null) return
    const target = weekDropTargetFromDrag(event, calendarEvent)
    setDragPreview(null)
    if (target === null) {
      setError(t('calendar.move.unsupported'))
      return
    }
    if (
      typeof calendarEvent.start.dateTime === 'string' &&
      calendarEvent.start.dateTime.slice(0, 16) === target.nextStart &&
      typeof calendarEvent.end.dateTime === 'string' &&
      calendarEvent.end.dateTime.slice(0, 16) === target.nextEnd
    ) {
      return
    }
    setError(null)
    setFeedback(null)
    try {
      const result = await moveCalendarDbEvent(calendarEvent.id, {
        start: target.nextStart,
        end: target.nextEnd,
        time_zone: 'Asia/Tokyo',
      })
      setEvents((currentEvents) =>
        currentEvents
          .map((item) => (item.id === calendarEvent.id ? result.event : item))
          .sort((left, right) => calendarEventDate(left).localeCompare(calendarEventDate(right))),
      )
      setFeedback(t('calendar.move.done'))
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('app.requestFailed'))
    }
  }

  useEffect(() => {
    void loadMonthEvents()
  }, [calendarMonth, selectedCalendarIds])

  function toggleCalendar(calendarId: string) {
    setSelectedCalendarIds((current) => {
      if (current.includes(calendarId)) {
        return current.length === 1 ? current : current.filter((id) => id !== calendarId)
      }
      return [...current, calendarId]
    })
  }

  useEffect(() => {
    const timerId = window.setInterval(() => setNow(new Date()), 60000)
    return () => window.clearInterval(timerId)
  }, [])

  useEffect(() => {
    try {
      window.localStorage.setItem(
        CALENDAR_SOURCE_STORAGE_KEY,
        JSON.stringify(selectedCalendarIds),
      )
    } catch {
      // Calendar source selection is a convenience setting; ignore storage failures.
    }
  }, [selectedCalendarIds])

  function jumpMonth(amount: number) {
    const nextMonth = addMonths(calendarMonth, amount)
    setCalendarMonth(nextMonth)
    setSelectedDate(nextMonth)
  }

  function jumpWeek(amount: number) {
    const nextDate = addDays(selectedDate, amount * 7)
    setSelectedDate(nextDate)
    setCalendarMonth(nextDate.slice(0, 7) + '-01')
  }

  function selectDate(date: string) {
    setSelectedDate(date)
  }

  return (
    <main className="app-shell">
      <div className="calendar-shell">
        <header className="maintenance-header">
          <div>
            <p>{t('app.name')}</p>
            <h1>{t('calendar.heading')}</h1>
          </div>
          <nav aria-label={t('calendar.navigation')} className="maintenance-nav">
            <AppLink href="/tasks">{t('nav.tasks')}</AppLink>
            <AppLink href="/cases">{t('nav.cases')}</AppLink>
            <AppLink href="/">{t('top.heading')}</AppLink>
          </nav>
        </header>

        {error !== null && (
          <div className="mail-feedback">
            <p role="alert">{error}</p>
          </div>
        )}
        {feedback !== null && (
          <div className="mail-feedback">
            <p>{feedback}</p>
          </div>
        )}

        <div className="calendar-main-layout">
          <section className="calendar-panel calendar-week-panel">
            <div className="section-heading">
              <div>
                <h2>{weekLabel}</h2>
                <p>{t('calendar.day.count', { count: String(selectedEvents.length) })}</p>
              </div>
              <button
                className={`button-loading-dot${isLoading ? ' is-loading' : ''}`}
                disabled={isLoading || !canRead}
                onClick={() => void loadMonthEvents()}
                type="button"
              >
                {t('calendar.refresh')}
              </button>
              <button
                className={`button-loading-dot${isSyncing ? ' is-loading' : ''}`}
                disabled={isLoading || isSyncing || !canRead}
                onClick={() => void syncVisibleCalendars()}
                type="button"
              >
                {t('calendar.sync.load')}
              </button>
            </div>
            {isLoading ? (
              <p className="mail-empty">{t('calendar.loading')}</p>
            ) : (
              <div className="calendar-week-stage">
                <button
                  aria-label={t('calendar.previousWeek')}
                  className="calendar-week-shift calendar-week-shift-previous"
                  onClick={() => jumpWeek(-1)}
                  type="button"
                >
                  {'◀'}
                </button>
                <div
                  className="calendar-week-grid"
                  onDragLeave={(dragEvent) => {
                    if (!dragEvent.currentTarget.contains(dragEvent.relatedTarget as Node | null)) {
                      setDragPreview(null)
                    }
                  }}
                  onDragOver={handleWeekEventDragOver}
                  onDrop={(dropEvent) => void handleWeekEventDrop(dropEvent)}
                >
                  {shouldShowNowLine && todayColumnIndex >= 0 && (
                    <span
                      aria-hidden="true"
                      className="calendar-now-line"
                      style={{
                        left: `calc(58px + ((100% - 58px) / 7) * ${todayColumnIndex})`,
                        top: `${nowLineTop}px`,
                        width: 'calc((100% - 58px) / 7)',
                      }}
                    />
                  )}
                  {dragPreview !== null && (
                    <span
                      aria-hidden="true"
                      className="calendar-week-drop-preview"
                      style={{
                        left: `calc(58px + ((100% - 58px) / 7) * ${dragPreview.dayIndex} + 4px)`,
                        top: `${dragPreview.top}px`,
                        width: 'calc((100% - 58px) / 7 - 8px)',
                        height: `${dragPreview.height}px`,
                      }}
                    >
                      {dragPreview.label}
                    </span>
                  )}
                  {positionedWeekEvents.map(({ event, dayIndex, top, height, isAllDay, isShort, laneCount, laneOffsetRatio, laneWidthRatio }) => (
                    <AppLink
                      className={`calendar-week-event calendar-week-event-positioned${
                        isAllDay ? ' calendar-week-event-all-day' : ''
                      }${!isAllDay && (laneCount > 1 || isShort) ? ' calendar-week-event-narrow' : ''}${
                        isCalendarEventPast(event, now) || isCalendarEventAttendanceOptional(event)
                          ? ' calendar-week-event-past'
                          : ''
                      } calendar-week-event-${calendarSourceTone(
                        event.calendar_source_id ?? 'primary',
                        calendars,
                      )}`}
                      key={`${dayIndex}-${event.id ?? `${calendarEventDate(event)}-${calendarEventTime(event)}-${event.summary}`}`}
                      draggable={!isAllDay && event.id !== null}
                      onDragStart={(dragEvent) => {
                        if (event.id === null || isAllDay) {
                          dragEvent.preventDefault()
                          return
                        }
                        dragEvent.dataTransfer.effectAllowed = 'move'
                        dragEvent.dataTransfer.setData('text/calendar-event-id', event.id)
                        setDraggedEventId(event.id)
                        setDragGrabOffsetMinutes(
                          Math.max(
                            0,
                            Math.round(
                              ((dragEvent.clientY -
                                dragEvent.currentTarget.getBoundingClientRect().top) /
                                WEEK_GRID_HOUR_HEIGHT) *
                                60,
                            ),
                          ),
                        )
                      }}
                      onDragEnd={() => {
                        setDraggedEventId(null)
                        setDragPreview(null)
                        setDragGrabOffsetMinutes(0)
                      }}
                      style={{
                        left: isAllDay
                          ? `calc(58px + ((100% - 58px) / 7) * ${dayIndex} + 4px)`
                          : `calc(58px + ((100% - 58px) / 7) * ${dayIndex} + (((100% - 58px) / 7 - 8px) * ${laneOffsetRatio}) + 4px)`,
                        top: `${top}px`,
                        width: isAllDay
                          ? 'calc((100% - 58px) / 7 - 8px)'
                          : `calc(((100% - 58px) / 7 - 8px) * ${laneWidthRatio} - 2px)`,
                        height: `${height}px`,
                      }}
                      href={`/calendar/events/${encodeURIComponent(event.id ?? '')}`}
                    >
                      <strong>{event.summary || t('calendar.noTitle')}</strong>
                    </AppLink>
                  ))}
                  <div aria-hidden="true" className="calendar-week-corner" />
                  {selectedWeekDays.map((date) => {
                    const weekdayIndex = new Date(`${date}T00:00:00Z`).getUTCDay()
                    return (
                    <button
                      aria-current={date === selectedDate ? 'date' : undefined}
                      className={`calendar-week-day-heading${
                        weekdayIndex === 0 ? ' is-sunday' : weekdayIndex === 6 ? ' is-saturday' : ''
                      }${date === today ? ' is-today' : ''}`}
                      key={date}
                      onClick={() => selectDate(date)}
                      type="button"
                    >
                      <span>{['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][weekdayIndex]}</span>
                      <strong>{Number(date.slice(8, 10))}</strong>
                    </button>
                    )
                  })}
                  {weekHours.map((hour) => (
                    <div className="calendar-week-row" key={hour}>
                      <time>{String(hour).padStart(2, '0')}:00</time>
                      {selectedWeekDays.map((date) => (
                        <div className="calendar-week-cell" key={`${date}-${hour}`} />
                      ))}
                    </div>
                  ))}
                </div>
                <button
                  aria-label={t('calendar.nextWeek')}
                  className="calendar-week-shift calendar-week-shift-next"
                  onClick={() => jumpWeek(1)}
                  type="button"
                >
                  {'▶'}
                </button>
              </div>
            )}
          </section>

          <aside className="calendar-gadget-column">
            <section className="case-gadget-card">
              <AppLink className="case-gadget-action" href="/calendar/new">
                {t('calendar.create.submit')}
              </AppLink>
            </section>

            <section aria-label={t('calendar.monthGrid')} className="mail-panel mail-calendar-panel calendar-mini-panel">
              <button
                className="mail-calendar-today"
                onClick={() => {
                  setCalendarMonth(today.slice(0, 7) + '-01')
                  selectDate(today)
                }}
                type="button"
              >
                {t('calendar.today')}
              </button>
              <div className="mail-calendar-heading">
                <button
                  aria-label={t('mail.previousMonth')}
                  onClick={() => jumpMonth(-1)}
                  type="button"
                >
                  {'<'}
                </button>
                <strong>{calendarMonth.slice(0, 7)}</strong>
                <button
                  aria-label={t('mail.nextMonth')}
                  onClick={() => jumpMonth(1)}
                  type="button"
                >
                  {'>'}
                </button>
              </div>
              <div aria-label={t('calendar.monthGrid')} className="mail-calendar-grid">
                {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map((weekday, index) => (
                  <span
                    className={`mail-calendar-weekday${
                      index === 0 ? ' is-sunday' : index === 6 ? ' is-saturday' : ''
                    }`}
                    key={weekday}
                  >
                    {weekday}
                  </span>
                ))}
                {selectedMonthDays.map((date, index) => {
                  if (date === null) {
                    return (
                      <span
                        aria-hidden="true"
                        className="mail-calendar-empty"
                        key={`empty-${index}`}
                      />
                    )
                  }
                  const count = eventsByDate.get(date)?.length ?? 0
                  return (
                    <button
                      aria-current={date === selectedDate ? 'date' : undefined}
                      aria-label={t('calendar.day.count', { count: String(count) })}
                      className={`mail-calendar-day${
                        count > 0 ? ' calendar-mini-day-has-event' : ''
                      }${date === today ? ' is-today' : ''}`}
                      key={date}
                      onClick={() => selectDate(date)}
                      type="button"
                    >
                      {Number(date.slice(8, 10))}
                    </button>
                  )
                })}
              </div>
            </section>

            <section className="case-gadget-card">
              <h2>{t('calendar.upcoming.heading')}</h2>
              {upcomingEvents.length === 0 ? (
                <p>{t('calendar.upcoming.empty')}</p>
              ) : (
                <div className="calendar-upcoming-list">
                  {upcomingEvents.map((event) => (
                    <button
                      key={event.id ?? `${calendarEventDate(event)}-${event.summary}`}
                      onClick={() => {
                        const date = calendarEventDate(event)
                        if (date !== '') {
                          setCalendarMonth(date.slice(0, 7) + '-01')
                          selectDate(date)
                        }
                      }}
                      type="button"
                    >
                      <span>
                        {calendarEventDate(event)} {calendarEventTime(event)}
                      </span>
                      <strong>{event.summary || t('calendar.noTitle')}</strong>
                    </button>
                  ))}
                </div>
              )}
            </section>

            <section className="case-gadget-card calendar-source-gadget">
              <div className="case-gadget-heading-row">
                <h2>{t('calendar.source.heading')}</h2>
                <button
                  aria-expanded={isCalendarSourceOpen}
                  aria-label={t('calendar.source.heading')}
                  className="case-icon-button"
                  onClick={() => setIsCalendarSourceOpen((current) => !current)}
                  type="button"
                >
                  ⚙
                </button>
              </div>
              {isCalendarSourceOpen && (
                <div aria-label={t('calendar.source.label')} className="calendar-source-checks">
                  {calendars.length === 0 ? (
                    <p>{t('calendar.source.primary')}</p>
                  ) : (
                    calendars.map((calendar) => (
                      <label key={calendar.id}>
                        <input
                          checked={selectedCalendarIdSet.has(calendar.id)}
                          disabled={isLoading}
                          onChange={() => toggleCalendar(calendar.id)}
                          type="checkbox"
                        />
                        <span
                          aria-hidden="true"
                          className={`calendar-source-swatch calendar-source-swatch-${calendarSourceTone(
                            calendar.id,
                            calendars,
                          )}`}
                        />
                        <strong>{calendar.summary || calendar.id}</strong>
                      </label>
                    ))
                  )}
                </div>
              )}
            </section>
          </aside>
        </div>
      </div>
    </main>
  )
}

export default CalendarView
