import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { AppLink, TopNav, navigateTo, returnToOrFallback } from './navigation'
import {
  createCalendarDbEventLink,
  deleteCalendarDbEvent,
  deleteCalendarDbEventLink,
  getCalendarDbEvent,
  listGoogleCalendars,
  moveCalendarDbEvent,
  toJstIsoDateTime,
  updateCalendarDbEvent,
} from './phase4Api'
import { listMailPage } from './phase4Api'
import type { CalendarEventDetail, GoogleCalendarEvent, GoogleCalendarListItem, MailListItem } from './phase4Api'
import { listCases } from './phase7Api'
import type { CaseItem } from './phase7Api'
import { listTasks } from './phase8Api'
import type { TaskItem } from './phase8Api'
import SuggestInput from './SuggestInput'
import { t } from './i18n'
import defaultContactAvatarUrl from './assets/default-contact-avatar.svg'
import defaultMailingListAvatarUrl from './assets/default-mailing-list-avatar.svg'
import defaultServiceAvatarUrl from './assets/default-service-avatar.svg'
import defaultSpamAvatarUrl from './assets/default-spam-avatar.webp'
import gmailIconUrl from './assets/gmail-icon-2020.svg'
import paperclipDiagonalUrl from './assets/paperclip-diagonal.svg'
import settingsGearIconUrl from './assets/settings-gear.svg'

type CalendarDeleteScope = 'event' | 'series'

function eventDateTimeValue(event: GoogleCalendarEvent, key: 'start' | 'end') {
  const value = event[key]
  if (typeof value.dateTime === 'string') return value.dateTime
  if (typeof value.date === 'string') return value.date
  return ''
}

function eventDateTimeInputValue(event: GoogleCalendarEvent, key: 'start' | 'end') {
  const value = eventDateTimeValue(event, key)
  return value.length > 16 ? value.slice(0, 16) : value
}

function calendarHrefForEvent(event: GoogleCalendarEvent | null) {
  const date = event === null ? '' : eventDateTimeValue(event, 'start').slice(0, 10)
  return /^\d{4}-\d{2}-\d{2}$/.test(date) ? `/calendar?date=${encodeURIComponent(date)}` : '/calendar'
}

function formatEventTimeRange(event: GoogleCalendarEvent) {
  const start = eventDateTimeValue(event, 'start')
  const end = eventDateTimeValue(event, 'end')
  if (start === '') return '-'
  if (start.length <= 10) {
    return end !== '' && end !== start ? `${start} - ${end}` : start
  }
  const startDate = start.slice(0, 10)
  const startTime = start.slice(11, 16)
  const endDate = end.slice(0, 10)
  const endTime = end.length > 10 ? end.slice(11, 16) : ''
  if (endTime === '') return `${startDate} ${startTime}`
  if (endDate !== '' && endDate !== startDate) {
    return `${startDate} ${startTime} - ${endDate} ${endTime}`
  }
  return `${startDate} ${startTime}-${endTime}`
}

function locationHref(location: string | null | undefined) {
  const value = location?.trim()
  if (value === undefined || value === '') return null
  try {
    const url = new URL(value)
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.toString() : null
  } catch {
    return null
  }
}

function attendanceLabel(value: string | null | undefined) {
  const normalizedValue = value?.toLowerCase().trim()
  if (
    normalizedValue === 'not_required' ||
    normalizedValue === 'optional' ||
    normalizedValue === 'unnecessary' ||
    normalizedValue === 'no_attendance'
  ) {
    return t('calendar.event.attendanceOptional')
  }
  return t('calendar.event.attendanceRequired')
}

function attendanceValue(value: string | null | undefined) {
  return attendanceLabel(value) === t('calendar.event.attendanceOptional') ? 'not_required' : 'required'
}

const calendarMovingTag = 'calendar:moving'

function calendarEventTags(event: GoogleCalendarEvent | null) {
  const rawTags = event?.tags_json
  if (rawTags === undefined || rawTags === null || rawTags.trim() === '') return []
  try {
    const parsed = JSON.parse(rawTags)
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === 'string') : []
  } catch {
    return []
  }
}

function isCalendarEventMoving(event: GoogleCalendarEvent | null) {
  return calendarEventTags(event).includes(calendarMovingTag)
}

function syncLabel(value: string | null | undefined) {
  if (value === 'local_only') return t('calendar.event.syncLocalOnly')
  if (value === 'synced') return t('calendar.event.syncSynced')
  return value ?? '-'
}

type CalendarMailAssignSort = 'newest' | 'importance'

function mailThreadKey(mail: MailListItem) {
  return mail.thread_id ?? mail.gmail_thread_id
}

function latestThreadItems(mails: MailListItem[]) {
  const latestByThread = new Map<string, MailListItem>()
  for (const mail of mails) {
    const key = mailThreadKey(mail)
    const current = latestByThread.get(key)
    if (
      current === undefined ||
      mail.received_at.localeCompare(current.received_at) > 0 ||
      (mail.received_at === current.received_at && mail.id.localeCompare(current.id) > 0)
    ) {
      latestByThread.set(key, mail)
    }
  }
  return Array.from(latestByThread.values())
}

function mailPriorityClass(importance: string) {
  return importance === 'pending' ? 'mail-priority-bug' : `mail-priority-${importance}`
}

function mailGroupLabel(mail: MailListItem, sort: CalendarMailAssignSort) {
  return sort === 'importance' ? mail.effective_importance : mail.received_date ?? mail.received_at.slice(0, 10)
}

function shouldShowMailGroupLabel(
  mail: MailListItem,
  index: number,
  mails: MailListItem[],
  sort: CalendarMailAssignSort,
) {
  return index === 0 || mailGroupLabel(mail, sort) !== mailGroupLabel(mails[index - 1], sort)
}

function middleOrHigher(importance: string) {
  return importance === 'pinned' || importance === 'high' || importance === 'middle'
}

function shouldShowImportanceThreshold(
  mail: MailListItem,
  index: number,
  mails: MailListItem[],
  sort: CalendarMailAssignSort,
) {
  return (
    sort === 'importance' &&
    index > 0 &&
    middleOrHigher(mails[index - 1].effective_importance) &&
    !middleOrHigher(mail.effective_importance)
  )
}

function compareMailItems(sort: CalendarMailAssignSort) {
  return (left: MailListItem, right: MailListItem) => {
    if (sort === 'importance') {
      const rank = (left.importance_rank ?? 99) - (right.importance_rank ?? 99)
      if (rank !== 0) return rank
    }
    return right.received_at.localeCompare(left.received_at) || left.id.localeCompare(right.id)
  }
}

function mailSenderName(mail: MailListItem) {
  return mail.sender_contact?.display_name ?? mail.from_name ?? mail.from_address
}

function mailSenderAvatar(mail: MailListItem) {
  if (mail.sender_contact === null || mail.sender_contact === undefined) return defaultContactAvatarUrl
  return (
    mail.sender_contact.avatar_url ??
    (mail.sender_contact.status === 'spam'
      ? defaultSpamAvatarUrl
      : mail.sender_contact.kind === 'mailing_list'
        ? defaultMailingListAvatarUrl
        : mail.sender_contact.kind === 'service'
          ? defaultServiceAvatarUrl
          : defaultContactAvatarUrl)
  )
}

function mailSummary(mail: MailListItem) {
  const summary = mail.summary?.trim()
  if (summary === undefined || summary === '') return ''
  return summary.length > 96 ? `${summary.slice(0, 95)}...` : summary
}

export default function CalendarEventDetailView({
  eventId,
  mode = 'detail',
}: {
  eventId: string
  mode?: 'detail' | 'edit' | 'attach-mail'
}) {
  const [detail, setDetail] = useState<CalendarEventDetail | null>(null)
  const [calendars, setCalendars] = useState<GoogleCalendarListItem[]>([])
  const [cases, setCases] = useState<CaseItem[]>([])
  const [tasks, setTasks] = useState<TaskItem[]>([])
  const [summaryDraft, setSummaryDraft] = useState('')
  const [calendarIdDraft, setCalendarIdDraft] = useState('')
  const [locationDraft, setLocationDraft] = useState('')
  const [attendanceDraft, setAttendanceDraft] = useState('required')
  const [movingDraft, setMovingDraft] = useState(false)
  const [caseQuery, setCaseQuery] = useState('')
  const [taskQuery, setTaskQuery] = useState('')
  const [startDraft, setStartDraft] = useState('')
  const [endDraft, setEndDraft] = useState('')
  const [mailSearchResults, setMailSearchResults] = useState<MailListItem[]>([])
  const [mailSearchQuery, setMailSearchQuery] = useState('')
  const [mailSort, setMailSort] = useState<CalendarMailAssignSort>('importance')
  const [mailPageSize, setMailPageSize] = useState(25)
  const [mailSearchRefreshTick, setMailSearchRefreshTick] = useState(0)
  const [selectedMails, setSelectedMails] = useState<Record<string, MailListItem>>({})
  const [isLoading, setIsLoading] = useState(true)
  const [isSavingLink, setIsSavingLink] = useState(false)
  const [isSavingEvent, setIsSavingEvent] = useState(false)
  const [isSavingTime, setIsSavingTime] = useState(false)
  const [isDeletingEvent, setIsDeletingEvent] = useState(false)
  const [isDeleteConfirmOpen, setIsDeleteConfirmOpen] = useState(false)
  const [deleteScope, setDeleteScope] = useState<CalendarDeleteScope>('event')
  const [isSearchingMails, setIsSearchingMails] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [linkError, setLinkError] = useState<string | null>(null)

  useEffect(() => {
    let isMounted = true
    setIsLoading(true)
    getCalendarDbEvent(eventId)
      .then((nextDetail) => {
        if (isMounted) {
          setDetail(nextDetail)
          setError(null)
        }
      })
      .catch((requestError) => {
        if (isMounted) {
          setError(requestError instanceof Error ? requestError.message : t('app.requestFailed'))
        }
      })
      .finally(() => {
        if (isMounted) {
          setIsLoading(false)
        }
      })
    return () => {
      isMounted = false
    }
  }, [eventId])

  useEffect(() => {
    if (mode !== 'edit') {
      return
    }
    let isMounted = true
    Promise.all([listCases('all'), listTasks({ limit: 200 }), listGoogleCalendars()])
      .then(([caseItems, taskItems, calendarItems]) => {
        if (isMounted) {
          setCases(caseItems.filter((item) => item.archived_at === null))
          setTasks(taskItems.filter((item) => item.deleted_at === null))
          setCalendars(calendarItems)
        }
      })
      .catch((requestError) => {
        if (isMounted) {
          setLinkError(requestError instanceof Error ? requestError.message : t('app.requestFailed'))
        }
      })
    return () => {
      isMounted = false
    }
  }, [mode])

  useEffect(() => {
    if (mode !== 'attach-mail') {
      setMailSearchResults([])
      setIsSearchingMails(false)
      return
    }
    const query = mailSearchQuery.trim()
    if (query === '') {
      setMailSearchResults([])
      setIsSearchingMails(false)
      return
    }
    let isMounted = true
    setIsSearchingMails(true)
    const timeoutId = window.setTimeout(() => {
      listMailPage({
        tab: 'all',
        processed: 'all',
        contact_status: 'all',
        read: 'all',
        q: query,
        limit: mailPageSize,
      })
        .then((page) => {
          if (isMounted) setMailSearchResults(page.items)
        })
        .catch((requestError) => {
          if (isMounted) {
            setLinkError(requestError instanceof Error ? requestError.message : t('app.requestFailed'))
          }
        })
        .finally(() => {
          if (isMounted) setIsSearchingMails(false)
        })
    }, 220)
    return () => {
      isMounted = false
      window.clearTimeout(timeoutId)
    }
  }, [mailPageSize, mailSearchQuery, mailSearchRefreshTick, mode])

  const event = detail?.event ?? null
  const eventIsMoving = isCalendarEventMoving(event)
  const calendarHref = calendarHrefForEvent(event)
  const returnHref = returnToOrFallback(calendarHref)
  const eventLocationHref = locationHref(event?.location)
  const canDeleteSeries =
    (event?.recurring_event_id !== undefined &&
      event.recurring_event_id !== null &&
      event.recurring_event_id.trim() !== '') ||
    (event?.academic_series_id !== undefined &&
      event.academic_series_id !== null &&
      event.academic_series_id.trim() !== '')
  const deleteSeriesKind =
    event?.academic_series_id !== undefined &&
    event.academic_series_id !== null &&
    event.academic_series_id.trim() !== ''
      ? 'academic'
      : 'recurring'
  const caseLinks = detail?.links.filter((link) => link.linked_type === 'case') ?? []
  const taskLinks = detail?.links.filter((link) => link.linked_type === 'task') ?? []
  const mailLinks =
    detail?.links.filter((link) => link.linked_type === 'mail' || link.linked_type === 'gmail_message') ??
    []
  const mailSummaries = detail?.mail_summaries ?? []
  const firstCaseLink = caseLinks.find((link) => link.href !== null)
  const firstTaskLink = taskLinks.find((link) => link.href !== null)
  const firstMailLink = mailLinks.find((link) => link.href !== null)
  const caseSuggestions = cases
    .filter((item) => item.name.toLowerCase().includes(caseQuery.trim().toLowerCase()))
    .slice(0, 6)
  const taskSuggestions = tasks
    .filter((item) => item.title.toLowerCase().includes(taskQuery.trim().toLowerCase()))
    .slice(0, 6)
  const selectedCase = cases.find((item) => item.name === caseQuery.trim()) ?? null
  const selectedTask = tasks.find((item) => item.title === taskQuery.trim()) ?? null
  const linkedMailIds = new Set(mailLinks.map((link) => link.linked_id))
  const selectedMailItems = latestThreadItems(Object.values(selectedMails)).toSorted(
    (first, second) => second.received_at.localeCompare(first.received_at),
  )
  const selectedMailThreadIds = new Set(selectedMailItems.map(mailThreadKey))
  const visibleMailSearchResults = latestThreadItems(mailSearchResults)
    .filter((mail) => {
      const key = mailThreadKey(mail)
      return !linkedMailIds.has(mail.id) && !selectedMailThreadIds.has(key) && mailSearchQuery.trim() !== ''
    })
    .toSorted(compareMailItems(mailSort))

  useEffect(() => {
    if (mode !== 'edit') return
    setCaseQuery(firstCaseLink?.title ?? '')
    setTaskQuery(firstTaskLink?.title ?? '')
  }, [firstCaseLink?.id, firstCaseLink?.title, firstTaskLink?.id, firstTaskLink?.title, mode])

  useEffect(() => {
    if (mode !== 'edit' || event === null) return
    setSummaryDraft(event.summary)
    setCalendarIdDraft(event.calendar_source_id ?? 'primary')
    setLocationDraft(event.location ?? '')
    setAttendanceDraft(attendanceValue(event.attendance_requirement))
    setMovingDraft(isCalendarEventMoving(event))
    setStartDraft(eventDateTimeInputValue(event, 'start'))
    setEndDraft(eventDateTimeInputValue(event, 'end'))
  }, [event?.id, event?.attendance_requirement, event?.tags_json, event?.updated, mode])

  useEffect(() => {
    if (!canDeleteSeries) {
      setDeleteScope('event')
    }
  }, [canDeleteSeries])

  async function saveEventBasics() {
    if (summaryDraft.trim() === '') {
      setLinkError(t('calendar.event.titleRequired'))
      return
    }
    setIsSavingEvent(true)
    setLinkError(null)
    try {
      await updateCalendarDbEvent(eventId, {
        summary: summaryDraft,
        calendar_id: calendarIdDraft,
        location: locationDraft.trim() === '' ? null : locationDraft,
        attendance_requirement: attendanceDraft,
        moving: movingDraft,
      })
      setDetail(await getCalendarDbEvent(eventId))
    } catch (requestError) {
      setLinkError(requestError instanceof Error ? requestError.message : t('app.requestFailed'))
    } finally {
      setIsSavingEvent(false)
    }
  }

  async function saveDateTime() {
    if (startDraft.trim() === '' || endDraft.trim() === '') {
      setLinkError(t('calendar.event.dateTimeRequired'))
      return
    }
    if (endDraft <= startDraft) {
      setLinkError(t('calendar.create.invalidDateOrder'))
      return
    }
    setIsSavingTime(true)
    setLinkError(null)
    try {
      await moveCalendarDbEvent(eventId, {
        start: toJstIsoDateTime(startDraft),
        end: toJstIsoDateTime(endDraft),
        time_zone: 'Asia/Tokyo',
      })
      setDetail(await getCalendarDbEvent(eventId))
    } catch (requestError) {
      setLinkError(requestError instanceof Error ? requestError.message : t('app.requestFailed'))
    } finally {
      setIsSavingTime(false)
    }
  }

  async function upsertLink(linkedType: 'case' | 'task', linkedId: string | null) {
    if (linkedId === null) {
      setLinkError(t('calendar.event.linkSelectRequired'))
      return
    }
    setIsSavingLink(true)
    setLinkError(null)
    try {
      const existingLinks = (detail?.links ?? []).filter((link) => link.linked_type === linkedType)
      await Promise.all(
        existingLinks
          .filter((link) => link.linked_id !== linkedId)
          .map((link) => deleteCalendarDbEventLink(eventId, link.id)),
      )
      if (!existingLinks.some((link) => link.linked_id === linkedId)) {
        await createCalendarDbEventLink(eventId, {
          linked_type: linkedType,
          linked_id: linkedId,
          role: 'related',
        })
      }
      const nextDetail = await getCalendarDbEvent(eventId)
      setDetail(nextDetail)
      if (linkedType === 'case') {
        setCaseQuery(nextDetail.links.find((link) => link.linked_type === 'case')?.title ?? '')
      }
      if (linkedType === 'task') {
        setTaskQuery(nextDetail.links.find((link) => link.linked_type === 'task')?.title ?? '')
      }
    } catch (requestError) {
      setLinkError(requestError instanceof Error ? requestError.message : t('app.requestFailed'))
    } finally {
      setIsSavingLink(false)
    }
  }

  async function removeLink(linkId: string) {
    setIsSavingLink(true)
    setLinkError(null)
    try {
      await deleteCalendarDbEventLink(eventId, linkId)
      setDetail((current) =>
        current === null
          ? current
          : { ...current, links: current.links.filter((link) => link.id !== linkId) },
      )
    } catch (requestError) {
      setLinkError(requestError instanceof Error ? requestError.message : t('app.requestFailed'))
    } finally {
      setIsSavingLink(false)
    }
  }

  async function deleteEvent() {
    setIsDeletingEvent(true)
    setLinkError(null)
    try {
      await deleteCalendarDbEvent(eventId, deleteScope)
      navigateTo(returnHref, true)
    } catch (requestError) {
      setLinkError(requestError instanceof Error ? requestError.message : t('app.requestFailed'))
      setIsDeleteConfirmOpen(false)
      setIsDeletingEvent(false)
    }
  }

  function selectMail(mail: MailListItem) {
    setSelectedMails({ [mailThreadKey(mail)]: mail })
  }

  function unselectMail(mail: MailListItem) {
    setSelectedMails((current) => {
      const next = { ...current }
      delete next[mailThreadKey(mail)]
      return next
    })
  }

  async function attachSelectedMails() {
    if (selectedMailItems.length === 0) return
    setIsSavingLink(true)
    setLinkError(null)
    try {
      const selectedMail = selectedMailItems[0]
      await Promise.all(mailLinks.map((link) => deleteCalendarDbEventLink(eventId, link.id)))
      await createCalendarDbEventLink(eventId, {
        linked_type: 'mail',
        linked_id: selectedMail.id,
        role: 'related',
      })
      setSelectedMails({})
      setMailSearchQuery('')
      setDetail(await getCalendarDbEvent(eventId))
    } catch (requestError) {
      setLinkError(requestError instanceof Error ? requestError.message : t('app.requestFailed'))
    } finally {
      setIsSavingLink(false)
    }
  }

  return (
    <main className="app-shell">
      <div className="calendar-shell">
        <header className="maintenance-header">
          <div>
            <p>{t('app.name')}</p>
            <h1>
              {mode === 'edit'
                ? t('calendar.event.editHeading')
                : mode === 'attach-mail'
                  ? t('calendar.event.attachMailHeading')
                  : t('calendar.event.heading')}
            </h1>
          </div>
          <TopNav
            ariaLabelKey="calendar.navigation"
            items={[
              ...(mode !== 'detail'
                ? [
                    {
                      href: `/calendar/events/${encodeURIComponent(eventId)}`,
                      labelKey: 'calendar.event.heading' as const,
                    },
                  ]
                : []),
              { href: '/calendar', labelKey: 'nav.calendar' },
              { href: '/', labelKey: 'top.heading' },
              { href: '/mail', labelKey: 'nav.mail' },
              { href: '/tasks', labelKey: 'nav.tasks' },
              { href: '/cases', labelKey: 'nav.cases' },
            ]}
          />
        </header>

        {isLoading && <p className="mail-empty">{t('common.loading')}</p>}
        {error !== null && (
          <div className="mail-feedback">
            <p role="alert">{error}</p>
          </div>
        )}
        {event !== null && (
          <div className="calendar-event-detail-layout">
            <section className="calendar-panel calendar-event-detail-main">
              <div className="section-heading">
                <div>
                  <p>{event.calendar_source_id ?? '-'}</p>
                  <h2>{event.summary || t('calendar.noTitle')}</h2>
                </div>
                <div className="calendar-event-icon-actions">
                  {mode === 'detail' && (
                    <>
                      <IconAction href={firstCaseLink?.href ?? null} label={t('calendar.event.relatedCases')}>
                        C
                      </IconAction>
                      <IconAction href={firstTaskLink?.href ?? null} label={t('calendar.event.relatedTasks')}>
                        T
                      </IconAction>
                      <IconAction href={firstMailLink?.href ?? null} label={t('calendar.event.relatedMail')}>
                        <img alt="" aria-hidden="true" src={gmailIconUrl} />
                      </IconAction>
                    </>
                  )}
                  {mode === 'detail' ? (
                    <AppLink
                      aria-label={t('calendar.event.edit')}
                      className="case-icon-button"
                      href={`/calendar/events/${encodeURIComponent(eventId)}/edit`}
                    >
                      <img alt="" aria-hidden="true" src={settingsGearIconUrl} />
                    </AppLink>
                  ) : (
                    <AppLink
                      aria-label={t('calendar.event.backToDetail')}
                      className="case-icon-button"
                      href={`/calendar/events/${encodeURIComponent(eventId)}`}
                    >
                      <img alt="" aria-hidden="true" src={settingsGearIconUrl} />
                    </AppLink>
                  )}
                </div>
              </div>

              <div className="calendar-event-summary-row">
                <strong>{formatEventTimeRange(event)}</strong>
                <span>
                  {eventLocationHref === null ? (
                    event.location ?? '-'
                  ) : (
                    <a href={eventLocationHref} rel="noreferrer" target="_blank">
                      {event.location}
                    </a>
                  )}
                </span>
              </div>
              <div className="calendar-event-badges">
                <span>{attendanceLabel(event.attendance_requirement)}</span>
                {eventIsMoving && <span>{t('calendar.event.moving')}</span>}
                <span>{syncLabel(event.sync_status)}</span>
              </div>
              {event.meeting_url !== undefined && event.meeting_url !== null && event.meeting_url.trim() !== '' && (
                <div className="calendar-event-meeting-row">
                  <span>{t('calendar.event.meeting')}</span>
                  <a href={event.meeting_url} rel="noreferrer" target="_blank">
                    {t('calendar.event.openMeeting')}
                  </a>
                </div>
              )}

              {linkError !== null && mode !== 'edit' && (
                <div className="mail-feedback">
                  <p role="alert">{linkError}</p>
                </div>
              )}

              {mode === 'edit' ? (
                <div className="calendar-event-edit-placeholder">
                  {linkError !== null && (
                    <div className="mail-feedback">
                      <p role="alert">{linkError}</p>
                    </div>
                  )}
                  <section className="calendar-event-link-editor">
                    <div className="calendar-event-link-row calendar-event-basics-row">
                      <label className="calendar-event-link-field">
                        <span>{t('calendar.event.title')}</span>
                        <input
                          onChange={(inputEvent) => setSummaryDraft(inputEvent.target.value)}
                          value={summaryDraft}
                        />
                      </label>
                      <label className="calendar-event-link-field">
                        <span>{t('calendar.event.calendarSource')}</span>
                        <select
                          onChange={(inputEvent) => setCalendarIdDraft(inputEvent.target.value)}
                          value={calendarIdDraft}
                        >
                          {calendars.map((calendar) => (
                            <option key={calendar.id} value={calendar.id}>
                              {calendar.summary}
                            </option>
                          ))}
                          {calendars.length === 0 && (
                            <option value={calendarIdDraft}>{calendarIdDraft || '-'}</option>
                          )}
                        </select>
                      </label>
                      <label className="calendar-event-link-field">
                        <span>{t('calendar.event.location')}</span>
                        <input
                          onChange={(inputEvent) => setLocationDraft(inputEvent.target.value)}
                          value={locationDraft}
                        />
                      </label>
                      <label className="calendar-event-link-field">
                        <span>{t('calendar.event.attendance')}</span>
                        <select
                          onChange={(inputEvent) => setAttendanceDraft(inputEvent.target.value)}
                          value={attendanceDraft}
                        >
                          <option value="required">{t('calendar.event.attendanceRequired')}</option>
                          <option value="not_required">{t('calendar.event.attendanceOptional')}</option>
                        </select>
                      </label>
                      <label className="calendar-event-moving-toggle">
                        <input
                          checked={movingDraft}
                          onChange={(inputEvent) => setMovingDraft(inputEvent.target.checked)}
                          type="checkbox"
                        />
                        <span>{t('calendar.event.moving')}</span>
                      </label>
                      <button
                        className={`button-loading-dot${isSavingEvent ? ' is-loading' : ''}`}
                        disabled={isSavingEvent}
                        onClick={() => void saveEventBasics()}
                        type="button"
                      >
                        {t('common.update')}
                      </button>
                    </div>
                  </section>
                  <section className="calendar-event-link-editor">
                    <div className="calendar-event-datetime-row">
                      <label>
                        <span>{t('calendar.event.start')}</span>
                        <input
                          onChange={(inputEvent) => setStartDraft(inputEvent.target.value)}
                          type="datetime-local"
                          value={startDraft}
                        />
                      </label>
                      <label>
                        <span>{t('calendar.event.end')}</span>
                        <input
                          onChange={(inputEvent) => setEndDraft(inputEvent.target.value)}
                          type="datetime-local"
                          value={endDraft}
                        />
                      </label>
                      <button
                        className={`button-loading-dot${isSavingTime ? ' is-loading' : ''}`}
                        disabled={isSavingTime}
                        onClick={() => void saveDateTime()}
                        type="button"
                      >
                        {t('calendar.event.saveDateTime')}
                      </button>
                    </div>
                  </section>
                  <section className="calendar-event-link-editor">
                    <div className="calendar-event-link-row">
                      <h3>{t('calendar.event.linkCases')}</h3>
                      <label className="calendar-event-link-field">
                        <SuggestInput
                          ariaLabel={t('calendar.event.linkCases')}
                          maxItems={1}
                          onChange={setCaseQuery}
                          options={caseSuggestions.map((item) => ({
                            key: item.id,
                            value: item.name,
                            label: item.name,
                            badgeLabel: item.name,
                          }))}
                          placeholder={t('calendar.event.casePlaceholder')}
                          value={caseQuery}
                        />
                      </label>
                      <button
                        disabled={isSavingLink || selectedCase === null}
                        onClick={() => void upsertLink('case', selectedCase?.id ?? null)}
                        type="button"
                      >
                        {caseLinks.length > 0 ? t('common.update') : t('common.add')}
                      </button>
                    </div>
                  </section>
                  <section className="calendar-event-link-editor">
                    <div className="calendar-event-link-row">
                      <h3>{t('calendar.event.linkTasks')}</h3>
                      <label className="calendar-event-link-field">
                        <SuggestInput
                          ariaLabel={t('calendar.event.linkTasks')}
                          maxItems={1}
                          onChange={setTaskQuery}
                          options={taskSuggestions.map((item) => ({
                            key: item.id,
                            value: item.title,
                            label: item.title,
                            badgeLabel: item.title,
                          }))}
                          placeholder={t('calendar.event.taskPlaceholder')}
                          value={taskQuery}
                        />
                      </label>
                      <button
                        disabled={isSavingLink || selectedTask === null}
                        onClick={() => void upsertLink('task', selectedTask?.id ?? null)}
                        type="button"
                      >
                        {taskLinks.length > 0 ? t('common.update') : t('common.add')}
                      </button>
                    </div>
                  </section>
                  <section className="calendar-event-link-editor">
                    <h3>{t('calendar.event.linkMail')}</h3>
                    <CalendarEventMailLinkCard
                      attachHref={`/calendar/events/${encodeURIComponent(eventId)}/attach-mail`}
                      isSaving={isSavingLink}
                      link={firstMailLink ?? mailLinks[0] ?? null}
                      onRemove={(linkId) => void removeLink(linkId)}
                    />
                  </section>
                  <label>
                    <span>{t('calendar.event.localNote')}</span>
                    <textarea readOnly value={event.local_note ?? ''} />
                  </label>
                  <section className="calendar-event-delete-zone">
                    {!isDeleteConfirmOpen ? (
                      <button
                        className="calendar-event-delete-button"
                        onClick={() => setIsDeleteConfirmOpen(true)}
                        type="button"
                      >
                        {t('calendar.event.delete')}
                      </button>
                    ) : (
                      <div className="calendar-event-delete-confirm">
                        <p>{t('calendar.event.deleteConfirm')}</p>
                        {canDeleteSeries && (
                          <fieldset className="calendar-event-delete-scope">
                            <legend>{t('calendar.event.deleteScope')}</legend>
                            <label>
                              <input
                                checked={deleteScope === 'event'}
                                disabled={isDeletingEvent}
                                onChange={() => setDeleteScope('event')}
                                type="radio"
                              />
                              <span>{t('calendar.event.deleteScopeEvent')}</span>
                            </label>
                            <label>
                              <input
                                checked={deleteScope === 'series'}
                                disabled={isDeletingEvent}
                                onChange={() => setDeleteScope('series')}
                                type="radio"
                              />
                              <span>
                                {deleteSeriesKind === 'academic'
                                  ? t('calendar.event.deleteScopeAcademicSeries')
                                  : t('calendar.event.deleteScopeRecurringSeries')}
                              </span>
                            </label>
                          </fieldset>
                        )}
                        <button
                          className={`button-loading-dot${isDeletingEvent ? ' is-loading' : ''}`}
                          disabled={isDeletingEvent}
                          onClick={() => void deleteEvent()}
                          type="button"
                        >
                          {t('calendar.event.deleteConfirmAction')}
                        </button>
                        <button
                          disabled={isDeletingEvent}
                          onClick={() => setIsDeleteConfirmOpen(false)}
                          type="button"
                        >
                          {t('common.cancel')}
                        </button>
                      </div>
                    )}
                  </section>
                  <p>{t('calendar.event.editPlaceholder')}</p>
                </div>
              ) : mode === 'attach-mail' ? (
                <CalendarEventMailAttachView
                  existingMailLink={firstMailLink ?? mailLinks[0] ?? null}
                  isSaving={isSavingLink}
                  isSearching={isSearchingMails}
                  mailPageSize={mailPageSize}
                  mailSearchQuery={mailSearchQuery}
                  mailSort={mailSort}
                  selectedMails={selectedMailItems}
                  searchResults={visibleMailSearchResults}
                  onAttach={() => void attachSelectedMails()}
                  hasExistingMailLink={mailLinks.length > 0}
                  onRefresh={() => setMailSearchRefreshTick((tick) => tick + 1)}
                  onResetSelected={() => setSelectedMails({})}
                  onSearchQueryChange={setMailSearchQuery}
                  onSelectMail={selectMail}
                  onSetPageSize={setMailPageSize}
                  onSetSort={setMailSort}
                  onUnselectMail={unselectMail}
                />
              ) : (
                <>
                  {event.description !== null && event.description.trim() !== '' && (
                    <section className="calendar-event-text-block">
                      <h3>{t('calendar.event.description')}</h3>
                      <p>{event.description}</p>
                    </section>
                  )}
                  {(event.local_note ?? '').trim() !== '' && (
                    <section className="calendar-event-text-block">
                      <h3>{t('calendar.event.localNote')}</h3>
                      <p>{event.local_note ?? ''}</p>
                    </section>
                  )}
                  {mailSummaries.length > 0 && (
                    <section className="calendar-event-text-block calendar-event-mail-summary-block">
                      <h3>{t('calendar.event.mailSummary')}</h3>
                      {mailSummaries.map((summary) => (
                        <article className="calendar-event-mail-summary-card" key={summary.message_id}>
                          <div>
                            <AppLink href={summary.href}>
                              <strong>{summary.subject ?? t('mail.noSubject')}</strong>
                            </AppLink>
                            <span>
                              {summary.from} / {summary.received_at.slice(0, 16).replace('T', ' ')}
                            </span>
                          </div>
                          <p>{summary.summary}</p>
                          {summary.next_action !== null && summary.next_action.trim() !== '' && (
                            <p className="calendar-event-mail-next-action">
                              <strong>{t('calendar.event.mailNextAction')}</strong>
                              {summary.next_action}
                            </p>
                          )}
                        </article>
                      ))}
                    </section>
                  )}
                </>
              )}
            </section>
          </div>
        )}
      </div>
    </main>
  )
}

function IconAction({
  href,
  label,
  children,
}: {
  href: string | null
  label: string
  children: ReactNode
}) {
  if (href === null) {
    return (
      <button aria-label={label} className="case-icon-button" disabled type="button">
        {children}
      </button>
    )
  }
  return (
    <AppLink aria-label={label} className="case-icon-button" href={href}>
      {children}
    </AppLink>
  )
}

function CalendarEventMailLinkCard({
  link,
  isSaving,
  onRemove,
  attachHref,
}: {
  link: CalendarEventDetail['links'][number] | null
  isSaving: boolean
  onRemove?: (linkId: string) => void
  attachHref?: string
}) {
  if (link === null) {
    return (
      <article className="calendar-event-linked-editor-row">
        <div>
          <strong>{t('calendar.event.noLinkedMail')}</strong>
          <span>mail / related</span>
        </div>
        {attachHref !== undefined && (
          <AppLink className="calendar-event-mail-attach-button" href={attachHref}>
            {t('calendar.event.attachMail')}
          </AppLink>
        )}
      </article>
    )
  }
  return (
    <article className="calendar-event-linked-editor-row">
      <div>
        <strong>{link.title ?? link.linked_id}</strong>
        <span>
          {link.linked_type} / {link.role}
        </span>
      </div>
      {onRemove !== undefined && (
        <button disabled={isSaving} onClick={() => onRemove(link.id)} type="button">
          {t('common.delete')}
        </button>
      )}
    </article>
  )
}

function CalendarEventMailAttachView({
  existingMailLink,
  searchResults,
  selectedMails,
  mailSearchQuery,
  mailSort,
  mailPageSize,
  isSearching,
  isSaving,
  hasExistingMailLink,
  onSearchQueryChange,
  onSetSort,
  onSetPageSize,
  onRefresh,
  onSelectMail,
  onUnselectMail,
  onResetSelected,
  onAttach,
}: {
  existingMailLink: CalendarEventDetail['links'][number] | null
  searchResults: MailListItem[]
  selectedMails: MailListItem[]
  mailSearchQuery: string
  mailSort: CalendarMailAssignSort
  mailPageSize: number
  isSearching: boolean
  isSaving: boolean
  hasExistingMailLink: boolean
  onSearchQueryChange: (value: string) => void
  onSetSort: (value: CalendarMailAssignSort) => void
  onSetPageSize: (value: number) => void
  onRefresh: () => void
  onSelectMail: (mail: MailListItem) => void
  onUnselectMail: (mail: MailListItem) => void
  onResetSelected: () => void
  onAttach: () => void
}) {
  const normalizedQuery = mailSearchQuery.trim().toLowerCase()

  function renderMailRow(mail: MailListItem, actionLabel: string, onClick: () => void) {
    return (
      <button
        className={`mail-list-item case-mail-picker-row ${mailPriorityClass(
          mail.effective_importance,
        )} mail-read-${mail.read_status ?? 'unread'}`}
        key={mail.id}
        onClick={onClick}
        type="button"
      >
        <div className="mail-list-sender-media">
          <span className="mail-list-time">{mail.received_at.slice(11, 16)}</span>
          <img
            alt={t('mail.senderAvatarAlt', { name: mailSenderName(mail) })}
            src={mailSenderAvatar(mail)}
          />
        </div>
        <div className="mail-list-main">
          <strong>
            <span>{mail.subject ?? t('mail.noSubject')}</span>
          </strong>
          <span>{mailSenderName(mail)}</span>
        </div>
        <p className="mail-list-summary">{mailSummary(mail)}</p>
        <div className="mail-list-cases">
          {mail.has_attachments === true && (
            <span
              aria-label={t('mail.attachmentsPresent')}
              className="mail-attachment-indicator"
              title={t('mail.attachmentsPresent')}
            >
              <img alt="" src={paperclipDiagonalUrl} />
            </span>
          )}
          <span>{actionLabel}</span>
        </div>
      </button>
    )
  }

  function renderMailList(mails: MailListItem[], actionLabel: string, onClick: (mail: MailListItem) => void) {
    return (
      <div className="mail-list case-mail-picker-list" role="list">
        {mails.map((mail, index) => (
          <div className="mail-list-entry" key={mail.id}>
            {shouldShowMailGroupLabel(mail, index, mails, mailSort) && (
              <div className="mail-list-group-label">
                <span>{mailGroupLabel(mail, mailSort)}</span>
              </div>
            )}
            {shouldShowImportanceThreshold(mail, index, mails, mailSort) && (
              <div aria-hidden="true" className="mail-importance-threshold" />
            )}
            {renderMailRow(mail, actionLabel, () => onClick(mail))}
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="mail-main-layout calendar-event-mail-attach-layout">
      <div className="mail-main-column">
        <section aria-labelledby="calendar-event-mail-search-heading" className="mail-list-workspace">
          <div className="mail-panel mail-list-panel">
            <div className="section-heading">
              <div>
                <h2 id="calendar-event-mail-search-heading">{t('mail.search.results')}</h2>
                <p>{t('mail.search.resultNote')}</p>
              </div>
              <button
                className={`button-loading-dot${isSearching ? ' is-loading' : ''}`}
                disabled={isSearching}
                onClick={onRefresh}
                type="button"
              >
                {t('mail.refresh')}
              </button>
            </div>

            {selectedMails.length > 0 && (
              <div className="mail-list case-mail-picker-list case-mail-pinned-list" role="list">
                <div className="mail-list-entry">
                  <div className="mail-list-group-label">
                    <span>{t('calendar.event.mailSelected')}</span>
                  </div>
                </div>
                {selectedMails.map((mail) => (
                  <div className="mail-list-entry" key={mailThreadKey(mail)}>
                    {renderMailRow(mail, t('calendar.event.mailUnselect'), () => onUnselectMail(mail))}
                  </div>
                ))}
              </div>
            )}

            {normalizedQuery === '' ? (
              <p className="mail-empty">{t('calendar.event.mailSelectPrompt')}</p>
            ) : isSearching ? (
              <p className="mail-empty">{t('mail.loading')}</p>
            ) : searchResults.length === 0 ? (
              <p className="mail-empty">{t('mail.search.empty')}</p>
            ) : (
              renderMailList(searchResults, t('calendar.event.mailSelect'), onSelectMail)
            )}
          </div>
        </section>
      </div>

      <aside className="mail-side-column">
        <section aria-labelledby="calendar-event-mail-sort-heading" className="mail-panel mail-sort-panel">
          <div className="section-heading">
            <h2 id="calendar-event-mail-sort-heading">{t('mail.sort.heading')}</h2>
          </div>
          <div aria-label={t('mail.sort.label')} className="mail-sort-control">
            <button
              aria-pressed={mailSort === 'importance'}
              onClick={() => onSetSort('importance')}
              type="button"
            >
              {t('mail.sort.importance')}
            </button>
            <button
              aria-pressed={mailSort === 'newest'}
              onClick={() => onSetSort('newest')}
              type="button"
            >
              {t('mail.sort.newest')}
            </button>
          </div>
        </section>

        <section aria-labelledby="calendar-event-mail-search-tools-heading" className="mail-panel mail-search-panel">
          <div className="section-heading">
            <h2 id="calendar-event-mail-search-tools-heading">{t('mail.search.heading')}</h2>
          </div>
          <form
            className="mail-search-form"
            onSubmit={(event) => {
              event.preventDefault()
              onRefresh()
            }}
          >
            <input
              aria-label={t('mail.search.label')}
              onChange={(event) => onSearchQueryChange(event.target.value)}
              placeholder={t('mail.search.placeholder')}
              value={mailSearchQuery}
            />
            <select
              aria-label={t('mail.pageSize')}
              onChange={(event) => onSetPageSize(Number(event.target.value))}
              value={mailPageSize}
            >
              <option value={10}>10</option>
              <option value={25}>25</option>
              <option value={50}>50</option>
            </select>
            <div className="mail-search-actions">
              <button
                className={`button-loading-dot${isSearching ? ' is-loading' : ''}`}
                disabled={isSearching}
                type="submit"
              >
                {t('mail.search.submit')}
              </button>
              <button
                disabled={isSearching || mailSearchQuery.trim() === ''}
                onClick={() => onSearchQueryChange('')}
                type="button"
              >
                {t('mail.search.clear')}
              </button>
            </div>
          </form>
        </section>

        <section aria-labelledby="calendar-event-mail-selected-heading" className="mail-panel mail-search-panel">
          <div className="section-heading">
            <h2 id="calendar-event-mail-selected-heading">{t('calendar.event.mailSelection')}</h2>
          </div>
          {existingMailLink !== null && (
            <div className="calendar-event-current-mail-link">
              <h3>{t('calendar.event.relatedMail')}</h3>
              <CalendarEventMailLinkCard
                isSaving={isSaving}
                link={existingMailLink}
              />
            </div>
          )}
          <div className="case-mail-pin-actions">
            <button disabled={selectedMails.length === 0} onClick={onResetSelected} type="button">
              {t('calendar.event.mailClearSelection')}
            </button>
            <button
              className={`button-loading-dot${isSaving ? ' is-loading' : ''}`}
              disabled={isSaving || selectedMails.length === 0}
              onClick={onAttach}
              type="button"
            >
              {hasExistingMailLink ? t('common.update') : t('calendar.event.attachMail')}
            </button>
          </div>
          <p className="case-mail-pin-note">
            {t('calendar.event.mailSelectedCount', { count: String(selectedMails.length) })}
          </p>
        </section>
      </aside>
    </div>
  )
}
