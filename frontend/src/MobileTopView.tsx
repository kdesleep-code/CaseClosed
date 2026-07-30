import { useEffect, useMemo, useState } from 'react'
import { t } from './i18n'
import { AppLink } from './navigation'
import { listUnresolvedFromAddresses } from './phase3Api'
import { listCalendarDbEvents, listMailPage } from './phase4Api'
import type { GoogleCalendarEvent, MailListItem } from './phase4Api'
import { readMaintenanceStatus } from './phase2Api'
import type { MaintenanceStatus } from './phase2Api'
import { listTasks } from './phase8Api'
import type { TaskItem } from './phase8Api'
import { loadMobileQuickSlot, readMobileQuickSlot } from './mobileQuickSlot'
import type { MobileQuickSlot } from './mobileQuickSlot'
import './MobileTopView.css'

type MobileTopData = {
  pendingContacts: number
  actionMails: MailListItem[]
  tasks: TaskItem[]
  events: GoogleCalendarEvent[]
  maintenance: MaintenanceStatus | null
}

function uniqueTasks(tasks: TaskItem[]) {
  const seen = new Set<string>()
  const result: TaskItem[] = []
  for (const task of tasks) {
    if (seen.has(task.id)) continue
    seen.add(task.id)
    result.push(task)
  }
  return result
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

function shortDateTime(value: string | null | undefined) {
  if (value === null || value === undefined || value === '') return null
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value.slice(0, 16)
  return new Intl.DateTimeFormat('ja-JP', {
    timeZone: 'Asia/Tokyo',
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(date)
}

function mailSender(mail: MailListItem) {
  return mail.from_name ?? mail.sender_contact?.display_name ?? mail.from_address
}

function taskMeta(task: TaskItem) {
  const due = shortDateTime(task.due_at)
  if (task.case_name !== null && due !== null) return `${task.case_name} / ${due}`
  if (task.case_name !== null) return task.case_name
  if (due !== null) return due
  return t('mobile.top.unassignedCase')
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

function eventSortRank(event: GoogleCalendarEvent) {
  const startValue = eventStartValue(event)
  if (startValue.length <= 10) return -1
  return Number(startValue.slice(11, 13)) * 60 + Number(startValue.slice(14, 16))
}

function sortEvents(events: GoogleCalendarEvent[]) {
  return [...events].sort((left, right) => {
    const rankDiff = eventSortRank(left) - eventSortRank(right)
    if (rankDiff !== 0) return rankDiff
    return left.summary.localeCompare(right.summary)
  })
}

function eventHref(today: string) {
  return `/m/calendar?date=${today}`
}

function maintenanceCount(status: MaintenanceStatus | null) {
  if (status === null) return 0
  return (status.action_required_jobs ?? 0) + status.external_unknown_count
}

export default function MobileTopView() {
  const [today] = useState(() => jstDateToday())
  const [data, setData] = useState<MobileTopData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [quickSlot, setQuickSlot] = useState<MobileQuickSlot | null>(() => readMobileQuickSlot())

  useEffect(() => {
    let isMounted = true
    Promise.all([
      listUnresolvedFromAddresses(),
      listMailPage({ tab: 'all', needs_action: true, limit: 4 }),
      listTasks({ status: 'open', due: 'overdue', limit: 4 }),
      listTasks({ status: 'open', due: 'today', limit: 4 }),
      listCalendarDbEvents({ time_min: startOfDate(today), time_max: endOfDate(today) }),
      readMaintenanceStatus(),
      loadMobileQuickSlot().catch(() => readMobileQuickSlot()),
    ])
      .then(([pendingContacts, actionMailPage, overdueTasks, todayTasks, calendarPage, maintenance, loadedQuickSlot]) => {
        if (!isMounted) return
        setQuickSlot(loadedQuickSlot)
        setData({
          pendingContacts: pendingContacts.length,
          actionMails: actionMailPage.items,
          tasks: uniqueTasks([...overdueTasks, ...todayTasks]).slice(0, 4),
          events: sortEvents(calendarPage.items.filter((event) => eventDisplayDates(event).includes(today))),
          maintenance,
        })
      })
      .catch((requestError) => {
        if (!isMounted) return
        setError(requestError instanceof Error ? requestError.message : t('mobile.top.loadFailed'))
      })
    return () => {
      isMounted = false
    }
  }, [today])

  const counts = useMemo(() => {
    return {
      pendingContacts: data?.pendingContacts ?? 0,
      actionMails: data?.actionMails.length ?? 0,
      tasks: data?.tasks.length ?? 0,
      events: data?.events.length ?? 0,
      maintenance: maintenanceCount(data?.maintenance ?? null),
    }
  }, [data])

  return (
    <main className="mobile-shell">
      <header className="mobile-topbar">
        <div>
          <p>C@seClosed</p>
          <h1>{t('mobile.top.heading')}</h1>
        </div>
        <AppLink className="mobile-topbar-link" href="/?view=desktop">
          {t('mobile.desktopVersion')}
        </AppLink>
      </header>

      {error !== null && <p className="mobile-alert" role="alert">{error}</p>}

      {data === null && error === null ? (
        <p className="mobile-loading">{t('common.loading')}</p>
      ) : (
        <>
          <section className="mobile-primary-grid" aria-label="Primary actions">
            <AppLink className="mobile-panel mobile-primary-card mobile-primary-card-link" href="/m/mail/action-needed">
              <div className="mobile-panel-heading">
                <h2>{t('mobile.top.actionMailHeading')}</h2>
              </div>
              <strong className="mobile-primary-count">{counts.actionMails}</strong>
              {data?.actionMails.length === 0 ? (
                <p className="mobile-empty">{t('mobile.top.actionMailEmpty')}</p>
              ) : (
                <ul className="mobile-list compact">
                  {data?.actionMails.slice(0, 2).map((mail) => (
                    <li key={mail.id}>
                      <div className="mobile-list-static-row">
                        <strong>{mail.subject ?? t('mail.noSubject')}</strong>
                        <span>{mailSender(mail)}</span>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </AppLink>

            <AppLink className="mobile-panel mobile-primary-card mobile-primary-card-link" href="/m/tasks">
              <div className="mobile-panel-heading">
                <h2>{t('mobile.top.todayTasksHeading')}</h2>
              </div>
              <strong className="mobile-primary-count">{counts.tasks}</strong>
              {data?.tasks.length === 0 ? (
                <p className="mobile-empty">{t('mobile.top.todayTasksEmpty')}</p>
              ) : (
                <ul className="mobile-list compact">
                  {data?.tasks.slice(0, 2).map((task) => (
                    <li key={task.id}>
                      <div className="mobile-list-static-row">
                        <strong>{task.title}</strong>
                        <span>{taskMeta(task)}</span>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </AppLink>
          </section>

          <section className="mobile-panel mobile-calendar-panel">
            <div className="mobile-panel-heading">
              <h2>{t('mobile.top.todayEventsHeading')}</h2>
              <AppLink href={`/m/calendar?date=${today}`}>{t('calendar.heading')}</AppLink>
            </div>
            {data?.events.length === 0 ? (
              <p className="mobile-empty">{t('mobile.top.todayEventsEmpty')}</p>
            ) : (
              <ol className="mobile-agenda-list">
                {data?.events.map((event) => (
                  <li key={event.id ?? `${event.summary}-${eventTime(event)}`}>
                    <AppLink href={eventHref(today)}>
                      <time>{eventTime(event)}</time>
                      <strong>{event.summary || t('mobile.noTitle')}</strong>
                    </AppLink>
                  </li>
                ))}
              </ol>
            )}
          </section>

          <nav aria-label="Mobile navigation" className="mobile-nav-grid mobile-nav-grid-primary">
            <AppLink href={`/m/mail?date=${today}`}>{t('nav.mail')}</AppLink>
            <AppLink href="/m/tasks">{t('nav.tasks')}</AppLink>
            <AppLink href={`/m/calendar?date=${today}`}>{t('calendar.heading')}</AppLink>
            <AppLink href="/pomodoro">{t('nav.pomodoro')}</AppLink>
            {quickSlot === null ? (
              <span className="mobile-nav-empty" aria-label={t('mobile.quickSlot.empty')} />
            ) : (
              <AppLink href={quickSlot.href}>{quickSlot.label}</AppLink>
            )}
            <AppLink href="/m/settings">{t('nav.settings')}</AppLink>
          </nav>

          {counts.pendingContacts > 0 && (
            <section className="mobile-panel mobile-panel-warn">
              <div>
                <h2>{t('pendingContactRedirect.heading')}</h2>
                <p>{t('mobile.top.pendingContactsBody')}</p>
              </div>
              <AppLink href="/contacts/pending">{t('mail.blocked.openPending')}</AppLink>
            </section>
          )}
        </>
      )}
    </main>
  )
}
