import { useEffect, useState } from 'react'
import { listCalendarConflicts, listCalendarDbEvents, updateCalendarDbEvent } from './phase4Api'
import type { CalendarConflictGroup, GoogleCalendarEvent } from './phase4Api'
import { t } from './i18n'
import { TopNav, navigateTo } from './navigation'

function formatJstDateTime(value: string) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Tokyo',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  })
    .formatToParts(new Date(value))
    .reduce<Record<string, string>>((values, part) => {
      values[part.type] = part.value
      return values
    }, {})

  return `${parts.year}/${parts.month}/${parts.day} ${parts.hour}:${parts.minute}`
}

function calendarEventTime(event: GoogleCalendarEvent) {
  const startValue = typeof event.start.dateTime === 'string' ? event.start.dateTime : ''
  const endValue = typeof event.end.dateTime === 'string' ? event.end.dateTime : ''
  if (startValue === '') return t('time.unavailable')
  return `${formatJstDateTime(startValue)}-${endValue === '' ? '' : endValue.slice(11, 16)}`
}

function eventDetailHref(event: GoogleCalendarEvent) {
  return event.id === null ? '/calendar' : `/calendar/events/${encodeURIComponent(event.id)}`
}

function eventLocation(event: GoogleCalendarEvent) {
  const location = event.location?.trim() ?? ''
  return location === '' ? t('time.unavailable') : location
}

type ConflictActionMode = 'optional' | 'moving' | null

const calendarMovingTag = 'calendar:moving'

function calendarEventTags(event: GoogleCalendarEvent) {
  const rawTags = event.tags_json
  if (rawTags === undefined || rawTags === null || rawTags.trim() === '') return []
  try {
    const parsed = JSON.parse(rawTags)
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === 'string') : []
  } catch {
    return []
  }
}

function isCalendarEventMoving(event: GoogleCalendarEvent) {
  return calendarEventTags(event).includes(calendarMovingTag)
}

function conflictKey(conflict: CalendarConflictGroup) {
  return `${conflict.conflict_start}-${conflict.conflict_end}`
}

function composeRescheduleSubject(event: GoogleCalendarEvent) {
  return `日程調整のお願い: ${event.summary}`
}

function composeRescheduleBody(event: GoogleCalendarEvent, conflict: CalendarConflictGroup) {
  return [
    'お世話になっております。',
    '',
    `以下の予定について、別予定と時間が重なっているため日程調整をお願いできますでしょうか。`,
    '',
    `予定: ${event.summary}`,
    `現在の日時: ${calendarEventTime(event)}`,
    `重複している時間帯: ${formatJstDateTime(conflict.conflict_start)} - ${formatJstDateTime(conflict.conflict_end).slice(11)}`,
    event.location?.trim() ? `場所: ${event.location.trim()}` : null,
    '',
    '候補日時をいくつかいただけますと幸いです。',
    'どうぞよろしくお願いいたします。',
  ].filter((line): line is string => line !== null).join('\n')
}

function composeRescheduleHref(event: GoogleCalendarEvent, conflict: CalendarConflictGroup) {
  const params = new URLSearchParams()
  params.set('subject', composeRescheduleSubject(event))
  params.set('manual_body', composeRescheduleBody(event, conflict))
  return `/mail/compose?${params.toString()}`
}

function ConflictCard({
  actionMode,
  busyEventId,
  conflict,
  isActionScope,
  onActionModeChange,
  onEventClick,
}: {
  actionMode: ConflictActionMode
  busyEventId: string | null
  conflict: CalendarConflictGroup
  isActionScope: boolean
  onActionModeChange: (mode: ConflictActionMode, conflict: CalendarConflictGroup) => void
  onEventClick: (event: GoogleCalendarEvent, conflict: CalendarConflictGroup) => void
}) {
  return (
    <article className="calendar-conflict-card">
      <header>
        <div>
          <span>{t('calendar.conflicts.window')}</span>
          <h2>
            {formatJstDateTime(conflict.conflict_start)} -{' '}
            {formatJstDateTime(conflict.conflict_end).slice(11)}
          </h2>
        </div>
        <strong>{t('calendar.conflicts.count').replace('{count}', String(conflict.event_count))}</strong>
      </header>

      <div className="calendar-conflict-guidance" aria-label={t('calendar.conflicts.heading')}>
        <button
          aria-pressed={isActionScope && actionMode === 'optional'}
          onClick={() => onActionModeChange(isActionScope && actionMode === 'optional' ? null : 'optional', conflict)}
          type="button"
        >
          {t('calendar.conflicts.suggestOptional')}
        </button>
        <button
          aria-pressed={isActionScope && actionMode === 'moving'}
          onClick={() => onActionModeChange(isActionScope && actionMode === 'moving' ? null : 'moving', conflict)}
          type="button"
        >
          {t('calendar.conflicts.suggestReschedule')}
        </button>
      </div>

      <div className="calendar-conflict-events">
        {conflict.events.map((event) => (
          <button
            className={`calendar-conflict-event${isActionScope ? ' is-action-target' : ''}`}
            disabled={busyEventId === event.id || (actionMode !== null && !isActionScope)}
            key={event.id}
            onClick={() => onEventClick(event, conflict)}
            type="button"
          >
            <span>{calendarEventTime(event)}</span>
            <strong>{event.summary}</strong>
            <small>{eventLocation(event)}</small>
          </button>
        ))}
      </div>
    </article>
  )
}

function MovingEventList({ events }: { events: GoogleCalendarEvent[] }) {
  return (
    <section className="calendar-conflict-moving">
      <div className="section-heading">
        <div>
          <h2>{t('calendar.conflicts.movingHeading')}</h2>
          <p>{t('calendar.conflicts.movingCount').replace('{count}', String(events.length))}</p>
        </div>
      </div>
      {events.length === 0 ? (
        <section className="calendar-conflict-empty">
          <h2>{t('calendar.conflicts.movingEmptyHeading')}</h2>
          <p>{t('calendar.conflicts.movingEmptyBody')}</p>
        </section>
      ) : (
        <div className="calendar-conflict-events">
          {events.map((event) => (
            <button
              className="calendar-conflict-event"
              key={event.id}
              onClick={() => navigateTo(eventDetailHref(event))}
              type="button"
            >
              <span>{calendarEventTime(event)}</span>
              <strong>{event.summary}</strong>
              <small>{eventLocation(event)}</small>
            </button>
          ))}
        </div>
      )}
    </section>
  )
}

export default function CalendarConflictView() {
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [feedback, setFeedback] = useState<string | null>(null)
  const [actionMode, setActionMode] = useState<ConflictActionMode>(null)
  const [actionConflictKey, setActionConflictKey] = useState<string | null>(null)
  const [busyEventId, setBusyEventId] = useState<string | null>(null)
  const [conflicts, setConflicts] = useState<CalendarConflictGroup[]>([])
  const [movingEvents, setMovingEvents] = useState<GoogleCalendarEvent[]>([])
  const [range, setRange] = useState<{ time_min: string; time_max: string } | null>(null)

  function loadConflicts(isMounted: () => boolean) {
    setIsLoading(true)
    setError(null)
    return listCalendarConflicts()
      .then((payload) => {
        if (!isMounted()) return
        setConflicts(payload.items)
        setRange({ time_min: payload.time_min, time_max: payload.time_max })
        return listCalendarDbEvents({ time_min: payload.time_min, time_max: payload.time_max })
      })
      .then((payload) => {
        if (!isMounted() || payload === undefined) return
        setMovingEvents(payload.items.filter(isCalendarEventMoving))
      })
      .catch((caught: unknown) => {
        if (!isMounted()) return
        setError(caught instanceof Error ? caught.message : 'Failed to load calendar conflicts')
        setMovingEvents([])
      })
      .finally(() => {
        if (isMounted()) {
          setIsLoading(false)
        }
      })
  }

  useEffect(() => {
    let isMounted = true
    void loadConflicts(() => isMounted)
    return () => {
      isMounted = false
    }
  }, [])

  function handleActionModeChange(mode: ConflictActionMode, conflict: CalendarConflictGroup) {
    setActionMode(mode)
    setActionConflictKey(mode === null ? null : conflictKey(conflict))
    setFeedback(null)
  }

  async function handleEventClick(event: GoogleCalendarEvent, conflict: CalendarConflictGroup) {
    const isActionScope = actionConflictKey === conflictKey(conflict)
    if (event.id === null || actionMode === null || !isActionScope) {
      navigateTo(eventDetailHref(event))
      return
    }
    setBusyEventId(event.id)
    setError(null)
    setFeedback(null)
    try {
      if (actionMode === 'optional') {
        await updateCalendarDbEvent(event.id, { attendance_requirement: 'not_required' })
        setFeedback(t('calendar.conflicts.optionalDone'))
        await loadConflicts(() => true)
        setActionMode(null)
        setActionConflictKey(null)
        return
      }
      await updateCalendarDbEvent(event.id, { moving: true })
      navigateTo(composeRescheduleHref(event, conflict))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t('app.requestFailed'))
    } finally {
      setBusyEventId(null)
    }
  }

  const rangeLabel =
    range === null
      ? t('common.loading')
      : `${formatJstDateTime(range.time_min)} - ${formatJstDateTime(range.time_max)}`

  return (
    <main className="app-shell">
      <div className="calendar-shell calendar-conflict-shell">
        <header className="maintenance-header">
          <div>
            <p>{t('app.name')}</p>
            <h1>
              {t('calendar.conflicts.heading')}
              <span className="calendar-last-sync">{rangeLabel}</span>
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
          <section className="calendar-panel calendar-conflict-panel">
            <div className="section-heading">
              <div>
                <h2>{t('calendar.conflicts.range')}</h2>
                <p>{rangeLabel}</p>
              </div>
              <button className="calendar-sync-button" onClick={() => navigateTo('/calendar')} type="button">
                {t('calendar.conflicts.back')}
              </button>
            </div>

            {isLoading && <p className="mail-empty">{t('common.loading')}</p>}
            {!isLoading && error === null && conflicts.length === 0 && (
              <section className="calendar-conflict-empty">
                <h2>{t('calendar.conflicts.emptyHeading')}</h2>
                <p>{t('calendar.conflicts.emptyBody')}</p>
              </section>
            )}
            {!isLoading && error === null && conflicts.length > 0 && (
              <section className="calendar-conflict-list" aria-label={t('calendar.conflicts.heading')}>
                {conflicts.map((conflict) => (
                  <ConflictCard
                    actionMode={actionMode}
                    busyEventId={busyEventId}
                    conflict={conflict}
                    isActionScope={actionConflictKey === conflictKey(conflict)}
                    key={conflictKey(conflict)}
                    onActionModeChange={handleActionModeChange}
                    onEventClick={handleEventClick}
                  />
                ))}
              </section>
            )}
            {!isLoading && error === null && <MovingEventList events={movingEvents} />}
          </section>
        </div>
      </div>
    </main>
  )
}
