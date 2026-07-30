import { Fragment, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { DragEvent } from 'react'
import type { CSSProperties } from 'react'
import {
  getGoogleGmailStatus,
  listCalendarDbEvents,
  listGoogleCalendars,
  moveCalendarDbEvent,
  syncGoogleCalendarEvents,
  updateGoogleCalendarAutoSyncSettings,
  toJstIsoDateTime,
  updateCalendarDbEventTitleFit,
} from './phase4Api'
import type {
  GoogleCalendarAutoSyncSettings,
  GoogleCalendarEvent,
  GoogleCalendarListItem,
} from './phase4Api'
import settingsGearIconUrl from './assets/settings-gear.svg'
import { t } from './i18n'
import { AppLink, TopNav, navigateTo } from './navigation'

type CalendarEventWithSource = GoogleCalendarEvent & {
  calendar_source_id?: string | null
}

type CalendarWeekTitleFit = {
  fit_version?: number
  title: string
  font_size_px: number
  line_height: number
  line_clamp: number
  measured_width: number
  measured_height: number
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

function calendarEventLoadRange(calendarMonth: string, selectedDate: string) {
  const month = monthRange(calendarMonth)
  const week = weekRange(selectedDate)
  const start = month.start < week.start ? month.start : week.start
  const end = month.end > week.end ? month.end : week.end
  return {
    start,
    end,
    timeMin: `${start}T00:00:00+09:00`,
    timeMax: `${end}T00:00:00+09:00`,
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

function calendarWeekTitleFit(event: GoogleCalendarEvent): CalendarWeekTitleFit | null {
  if (event.metadata_json === null || event.metadata_json === undefined || event.metadata_json.trim() === '') {
    return null
  }
  try {
    const metadata = JSON.parse(event.metadata_json) as Record<string, unknown>
    const fit = metadata.calendar_week_title_fit
    if (typeof fit !== 'object' || fit === null) return null
    const candidate = fit as Partial<CalendarWeekTitleFit>
    if (
      candidate.fit_version !== WEEK_EVENT_TITLE_FIT_VERSION ||
      typeof candidate.title !== 'string' ||
      typeof candidate.font_size_px !== 'number' ||
      typeof candidate.line_height !== 'number' ||
      typeof candidate.line_clamp !== 'number'
    ) {
      return null
    }
    return {
      fit_version: candidate.fit_version,
      title: candidate.title,
      font_size_px: candidate.font_size_px,
      line_height: candidate.line_height,
      line_clamp: candidate.line_clamp,
      measured_width: typeof candidate.measured_width === 'number' ? candidate.measured_width : 0,
      measured_height: typeof candidate.measured_height === 'number' ? candidate.measured_height : 0,
    }
  } catch {
    return null
  }
}

const WEEK_GRID_HEADER_HEIGHT = 48
const WEEK_GRID_HOUR_HEIGHT = 45
const WEEK_GRID_START_MINUTES = 6 * 60
const WEEK_GRID_END_MINUTES = 21 * 60
const WEEK_GRID_DROP_STEP_MINUTES = 15
const WEEK_EVENT_TITLE_FIT_VERSION = 2

const WEEK_EVENT_TITLE_FONT_CANDIDATES = [
  { fontSizePx: 11.5, lineHeight: 1.14 },
  { fontSizePx: 11, lineHeight: 1.12 },
  { fontSizePx: 10.5, lineHeight: 1.1 },
  { fontSizePx: 10, lineHeight: 1.08 },
  { fontSizePx: 9.5, lineHeight: 1.07 },
  { fontSizePx: 9, lineHeight: 1.06 },
  { fontSizePx: 8.5, lineHeight: 1.05 },
  { fontSizePx: 8, lineHeight: 1.04 },
] as const

function savedWeekEventTitleStyle(fit: CalendarWeekTitleFit): CSSProperties {
  return {
    '--calendar-event-title-font-size': `${fit.font_size_px}px`,
    '--calendar-event-title-line-height': String(fit.line_height),
    '--calendar-event-title-line-clamp': String(fit.line_clamp),
  } as CSSProperties
}

function CalendarWeekMeasuredTitle({
  eventId,
  title,
}: {
  eventId: string | null
  title: string
}) {
  const titleRef = useRef<HTMLElement | null>(null)
  const [style, setStyle] = useState<CSSProperties>({
    '--calendar-event-title-font-size': '11.5px',
    '--calendar-event-title-line-height': '1.14',
    '--calendar-event-title-line-clamp': '2',
  } as CSSProperties)

  useLayoutEffect(() => {
    const element = titleRef.current
    if (element === null || eventId === null) return
    const parent = element.parentElement
    if (parent === null) return
    const titleElement = element
    const parentElement = parent

    window.requestAnimationFrame(() => {
      const width = titleElement.clientWidth
      if (width <= 0) return
      const parentStyle = window.getComputedStyle(parentElement)
      const elementStyle = window.getComputedStyle(titleElement)
      const paddingTop = Number.parseFloat(parentStyle.paddingTop) || 0
      const paddingBottom = Number.parseFloat(parentStyle.paddingBottom) || 0
      const availableHeight = Math.max(8, parentElement.clientHeight - paddingTop - paddingBottom - 2)
      const measure = document.createElement('strong')
      measure.textContent = title
      measure.style.position = 'absolute'
      measure.style.left = '-10000px'
      measure.style.top = '0'
      measure.style.visibility = 'hidden'
      measure.style.pointerEvents = 'none'
      measure.style.display = 'block'
      measure.style.width = `${width}px`
      measure.style.boxSizing = 'border-box'
      measure.style.whiteSpace = 'normal'
      measure.style.overflowWrap = 'anywhere'
      measure.style.wordBreak = 'normal'
      measure.style.fontFamily = elementStyle.fontFamily
      measure.style.fontWeight = elementStyle.fontWeight
      document.body.appendChild(measure)
      const smallest = WEEK_EVENT_TITLE_FONT_CANDIDATES.at(-1)!
      let selected = smallest
      let lineClamp = Math.max(
        1,
        Math.floor(availableHeight / (smallest.fontSizePx * smallest.lineHeight)),
      )
      for (const candidate of WEEK_EVENT_TITLE_FONT_CANDIDATES) {
        measure.style.fontSize = `${candidate.fontSizePx}px`
        measure.style.lineHeight = String(candidate.lineHeight)
        const lineHeightPx = candidate.fontSizePx * candidate.lineHeight
        const fullLineCount = Math.max(1, Math.ceil(measure.scrollHeight / lineHeightPx))
        if (fullLineCount * lineHeightPx <= availableHeight) {
          selected = candidate
          lineClamp = fullLineCount
          break
        }
      }
      if (selected === smallest) {
        measure.style.fontSize = `${selected.fontSizePx}px`
        measure.style.lineHeight = String(selected.lineHeight)
        const lineHeightPx = selected.fontSizePx * selected.lineHeight
        const fullLineCount = Math.max(1, Math.ceil(measure.scrollHeight / lineHeightPx))
        lineClamp = Math.min(
          fullLineCount,
          Math.max(1, Math.floor(availableHeight / lineHeightPx)),
        )
      }
      document.body.removeChild(measure)
      const nextStyle = {
        '--calendar-event-title-font-size': `${selected.fontSizePx}px`,
        '--calendar-event-title-line-height': String(selected.lineHeight),
        '--calendar-event-title-line-clamp': String(lineClamp),
      } as CSSProperties
      setStyle(nextStyle)
      persistCalendarTitleFit(eventId, {
        title,
        font_size_px: selected.fontSizePx,
        line_height: selected.lineHeight,
        line_clamp: lineClamp,
        measured_width: width,
        measured_height: parentElement.clientHeight,
      })
    })
  }, [eventId, title])

  return (
    <strong ref={titleRef} style={style}>
      {title}
    </strong>
  )
}

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

function formatCalendarSyncTime(value: string | null) {
  if (value === null) return t('common.none')
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return new Intl.DateTimeFormat('ja-JP', {
    timeZone: 'Asia/Tokyo',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(parsed)
}

function calendarSyncStatusLabel(
  settings: GoogleCalendarAutoSyncSettings | null,
  isSyncing: boolean,
) {
  if (isSyncing) return t('calendar.sync.statusSyncing')
  if (settings === null) return null
  if (settings.last_error !== null) {
    return t('calendar.sync.statusError')
  }
  if (settings.last_success_at === null) {
    return t('calendar.sync.statusNever')
  }
  const parsed = Date.parse(settings.last_success_at)
  if (!Number.isNaN(parsed)) {
    const staleAfterMs = Math.max(5, settings.interval_minutes * 2) * 60_000
    if (Date.now() - parsed > staleAfterMs) {
      return t('calendar.sync.statusStale')
    }
  }
  return null
}

function calendarSyncStatusTone(
  settings: GoogleCalendarAutoSyncSettings | null,
  isSyncing: boolean,
) {
  if (isSyncing) return 'pending'
  if (settings?.last_error !== null && settings?.last_error !== undefined) return 'failed'
  if (calendarSyncStatusLabel(settings, false) !== null) return 'pending'
  return 'succeeded'
}

const CALENDAR_SOURCE_STORAGE_KEY = 'caseclosed.calendar.selectedCalendarIds'

function initialCalendarDate() {
  const value = new URLSearchParams(window.location.search).get('date')?.trim() ?? ''
  return /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : jstDateToday()
}

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

type CalendarSourceSnapshot = {
  status: Awaited<ReturnType<typeof getGoogleGmailStatus>>
  calendarItems: GoogleCalendarListItem[]
}

const CALENDAR_SOURCE_CACHE_MILLISECONDS = 60_000
let calendarSourceCache: { value: CalendarSourceSnapshot; expiresAt: number } | null = null
let calendarSourceInFlight: Promise<CalendarSourceSnapshot> | null = null
const persistedCalendarTitleFits = new Map<string, string>()

function loadCalendarSources(): Promise<CalendarSourceSnapshot> {
  if (calendarSourceCache !== null && calendarSourceCache.expiresAt > Date.now()) {
    return Promise.resolve(calendarSourceCache.value)
  }
  if (calendarSourceInFlight !== null) return calendarSourceInFlight

  const pendingRequest = getGoogleGmailStatus()
    .then(async (status) => ({
      status,
      calendarItems:
        status.connected === true && status.calendar_read_enabled === true
          ? await listGoogleCalendars()
          : [],
    }))
    .then((value) => {
      calendarSourceCache = {
        value,
        expiresAt: Date.now() + CALENDAR_SOURCE_CACHE_MILLISECONDS,
      }
      return value
    })
    .finally(() => {
      if (calendarSourceInFlight === pendingRequest) calendarSourceInFlight = null
    })
  calendarSourceInFlight = pendingRequest
  return pendingRequest
}

function invalidateCalendarSourceCache() {
  calendarSourceCache = null
}

function persistCalendarTitleFit(
  eventId: string,
  payload: Parameters<typeof updateCalendarDbEventTitleFit>[1],
) {
  const signature = JSON.stringify(payload)
  if (persistedCalendarTitleFits.get(eventId) === signature) return
  persistedCalendarTitleFits.set(eventId, signature)
  void updateCalendarDbEventTitleFit(eventId, payload).catch(() => {
    if (persistedCalendarTitleFits.get(eventId) === signature) {
      persistedCalendarTitleFits.delete(eventId)
    }
  })
}


function CalendarView() {
  const today = useMemo(() => jstDateToday(), [])
  const initialDate = useMemo(() => initialCalendarDate(), [])
  const [now, setNow] = useState(() => new Date())
  const [calendarMonth, setCalendarMonth] = useState(initialDate.slice(0, 7) + '-01')
  const [selectedDate, setSelectedDate] = useState(initialDate)
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
  const [lastCalendarSyncAt, setLastCalendarSyncAt] = useState<string | null>(null)
  const [calendarAutoSync, setCalendarAutoSync] =
    useState<GoogleCalendarAutoSyncSettings | null>(null)
  const [dragPreview, setDragPreview] = useState<{
    dayIndex: number
    top: number
    height: number
    label: string
  } | null>(null)
  const [draggedEventId, setDraggedEventId] = useState<string | null>(null)
  const [dragGrabOffsetMinutes, setDragGrabOffsetMinutes] = useState(0)
  const [hasLoadedCalendarSourceSettings, setHasLoadedCalendarSourceSettings] = useState(false)

  const selectedMonthDays = useMemo(() => calendarDays(calendarMonth), [calendarMonth])
  const selectedWeekDays = useMemo(() => weekDays(selectedDate), [selectedDate])
  const eventLoadRange = useMemo(
    () => calendarEventLoadRange(calendarMonth, selectedDate),
    [calendarMonth, selectedDate],
  )
  const weekLabel = `${selectedWeekDays[0]} - ${selectedWeekDays[6]}`
  const syncStatusLabel = calendarSyncStatusLabel(calendarAutoSync, isSyncing)
  const syncStatusTone = calendarSyncStatusTone(calendarAutoSync, isSyncing)
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
    ...selectedWeekDays.flatMap((_, dayIndex) => {
      const allDayEvents = positionedWeekEventBase
        .filter((item) => item.dayIndex === dayIndex && item.isAllDay)
        .sort(
          (left, right) =>
            calendarEventStartSortKey(left.event) - calendarEventStartSortKey(right.event) ||
            (left.event.summary || '').localeCompare(right.event.summary || ''),
        )
      const laneCount = Math.max(1, allDayEvents.length)
      return allDayEvents.map((item, lane) => ({
        ...item,
        lane,
        laneCount,
        laneOffsetRatio: lane / laneCount,
        laneWidthRatio: 1 / laneCount,
      }))
    }),
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
      const { status, calendarItems } = await loadCalendarSources()
      setCanRead(status.calendar_read_enabled === true)
      setLastCalendarSyncAt(status.calendar_auto_sync.last_success_at)
      setCalendarAutoSync(status.calendar_auto_sync)
      if (status.connected !== true || status.calendar_read_enabled !== true) {
        setEvents([])
        setError(
          status.connected === true
            ? t('calendar.scopeMissing')
          : t('calendar.notConnected'),
        )
        return
      }
      setCalendars(calendarItems)
      const validIds = new Set(calendarItems.map((calendar) => calendar.id))
      const primaryCalendarId = calendarItems.find((calendar) => calendar.primary)?.id ?? 'primary'
      const isDefaultPrimarySelection = (calendarIds: string[]) =>
        calendarIds.length === 1 &&
        (calendarIds[0] === 'primary' || calendarIds[0] === primaryCalendarId)
      const serverCalendarIds = status.calendar_auto_sync.calendar_ids
      const savedCalendarIds = hasLoadedCalendarSourceSettings
        ? selectedCalendarIds
        : isDefaultPrimarySelection(serverCalendarIds) &&
            !isDefaultPrimarySelection(selectedCalendarIds)
          ? selectedCalendarIds
          : serverCalendarIds
      const nextCalendarIds = savedCalendarIds.filter((id) => validIds.has(id))
      if (nextCalendarIds.length === 0) {
        const fallbackId =
          calendarItems.find((calendar) => calendar.primary)?.id ??
          calendarItems[0]?.id ??
          'primary'
        nextCalendarIds.push(fallbackId)
      }
      setHasLoadedCalendarSourceSettings(true)
      if (nextCalendarIds.join('\n') !== selectedCalendarIds.join('\n')) {
        setSelectedCalendarIds(nextCalendarIds)
      }
      const eventPages = await listCalendarDbEvents({
        calendar_id: nextCalendarIds,
        time_min: eventLoadRange.timeMin,
        time_max: eventLoadRange.timeMax,
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
      const syncedAt = new Date().toISOString()
      setFeedback(
        t('calendar.sync.done', {
          imported: String(result.imported_count),
          updated: String(result.updated_count),
        }),
      )
      invalidateCalendarSourceCache()
      await loadMonthEvents()
      setLastCalendarSyncAt(syncedAt)
      setCalendarAutoSync((current) =>
        current === null
          ? current
          : {
              ...current,
              last_run_at: syncedAt,
              last_success_at: syncedAt,
              last_error: null,
              last_stop_reason: 'synced',
            },
      )
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
        start: toJstIsoDateTime(target.nextStart),
        end: toJstIsoDateTime(target.nextEnd),
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
  }, [eventLoadRange.timeMin, eventLoadRange.timeMax, selectedCalendarIds])

  function toggleCalendar(calendarId: string) {
    setSelectedCalendarIds((current) => {
      if (current.includes(calendarId)) {
        return current.length === 1 ? current : current.filter((id) => id !== calendarId)
      }
      return [...current, calendarId]
    })
  }

  async function saveCalendarSourceSelection(calendarIds: string[]) {
    if (calendarAutoSync === null) {
      return
    }
    try {
      const settings = await updateGoogleCalendarAutoSyncSettings({
        enabled: calendarAutoSync.enabled,
        interval_minutes: calendarAutoSync.interval_minutes,
        calendar_ids: calendarIds,
        month_count: calendarAutoSync.month_count,
      })
      setCalendarAutoSync(settings)
      invalidateCalendarSourceCache()
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('app.requestFailed'))
    }
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
    if (hasLoadedCalendarSourceSettings) {
      void saveCalendarSourceSelection(selectedCalendarIds)
    }
  }, [hasLoadedCalendarSourceSettings, selectedCalendarIds])

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
            <h1>
              {t('calendar.heading')}
              <span className="calendar-last-sync">
                {t('calendar.lastSync', {
                  value: formatCalendarSyncTime(lastCalendarSyncAt),
                })}
              </span>
              {syncStatusLabel !== null && (
                <span className="calendar-sync-status" data-status={syncStatusTone}>
                  {syncStatusLabel}
                </span>
              )}
            </h1>
          </div>
          <TopNav
            ariaLabelKey="calendar.navigation"
            items={[
              { href: '/', labelKey: 'top.heading' },
              { href: '/mail', labelKey: 'nav.mail' },
              { href: '/tasks', labelKey: 'nav.tasks' },
              { href: '/cases', labelKey: 'nav.cases' },
            ]}
          />
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
              <div className="calendar-heading-actions">
                <button
                  className={`calendar-sync-button button-loading-dot${isSyncing ? ' is-loading' : ''}`}
                  disabled={isLoading || isSyncing || !canRead}
                  onClick={() => void syncVisibleCalendars()}
                  type="button"
                >
                  {t('calendar.sync.load')}
                </button>
                <button
                  className="calendar-conflict-button"
                  onClick={() => navigateTo('/calendar/conflicts')}
                  type="button"
                >
                  {t('calendar.conflicts.open')}
                </button>
              </div>
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
                  {positionedWeekEvents.map(({ event, dayIndex, top, height, isAllDay, isShort, laneCount, laneOffsetRatio, laneWidthRatio }) => {
                    const title = event.summary || t('calendar.noTitle')
                    const titleFit = calendarWeekTitleFit(event)
                    const savedTitleStyle =
                      titleFit !== null && titleFit.title === title ? savedWeekEventTitleStyle(titleFit) : {}
                    return (
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
                        left: `calc(58px + ((100% - 58px) / 7) * ${dayIndex} + (((100% - 58px) / 7 - 8px) * ${laneOffsetRatio}) + 4px)`,
                        top: `${top}px`,
                        width: `calc(((100% - 58px) / 7 - 8px) * ${laneWidthRatio} - 2px)`,
                        height: `${height}px`,
                        ...savedTitleStyle,
                      }}
                      href={`/calendar/events/${encodeURIComponent(event.id ?? '')}`}
                    >
                      {titleFit !== null && titleFit.title === title ? (
                        <strong>{title}</strong>
                      ) : (
                        <CalendarWeekMeasuredTitle eventId={event.id} title={title} />
                      )}
                    </AppLink>
                    )
                  })}
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
                  {upcomingEvents.map((event, index) => {
                    const date = calendarEventDate(event)
                    const previousDate =
                      index === 0 ? null : calendarEventDate(upcomingEvents[index - 1])
                    return (
                      <Fragment key={event.id ?? `${date}-${event.summary}`}>
                        {date !== previousDate && (
                          <div className="calendar-upcoming-date-separator">
                            -- {date} --
                          </div>
                        )}
                        <button
                          onClick={() => {
                            if (date !== '') {
                              setCalendarMonth(date.slice(0, 7) + '-01')
                              selectDate(date)
                            }
                          }}
                          type="button"
                        >
                          <span>{calendarEventTime(event)}</span>
                          <strong>{event.summary || t('calendar.noTitle')}</strong>
                        </button>
                      </Fragment>
                    )
                  })}
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
                  title={t('calendar.source.heading')}
                  type="button"
                >
                  <img alt="" aria-hidden="true" src={settingsGearIconUrl} />
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
                  <AppLink className="calendar-settings-link" href="/academic-calendar">
                    {t('academicCalendar.open')}
                  </AppLink>
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
