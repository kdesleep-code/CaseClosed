import { useEffect, useMemo, useState } from 'react'
import type { CSSProperties } from 'react'
import { t } from './i18n'
import { AppLink, TopNav } from './navigation'
import { listCalendarDbEvents } from './phase4Api'
import type { GoogleCalendarEvent, MailListItem } from './phase4Api'
import { listMailPage } from './phase4Api'
import { listTasks } from './phase8Api'
import type { TaskItem } from './phase8Api'
import defaultContactAvatarUrl from './assets/default-contact-avatar.svg'
import defaultMailingListAvatarUrl from './assets/default-mailing-list-avatar.svg'
import defaultSpamAvatarUrl from './assets/default-spam-avatar.webp'
import sleepyTanukiUrl from './assets/sleeping-tanuki-calendar-banner.png'
import unknownContactAvatarUrl from './assets/default-unknown-contact-avatar.svg'

type TodayData = {
  mails: MailListItem[]
  tasks: TaskItem[]
  events: GoogleCalendarEvent[]
}

type PositionedTodayCalendarEvent = {
  event: GoogleCalendarEvent
  top: number
  height: number
  startMinute: number
  endMinute: number
  lane: number
  laneCount: number
  laneOffsetRatio: number
  laneWidthRatio: number
  isShort: boolean
}

const CALENDAR_START_HOUR = 7
const CALENDAR_END_HOUR = 22
const CALENDAR_HOUR_HEIGHT = 87
const CALENDAR_NOW_LINE_MASK_RATIO = 0.1
const CALENDAR_BOARD_HEIGHT = 760
const CALENDAR_SLEEP_BANNER_TOP =
  (CALENDAR_END_HOUR - CALENDAR_START_HOUR) * CALENDAR_HOUR_HEIGHT + 8
const CALENDAR_SLEEP_BANNER_HEIGHT = 124
const CALENDAR_CONTENT_BOTTOM = CALENDAR_SLEEP_BANNER_TOP + CALENDAR_SLEEP_BANNER_HEIGHT
const CALENDAR_MIN_BOARD_HEIGHT = 260
const CALENDAR_SLEEP_ONLY_BOARD_HEIGHT = CALENDAR_SLEEP_BANNER_HEIGHT + 16

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

function startOfDate(date: string) {
  return `${date}T00:00:00+09:00`
}

function endOfDate(date: string) {
  return `${date}T23:59:59+09:00`
}

function addDays(date: string, amount: number) {
  const [year, month, day] = date.split('-').map(Number)
  const nextDate = new Date(Date.UTC(year, month - 1, day + amount))
  return [
    nextDate.getUTCFullYear(),
    String(nextDate.getUTCMonth() + 1).padStart(2, '0'),
    String(nextDate.getUTCDate()).padStart(2, '0'),
  ].join('-')
}

function formatDueDate(value: string | null) {
  if (value === null) return t('common.none')
  return `~ ${value.slice(0, 10)}`
}

function isOverdueDate(value: string | null) {
  if (value === null) return false
  if (value.length <= 10) {
    return value.slice(0, 10) < jstDateToday()
  }
  const dueTime = new Date(value).getTime()
  return Number.isFinite(dueTime) && dueTime < Date.now()
}

function formatTime(value: string) {
  return value.length <= 10 ? t('calendar.allDay') : value.slice(11, 16)
}

function mailSender(mail: MailListItem) {
  return mail.sender_contact?.display_name ?? mail.from_name ?? mail.from_address
}

function senderAvatarUrl(mail: MailListItem) {
  if (mail.sender_contact === null || mail.sender_contact === undefined) {
    return unknownContactAvatarUrl
  }
  return (
    mail.sender_contact.avatar_url ??
    (mail.sender_contact.status === 'spam'
      ? defaultSpamAvatarUrl
      : mail.sender_contact.kind === 'mailing_list'
        ? defaultMailingListAvatarUrl
        : defaultContactAvatarUrl)
  )
}

function mailPriorityClass(importance: string) {
  return importance === 'pending' ? 'mail-priority-bug' : `mail-priority-${importance}`
}

function shouldShowTodayMail(mail: MailListItem) {
  return ['pinned', 'high', 'middle'].includes(mail.effective_importance)
}

function isOpenTask(task: TaskItem) {
  return task.deleted_at === null && task.status !== 'completed' && task.status !== 'canceled'
}

function isStartedTask(task: TaskItem, today: string) {
  return isOpenTask(task) && task.start_at !== null && task.start_at.slice(0, 10) <= today
}

function taskPriorityRank(task: TaskItem) {
  if (task.priority === 'high') return 0
  if (task.priority === 'middle') return 1
  if (task.priority === 'low') return 2
  return 3
}

function taskDueRank(task: TaskItem) {
  return task.due_at === null ? Number.MAX_SAFE_INTEGER : new Date(task.due_at).getTime()
}

function sortTasks(tasks: TaskItem[]) {
  return [...tasks].sort((left, right) => {
    const dueDiff = taskDueRank(left) - taskDueRank(right)
    if (dueDiff !== 0) return dueDiff
    const priorityDiff = taskPriorityRank(left) - taskPriorityRank(right)
    if (priorityDiff !== 0) return priorityDiff
    return left.title.localeCompare(right.title)
  })
}

function calendarEventDate(event: GoogleCalendarEvent) {
  const value =
    typeof event.start.dateTime === 'string'
      ? event.start.dateTime
      : typeof event.start.date === 'string'
        ? event.start.date
        : ''
  return value.slice(0, 10)
}

function calendarEventDisplayDates(event: GoogleCalendarEvent) {
  const startDate = calendarEventDate(event)
  if (startDate === '') {
    return []
  }
  const isAllDay = typeof event.start.date === 'string' && typeof event.start.dateTime !== 'string'
  const endDate = typeof event.end.date === 'string' ? event.end.date.slice(0, 10) : ''
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
  const startValue =
    typeof event.start.dateTime === 'string'
      ? event.start.dateTime
      : typeof event.start.date === 'string'
        ? event.start.date
        : ''
  const endValue =
    typeof event.end.dateTime === 'string'
      ? event.end.dateTime
      : typeof event.end.date === 'string'
        ? event.end.date
        : ''
  if (startValue.length <= 10) {
    return t('calendar.allDay')
  }
  const endTime = endValue.length > 10 ? endValue.slice(11, 16) : ''
  return endTime === '' ? startValue.slice(11, 16) : `${startValue.slice(11, 16)}-${endTime}`
}

function calendarSortRank(event: GoogleCalendarEvent) {
  const value = typeof event.start.dateTime === 'string' ? event.start.dateTime : ''
  if (value.length <= 10) return -1
  return Number(value.slice(11, 13)) * 60 + Number(value.slice(14, 16))
}

function calendarEventStartMinutes(event: GoogleCalendarEvent) {
  const value = typeof event.start.dateTime === 'string' ? event.start.dateTime : ''
  if (value.length <= 10) return null
  const hour = Number(value.slice(11, 13))
  const minute = Number(value.slice(14, 16))
  if (!Number.isFinite(hour) || !Number.isFinite(minute)) return null
  return hour * 60 + minute
}

function calendarEventEndMinutes(event: GoogleCalendarEvent) {
  const value = typeof event.end.dateTime === 'string' ? event.end.dateTime : ''
  if (value.length <= 10) return null
  const hour = Number(value.slice(11, 13))
  const minute = Number(value.slice(14, 16))
  if (!Number.isFinite(hour) || !Number.isFinite(minute)) return null
  return hour * 60 + minute
}

function isCalendarEventAttendanceOptional(event: GoogleCalendarEvent) {
  const value = (event.attendance_requirement ?? '').toLowerCase().trim()
  return ['optional', 'not_required', 'unnecessary', 'no_attendance'].includes(value)
}

function calendarEventBasePosition(event: GoogleCalendarEvent) {
  const startMinutes = calendarEventStartMinutes(event)
  const endMinutes = calendarEventEndMinutes(event)
  if (startMinutes === null) {
    return null
  }
  const dayStart = CALENDAR_START_HOUR * 60
  const dayEnd = CALENDAR_END_HOUR * 60
  const rawEnd = endMinutes ?? startMinutes + 60
  if (rawEnd <= dayStart || startMinutes >= dayEnd) {
    return null
  }
  const clampedStart = Math.max(dayStart, startMinutes)
  const clampedEnd = Math.min(Math.max(rawEnd, startMinutes + 15), dayEnd)
  return {
    top: ((clampedStart - dayStart) / 60) * CALENDAR_HOUR_HEIGHT,
    height: Math.max(34, ((clampedEnd - clampedStart) / 60) * CALENDAR_HOUR_HEIGHT - 4),
    startMinute: clampedStart,
    endMinute: clampedEnd,
    isShort: clampedEnd - clampedStart < 60,
  }
}

function calendarEventStyle(event: GoogleCalendarEvent) {
  const position = calendarEventBasePosition(event)
  if (position === null) return undefined
  return {
    top: `${position.top}px`,
    height: `${position.height}px`,
  }
}

function positionedCalendarEvents(events: GoogleCalendarEvent[]): PositionedTodayCalendarEvent[] {
  const dayEvents = events
    .map((event) => {
      const position = calendarEventBasePosition(event)
      return position === null ? null : { event, ...position }
    })
    .filter((item): item is NonNullable<typeof item> => item !== null)
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
}

function positionedCalendarEventStyle(item: PositionedTodayCalendarEvent): CSSProperties {
  return {
    top: `${item.top}px`,
    height: `${item.height}px`,
    left: `calc(8px + (100% - 16px) * ${item.laneOffsetRatio})`,
    right: 'auto',
    width: `calc((100% - 16px) * ${item.laneWidthRatio} - 2px)`,
  }
}

function currentTimeLineTop(today: string, now: Date) {
  if (today !== jstDateToday()) {
    return null
  }
  const minutes = currentJstMinutes(now)
  const dayStart = CALENDAR_START_HOUR * 60
  const dayEnd = CALENDAR_END_HOUR * 60
  if (minutes === null || minutes < dayStart || minutes > dayEnd) {
    return null
  }
  return {
    top: ((minutes - dayStart) / 60) * CALENDAR_HOUR_HEIGHT,
  }
}

function currentJstMinutes(now: Date) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Tokyo',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  })
    .formatToParts(now)
    .reduce<Record<string, string>>((values, part) => {
      values[part.type] = part.value
      return values
    }, {})
  const minutes = Number(parts.hour) * 60 + Number(parts.minute)
  if (!Number.isFinite(minutes)) {
    return null
  }
  return minutes
}

function calendarTrackStyle(today: string, now: Date, nowLineTop: { top: number } | null): CSSProperties {
  const fixedLineTop = CALENDAR_BOARD_HEIGHT * CALENDAR_NOW_LINE_MASK_RATIO
  const minutes = currentJstMinutes(now)
  const dayEnd = CALENDAR_END_HOUR * 60
  if (today === jstDateToday() && minutes !== null && minutes > dayEnd) {
    return {
      transform: `translateY(${8 - CALENDAR_SLEEP_BANNER_TOP}px)`,
    }
  }
  if (nowLineTop === null) {
    return {}
  }
  return {
    transform: `translateY(${fixedLineTop - nowLineTop.top}px)`,
  }
}

function calendarBoardStyle(today: string, now: Date, nowLineTop: { top: number } | null): CSSProperties {
  if (today !== jstDateToday()) {
    return {
      height: `${CALENDAR_CONTENT_BOTTOM}px`,
    }
  }
  const minutes = currentJstMinutes(now)
  const dayStart = CALENDAR_START_HOUR * 60
  const dayEnd = CALENDAR_END_HOUR * 60
  if (minutes !== null && minutes < dayStart) {
    return {
      height: `${CALENDAR_CONTENT_BOTTOM}px`,
    }
  }
  if (minutes !== null && minutes > dayEnd) {
    return {
      height: `${CALENDAR_SLEEP_ONLY_BOARD_HEIGHT}px`,
    }
  }
  if (nowLineTop === null) {
    return {}
  }
  const fixedLineTop = CALENDAR_BOARD_HEIGHT * CALENDAR_NOW_LINE_MASK_RATIO
  const trackOffset = fixedLineTop - nowLineTop.top
  const visibleContentBottom = CALENDAR_CONTENT_BOTTOM + trackOffset
  return {
    height: `${Math.max(CALENDAR_MIN_BOARD_HEIGHT, visibleContentBottom)}px`,
  }
}

function sortEvents(events: GoogleCalendarEvent[]) {
  return [...events].sort((left, right) => {
    const rankDiff = calendarSortRank(left) - calendarSortRank(right)
    if (rankDiff !== 0) return rankDiff
    return (left.summary || '').localeCompare(right.summary || '')
  })
}

function eventDetailHref(event: GoogleCalendarEvent, returnPath: string) {
  if (event.id === null) return '/calendar'
  const params = new URLSearchParams({ return_to: returnPath })
  return `/calendar/events/${encodeURIComponent(event.id)}?${params.toString()}`
}

function mailDetailHref(mail: MailListItem, returnPath: string) {
  const params = new URLSearchParams({
    return_to: returnPath,
    focus_message: mail.id,
  })
  return `/mail/${encodeURIComponent(mail.id)}?${params.toString()}`
}

function taskDetailHref(task: TaskItem, returnPath: string) {
  const params = new URLSearchParams({ return_to: returnPath })
  return `/tasks/${encodeURIComponent(task.id)}?${params.toString()}`
}

function targetDate(dayOffset: number) {
  return addDays(jstDateToday(), dayOffset)
}

function TodayView({ dayOffset = 0 }: { dayOffset?: 0 | 1 }) {
  const [today, setToday] = useState(() => targetDate(dayOffset))
  const [now, setNow] = useState(() => new Date())
  const nowLineTop = useMemo(() => currentTimeLineTop(today, now), [now, today])
  const trackStyle = useMemo(() => calendarTrackStyle(today, now, nowLineTop), [now, nowLineTop, today])
  const boardStyle = useMemo(() => calendarBoardStyle(today, now, nowLineTop), [now, nowLineTop, today])
  const nowLineStyle = useMemo<CSSProperties>(
    () => ({ top: `${CALENDAR_BOARD_HEIGHT * CALENDAR_NOW_LINE_MASK_RATIO}px` }),
    [],
  )
  const returnPath = dayOffset === 0 ? '/today' : '/tomorrow'
  const heading = dayOffset === 0 ? t('today.heading') : t('tomorrow.heading')
  const [data, setData] = useState<TodayData>({
    mails: [],
    tasks: [],
    events: [],
  })
  const allDayEvents = useMemo(
    () => data.events.filter((event) => calendarEventStyle(event) === undefined),
    [data.events],
  )
  const timedEvents = useMemo(
    () => data.events.filter((event) => calendarEventStyle(event) !== undefined),
    [data.events],
  )
  const positionedTimedEvents = useMemo(() => positionedCalendarEvents(timedEvents), [timedEvents])
  const locationEvents = useMemo(
    () =>
      data.events.filter(
        (event) =>
          event.location !== null &&
          event.location.trim() !== '' &&
          !isCalendarEventAttendanceOptional(event),
      ),
    [data.events],
  )
  const allDayLocationEvents = useMemo(
    () => locationEvents.filter((event) => calendarEventStyle(event) === undefined),
    [locationEvents],
  )
  const timedLocationEvents = useMemo(
    () => locationEvents.filter((event) => calendarEventStyle(event) !== undefined),
    [locationEvents],
  )
  const positionedTimedLocationEvents = useMemo(
    () => positionedCalendarEvents(timedLocationEvents),
    [timedLocationEvents],
  )
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setToday(targetDate(dayOffset))
    setNow(new Date())
  }, [dayOffset])

  useEffect(() => {
    let isMounted = true
    setIsLoading(true)
    Promise.all([
      listMailPage({
        tab: 'unprocessed',
        date_from: startOfDate(today),
        date_to: endOfDate(today),
        limit: 100,
      }),
      listTasks({ status: 'all', limit: 500 }),
      listCalendarDbEvents({
        time_min: startOfDate(today),
        time_max: startOfDate(addDays(today, 1)),
      }),
    ])
      .then(([mailPage, allTasks, calendarPage]) => {
        if (!isMounted) return
        setData({
          mails: mailPage.items.filter(shouldShowTodayMail),
          tasks: sortTasks(allTasks.filter((task) => isStartedTask(task, today))),
          events: sortEvents(
            calendarPage.items.filter((event) => calendarEventDisplayDates(event).includes(today)),
          ),
        })
        setError(null)
      })
      .catch((requestError) => {
        if (!isMounted) {
          return
        }
        setError(requestError instanceof Error ? requestError.message : t('app.requestFailed'))
      })
      .finally(() => {
        if (isMounted) {
          setIsLoading(false)
        }
      })

    return () => {
      isMounted = false
    }
  }, [today])

  useEffect(() => {
    const timerId = window.setInterval(() => {
      setNow(new Date())
      setToday((currentToday) => {
        const nextToday = targetDate(dayOffset)
        return nextToday === currentToday ? currentToday : nextToday
      })
    }, 60000)
    return () => window.clearInterval(timerId)
  }, [dayOffset])

  return (
    <main className="app-shell">
      <div className="today-shell">
        <div className="mail-floating-day-nav today-floating-day-nav" aria-label={t('today.dayNavigation')}>
          <AppLink
            aria-disabled={dayOffset === 0}
            aria-label={t('today.previousDay')}
            className={dayOffset === 0 ? 'is-disabled' : undefined}
            href="/today"
          >
            {'<'}
          </AppLink>
          <AppLink
            aria-disabled={dayOffset === 1}
            aria-label={t('today.nextDay')}
            className={dayOffset === 1 ? 'is-disabled' : undefined}
            href="/tomorrow"
          >
            {'>'}
          </AppLink>
        </div>
        <header className="maintenance-header">
          <div>
            <p>{t('app.name')}</p>
            <div className="mail-title-row">
              <h1>{heading}</h1>
              <span>{today}</span>
            </div>
          </div>
          <TopNav
            ariaLabelKey="today.navigation"
            items={[
              { href: '/', labelKey: 'top.heading' },
              { href: '/follow-ups', labelKey: 'nav.followUps' },
              { href: '/cases', labelKey: 'nav.cases' },
            ]}
          />
        </header>

        {error !== null && (
          <div className="mail-feedback">
            <p role="alert">{error}</p>
          </div>
        )}

        <div className="today-dashboard">
          <section className="today-panel today-calendar-panel today-calendar-shared-panel">
            <div className="section-heading">
              <div>
                <h2>{t('today.calendar.heading')}</h2>
                <p>{t('today.calendar.description')}</p>
              </div>
              <AppLink href={`/calendar?date=${today}`}>{t('today.openCalendar')}</AppLink>
            </div>
            {isLoading ? (
              <p className="today-empty">{t('common.loading')}</p>
            ) : (
              <>
                <div className="today-calendar-pair-heading">
                  <div>
                    <strong>{t('today.calendar.heading')}</strong>
                    <span>{t('today.calendar.description')}</span>
                  </div>
                  <div>
                    <strong>{t('today.calendarWindow.heading')}</strong>
                    <span>{t('today.calendarWindow.description')}</span>
                  </div>
                </div>
                {(allDayEvents.length > 0 || allDayLocationEvents.length > 0) && (
                  <div className="today-calendar-pair today-calendar-pair-all-day">
                    <div className="today-calendar-all-day-stack">
                      {allDayEvents.map((event) => (
                        <AppLink
                          className="today-calendar-event-card today-calendar-event-all-day"
                          href={eventDetailHref(event, returnPath)}
                          key={`all-day-${event.id ?? event.summary}`}
                        >
                          <time>{calendarEventTime(event)}</time>
                          <strong>{event.summary || t('calendar.noTitle')}</strong>
                        </AppLink>
                      ))}
                    </div>
                    <div className="today-calendar-all-day-stack today-location-all-day-stack">
                      {allDayLocationEvents.map((event) => (
                        <AppLink
                          className="today-calendar-event-card today-calendar-event-all-day today-location-card"
                          href={eventDetailHref(event, returnPath)}
                          key={`location-all-day-${event.id ?? event.summary}`}
                        >
                          <time>{calendarEventTime(event)}</time>
                          <strong>{event.location}</strong>
                        </AppLink>
                      ))}
                    </div>
                  </div>
                )}
                <div className="today-calendar-pair today-calendar-board-pair">
                  <img
                    alt=""
                    aria-hidden="true"
                    className="today-calendar-sleepy-tanuki"
                    src={sleepyTanukiUrl}
                    style={trackStyle}
                  />
                  <div className="today-calendar-board today-calendar-board-left" style={boardStyle}>
                    <div className="today-calendar-track" style={trackStyle}>
                      <div className="today-calendar-hours">
                        {Array.from(
                          { length: CALENDAR_END_HOUR - CALENDAR_START_HOUR },
                          (_, index) => CALENDAR_START_HOUR + index,
                        ).map((hour) => (
                          <div className="today-calendar-hour" key={hour}>
                            <time>{String(hour).padStart(2, '0')}:00</time>
                          </div>
                        ))}
                      </div>
                      <div className="today-calendar-event-layer">
                        {data.events.length === 0 && (
                          <p className="today-calendar-empty-label">{t('today.calendar.empty')}</p>
                        )}
                        {positionedTimedEvents.map((item) => {
                          const event = item.event
                          return (
                            <AppLink
                              className={`today-calendar-event-card${
                                item.laneCount > 1 || item.isShort ? ' today-calendar-event-narrow' : ''
                              }${isCalendarEventAttendanceOptional(event) ? ' today-calendar-event-optional' : ''}`}
                              href={eventDetailHref(event, returnPath)}
                              key={`${item.lane}-${event.id ?? `${event.summary}-${calendarEventTime(event)}`}`}
                              style={positionedCalendarEventStyle(item)}
                            >
                              <time>{calendarEventTime(event)}</time>
                              <strong>{event.summary || t('calendar.noTitle')}</strong>
                              {event.location !== null && event.location.trim() !== '' && (
                                <span>{event.location}</span>
                              )}
                            </AppLink>
                          )
                        })}
                      </div>
                    </div>
                  </div>
                  <div className="today-calendar-board today-calendar-board-right" style={boardStyle}>
                    <div
                      className="today-calendar-track today-calendar-track-no-hours"
                      style={trackStyle}
                    >
                      <div className="today-calendar-event-layer">
                        {locationEvents.length === 0 && (
                          <p className="today-calendar-empty-label">{t('today.calendarWindow.empty')}</p>
                        )}
                        {positionedTimedLocationEvents.map((item) => {
                          const event = item.event
                          return (
                            <AppLink
                              className={`today-calendar-event-card today-location-card${
                                item.laneCount > 1 || item.isShort ? ' today-calendar-event-narrow' : ''
                              }${isCalendarEventAttendanceOptional(event) ? ' today-calendar-event-optional' : ''}`}
                              href={eventDetailHref(event, returnPath)}
                              key={`location-${item.lane}-${event.id ?? `${event.location}-${calendarEventTime(event)}`}`}
                              style={positionedCalendarEventStyle(item)}
                            >
                              <time>{calendarEventTime(event)}</time>
                              <strong>{event.location}</strong>
                              <span>{event.summary || t('calendar.noTitle')}</span>
                            </AppLink>
                          )
                        })}
                      </div>
                    </div>
                  </div>
                  {nowLineTop !== null && (
                    <div aria-hidden="true" className="today-calendar-now-line" style={nowLineStyle} />
                  )}
                </div>
              </>
            )}
          </section>

          <div className="today-side-stack">
            <section className="today-panel">
            <div className="section-heading">
              <div>
                <h2>{t('today.mail.heading')}</h2>
                <p>{t('today.mail.description')}</p>
              </div>
              <AppLink href={`/mail?tab=unprocessed&date=${today}`}>{t('today.openMail')}</AppLink>
            </div>
            {isLoading ? (
              <p className="today-empty">{t('common.loading')}</p>
            ) : data.mails.length === 0 ? (
              <p className="today-empty">{t('today.mail.empty')}</p>
            ) : (
              <div className="today-list">
                {data.mails.map((mail) => (
                  <AppLink
                    className={`today-mail-row ${mailPriorityClass(mail.effective_importance)}`}
                    href={mailDetailHref(mail, returnPath)}
                    key={mail.id}
                  >
                    <div className="today-mail-sender-media">
                      <time>{formatTime(mail.received_at)}</time>
                      <img
                        alt={t('mail.senderAvatarAlt', { name: mailSender(mail) })}
                        src={senderAvatarUrl(mail)}
                      />
                      <span>{mailSender(mail)}</span>
                    </div>
                    <div>
                      <strong>{mail.subject ?? t('mail.noSubject')}</strong>
                    </div>
                  </AppLink>
                ))}
              </div>
            )}
            </section>

            <section className="today-panel">
            <div className="section-heading">
              <div>
                <h2>{t('today.tasks.heading')}</h2>
                <p>{t('today.tasks.description')}</p>
              </div>
              <AppLink href="/tasks">{t('today.openTasks')}</AppLink>
            </div>
            {isLoading ? (
              <p className="today-empty">{t('common.loading')}</p>
            ) : data.tasks.length === 0 ? (
              <p className="today-empty">{t('today.tasks.empty')}</p>
            ) : (
              <div className="today-list">
                {data.tasks.map((task) => (
                  <AppLink
                    className={`today-task-row today-priority-${task.priority}`}
                    href={taskDetailHref(task, returnPath)}
                    key={task.id}
                  >
                    <time className={isOverdueDate(task.due_at) ? 'task-due-overdue' : undefined}>
                      {formatDueDate(task.due_at)}
                    </time>
                    <div>
                      <strong>{task.title}</strong>
                      <span>{task.case_name ?? t('tasks.noCase')}</span>
                    </div>
                  </AppLink>
                ))}
              </div>
            )}
            </section>
          </div>
        </div>
      </div>
    </main>
  )
}

export default TodayView
