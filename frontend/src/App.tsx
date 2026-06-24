import { useEffect, useRef, useState } from 'react'
import type { CSSProperties, FormEvent } from 'react'
import { AuthApiError, login, readSession } from './authApi'
import type { SessionData } from './authApi'
import AcademicCalendarView from './AcademicCalendarView'
import loginDoorTanuki from './assets/login-door-tanuki.png'
import settingsGearIconUrl from './assets/settings-gear.svg'
import pomodoroBellUrl from './assets/pomodoro-school-bell.mp3'
import CalendarView from './CalendarView'
import CalendarEventDetailView from './CalendarEventDetailView'
import CalendarNewEventView from './CalendarNewEventView'
import CaseTaskBatchGenerateView from './CaseTaskBatchGenerateView'
import CaseView from './CaseView'
import ComposeMailView from './ComposeMailView'
import ContactsView from './ContactsView'
import type { ContactsInitialData } from './ContactsView'
import ExtensionLaunchView from './ExtensionLaunchView'
import ExtensionsHelpView from './ExtensionsHelpView'
import ExtensionsView from './ExtensionsView'
import FollowUpView from './FollowUpView'
import LogView from './LogView'
import ManualView from './ManualView'
import MailView from './MailView'
import type { MailInitialData } from './MailView'
import type { MailTab } from './MailView'
import MailThreadView from './MailThreadView'
import MaintenanceView from './MaintenanceView'
import type { MaintenanceInitialData } from './MaintenanceView'
import ProfileView from './ProfileView'
import SettingsView from './SettingsView'
import StorageView from './StorageView'
import TaskDetailView from './TaskDetailView'
import TaskNewView from './TaskNewView'
import TaskView from './TaskView'
import TodayView from './TodayView'
import {
  createExternalTool,
  deleteExternalTool,
  listExternalTools,
  reorderExternalTools,
  updateExternalTool,
} from './externalToolsApi'
import type { ExternalToolLink } from './externalToolsApi'
import { t } from './i18n'
import type { MessageKey } from './i18n'
import { AppLink, TopNav, naturalReturnTargetFromLocation, returnToFromLocation } from './navigation'
import {
  listExternalOperations,
  listJobs,
  listPendingMails,
  readMaintenanceStatus,
} from './phase2Api'
import {
  createFileIconSetting,
  deleteFileIconSetting,
  listContacts,
  listFileIconSettings,
  listUnresolvedFromAddresses,
  updateFileIconSetting,
} from './phase3Api'
import type { FileIconSetting } from './phase3Api'
import {
  createCaseToolIconSetting,
  deleteCaseToolIconSetting,
  listCaseToolIconSettings,
  updateCaseToolIconSetting,
} from './phase7Api'
import type { CaseToolIconSetting } from './phase7Api'
import { listMailDates, listMailPage } from './phase4Api'
import {
  pendingContactRedirectEventName,
  type PendingContactRedirectEvent,
} from './pendingContactRedirect'
import './App.css'

type LinkItem = {
  labelKey: MessageKey
  href: string
  target?: '_blank'
  rel?: string
}

type LinkRenderItem = LinkItem & {
  label?: string
}

type PageSlot = LinkItem | { blank: true; key: string }

const pageLinks: LinkItem[] = [
  { labelKey: 'nav.mail', href: '/mail' },
  { labelKey: 'nav.cases', href: '/cases' },
  { labelKey: 'nav.tasks', href: '/tasks' },
  { labelKey: 'nav.calendar', href: '/calendar' },
  { labelKey: 'nav.contacts', href: '/contacts' },
  { labelKey: 'nav.files', href: '/files' },
  { labelKey: 'nav.externalTools', href: '/external-tools' },
  { labelKey: 'nav.extensions', href: '/extensions' },
  { labelKey: 'nav.pomodoro', href: '/pomodoro', target: '_blank', rel: 'noopener noreferrer' },
]

const mainPageSlots: PageSlot[] = [
  ...pageLinks,
]

const utilityPageSlots: PageSlot[] = [
  { labelKey: 'nav.logs', href: '/logs' },
  { labelKey: 'nav.settings', href: '/settings' },
  { labelKey: 'nav.maintenance', href: '/maintenance' },
  { labelKey: 'nav.profile', href: '/profile' },
  { labelKey: 'nav.manual', href: '/manual' },
  { blank: true, key: 'reserved-2' },
]

type RoutePreload =
  | { path: '/'; pendingCount: number }
  | { path: '/mail'; pendingCount: number; mail?: MailInitialData }
  | { path: '/mail/action-needed'; pendingCount: number; mail?: MailInitialData }
  | { path: '/contacts'; contacts: ContactsInitialData }
  | { path: '/contacts/pending'; contacts: ContactsInitialData }
  | { path: '/maintenance'; maintenance: MaintenanceInitialData }
  | { path: 'other'; routePath: string }

type NavigationRequestEvent = CustomEvent<{
  path: string
  replace: boolean
}>

type PendingContactNotice = {
  count: number
  deadlineAt: number
}

function formatJstDateTime(value: string | null) {
  if (value === null) {
    return t('time.unavailable')
  }

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
    .reduce<Record<string, string>>((dateParts, part) => {
      dateParts[part.type] = part.value
      return dateParts
    }, {})

  return `${parts.year}/${parts.month}/${parts.day} ${parts.hour}:${parts.minute} JST`
}

function jstDateToday() {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Tokyo',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
    .formatToParts(new Date())
    .reduce<Record<string, string>>((dateParts, part) => {
      dateParts[part.type] = part.value
      return dateParts
    }, {})

  return `${parts.year}-${parts.month}-${parts.day}`
}

function formatTopTodayLabel() {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Tokyo',
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    weekday: 'short',
  })
    .formatToParts(new Date())
    .reduce<Record<string, string>>((dateParts, part) => {
      dateParts[part.type] = part.value
      return dateParts
    }, {})

  return `${parts.year}/${parts.month}./${parts.day} ${parts.weekday}.`
}

function topTodayClassName() {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Tokyo',
    weekday: 'short',
  }).formatToParts(new Date())
  const weekday = parts.find((part) => part.type === 'weekday')?.value
  if (weekday === 'Sat') {
    return 'is-saturday'
  }
  if (weekday === 'Sun') {
    return 'is-sunday'
  }
  return undefined
}

function linkLabel(link: LinkRenderItem) {
  return link.label ?? t(link.labelKey)
}

function startOfDate(date: string) {
  return `${date}T00:00:00+09:00`
}

function endOfDate(date: string) {
  return `${date}T23:59:59+09:00`
}

function currentBrowserPath() {
  return window.location.pathname + window.location.search + window.location.hash
}

function isEditableShortcutTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) {
    return false
  }
  const tagName = target.tagName.toLowerCase()
  return (
    tagName === 'input' ||
    tagName === 'textarea' ||
    tagName === 'select' ||
    target.isContentEditable
  )
}

function mailTabFromSearchParams(params: URLSearchParams): MailTab {
  const requestedTab = params.get('tab')
  return requestedTab === 'processed' || requestedTab === 'skip'
    ? requestedTab
    : 'unprocessed'
}

function requestedDateFromSearchParams(params: URLSearchParams): string | null {
  const requestedDate = params.get('date')
  return requestedDate !== null && /^\d{4}-\d{2}-\d{2}$/.test(requestedDate)
    ? requestedDate
    : null
}

async function loadMailInitialData(
  routeUrl: URL,
  viewMode: MailInitialData['viewMode'] = 'normal',
): Promise<MailInitialData> {
  const activeTab = mailTabFromSearchParams(routeUrl.searchParams)
  const requestedDate = requestedDateFromSearchParams(routeUrl.searchParams)
  const mailDates = viewMode === 'action-needed' ? [] : await listMailDates(activeTab)
  const today = jstDateToday()
  const selectedDate =
    requestedDate ??
    (mailDates.some((item) => item.date === today)
      ? today
      : mailDates.at(-1)?.date ?? today)
  const page =
    viewMode === 'action-needed'
      ? await listMailPage({
          tab: 'all',
          needs_action: true,
          limit: 25,
        })
      : await listMailPage({
          tab: activeTab,
          date_from: startOfDate(selectedDate),
          date_to: endOfDate(selectedDate),
          limit: 25,
        })

  return {
    mails: page.items,
    mailDates,
    nextCursor: page.next_cursor,
    activeTab,
    selectedDate,
    calendarMonth: selectedDate,
    viewMode,
  }
}

async function preloadRoute(path: string): Promise<RoutePreload> {
  const routeUrl = new URL(path, window.location.origin)
  const routePath = routeUrl.pathname

  if (routePath === '/') {
    const pendingContacts = await listUnresolvedFromAddresses()
    return { path: '/', pendingCount: pendingContacts.length }
  }

  if (routePath === '/maintenance') {
    const [status, jobs, operations, pendingMails] = await Promise.all([
      readMaintenanceStatus(),
      listJobs(),
      listExternalOperations(),
      listPendingMails(),
    ])
    return {
      path: '/maintenance',
      maintenance: { status, jobs, operations, pendingMails },
    }
  }

  if (routePath === '/contacts') {
    const contacts = await listContacts()
    return { path: '/contacts', contacts: { mode: 'list', contacts } }
  }

  if (routePath === '/contacts/pending') {
    const [unresolvedFromAddresses, contacts] = await Promise.all([
      listUnresolvedFromAddresses(),
      listContacts(),
    ])
    return {
      path: '/contacts/pending',
      contacts: { mode: 'pending', contacts, unresolvedFromAddresses },
    }
  }

  if (routePath === '/mail' || routePath === '/mail/action-needed') {
    const pendingContacts = await listUnresolvedFromAddresses()
    if (pendingContacts.length > 0) {
      return { path: routePath, pendingCount: pendingContacts.length }
    }

    const mail = await loadMailInitialData(
      routeUrl,
      routePath === '/mail/action-needed' ? 'action-needed' : 'normal',
    )
    return {
      path: routePath,
      pendingCount: 0,
      mail,
    }
  }

  return { path: 'other', routePath: path }
}

function MailRouteGate({ viewMode = 'normal' }: { viewMode?: MailInitialData['viewMode'] }) {
  const [pendingCount, setPendingCount] = useState<number | null>(null)
  const [initialMail, setInitialMail] = useState<MailInitialData | null>(null)
  const [gateError, setGateError] = useState<string | null>(null)

  useEffect(() => {
    let isMounted = true
    listUnresolvedFromAddresses()
      .then(async (items) => {
        if (isMounted) {
          if (items.length > 0) {
            setPendingCount(items.length)
            return
          }
          const mail = await loadMailInitialData(
            new URL(currentBrowserPath(), window.location.origin),
            viewMode,
          )
          if (isMounted) {
            setPendingCount(0)
            setInitialMail(mail)
          }
        }
      })
      .catch((requestError) => {
        if (isMounted) {
          setGateError(requestError instanceof Error ? requestError.message : t('app.requestFailed'))
        }
      })

    return () => {
      isMounted = false
    }
  }, [])

  if (gateError !== null) {
    return (
      <main className="app-shell">
        <div className="mail-shell">
          <header className="maintenance-header">
            <div>
              <p>{t('app.name')}</p>
              <h1>{t('mail.heading')}</h1>
            </div>
            <AppLink href="/">{t('top.heading')}</AppLink>
          </header>
          <div className="mail-feedback">
            <p role="alert">{gateError}</p>
          </div>
        </div>
      </main>
    )
  }

  if (pendingCount === null || (pendingCount === 0 && initialMail === null)) {
    return (
      <main className="app-shell">
        <div className="mail-shell">
          <header className="maintenance-header">
            <div>
              <p>{t('app.name')}</p>
              <h1>{t('mail.heading')}</h1>
            </div>
            <AppLink href="/">{t('top.heading')}</AppLink>
          </header>
          <p className="mail-empty">{t('session.checking.label')}</p>
        </div>
      </main>
    )
  }

  if (pendingCount > 0) {
    return (
      <main className="app-shell">
        <div className="mail-shell">
          <header className="maintenance-header">
            <div>
              <p>{t('app.name')}</p>
              <h1>{t('mail.heading')}</h1>
            </div>
            <AppLink href="/">{t('top.heading')}</AppLink>
          </header>
          <section className="mail-panel mail-blocked-panel">
            <h2>{t('mail.blocked.heading')}</h2>
            <p>{t('mail.blocked.body')}</p>
            <strong>{t('mail.blocked.count', { count: String(pendingCount) })}</strong>
            <div className="mail-actions">
              <AppLink href="/contacts/pending">{t('mail.blocked.openPending')}</AppLink>
            </div>
          </section>
        </div>
      </main>
    )
  }

  if (initialMail === null) {
    return null
  }

  return <MailView initialData={initialMail} />
}

function PreloadedMailRoute({
  preload,
  viewMode = 'normal',
}: {
  preload?: RoutePreload
  viewMode?: MailInitialData['viewMode']
}) {
  if (
    (preload?.path === '/mail' || preload?.path === '/mail/action-needed') &&
    preload.pendingCount > 0
  ) {
    return (
      <main className="app-shell">
        <div className="mail-shell">
          <header className="maintenance-header">
            <div>
              <p>{t('app.name')}</p>
              <h1>{t('mail.heading')}</h1>
            </div>
            <AppLink href="/">{t('top.heading')}</AppLink>
          </header>
          <section className="mail-panel mail-blocked-panel">
            <h2>{t('mail.blocked.heading')}</h2>
            <p>{t('mail.blocked.body')}</p>
            <strong>{t('mail.blocked.count', { count: String(preload.pendingCount) })}</strong>
            <div className="mail-actions">
              <AppLink href="/contacts/pending">{t('mail.blocked.openPending')}</AppLink>
            </div>
          </section>
        </div>
      </main>
    )
  }

  if (
    (preload?.path === '/mail' || preload?.path === '/mail/action-needed') &&
    preload.mail !== undefined
  ) {
    const routeKey = [
      preload.path,
      preload.mail.viewMode,
      preload.mail.activeTab,
      preload.mail.selectedDate,
    ].join(':')
    return <MailView key={routeKey} initialData={preload.mail} />
  }

  return <MailRouteGate viewMode={viewMode} />
}

function TopView({
  session,
  sessionExpiresAt,
  initialPendingCount,
}: {
  session: SessionData
  sessionExpiresAt: string | null
  initialPendingCount?: number
}) {
  const [pendingCount, setPendingCount] = useState<number | null>(
    initialPendingCount ?? null,
  )
  const [pendingError, setPendingError] = useState<string | null>(null)

  useEffect(() => {
    if (initialPendingCount !== undefined) {
      return
    }
    let isMounted = true
    listUnresolvedFromAddresses()
      .then((items) => {
        if (isMounted) {
          setPendingCount(items.length)
        }
      })
      .catch((requestError) => {
        if (isMounted) {
          setPendingError(
            requestError instanceof Error ? requestError.message : t('app.requestFailed'),
          )
        }
      })

    return () => {
      isMounted = false
    }
  }, [initialPendingCount])

  const isLockedByPending = pendingCount !== null && pendingCount > 0

  function openPomodoroWindow() {
    const width = 420
    const height = 620
    const margin = 24
    const screen = window.screen as Screen & { availLeft?: number; availTop?: number }
    const left = Math.max(0, (screen.availLeft ?? 0) + screen.availWidth - width - margin)
    const top = Math.max(0, (screen.availTop ?? 0) + screen.availHeight - height - margin)
    const features = [
      'popup=yes',
      `width=${width}`,
      `height=${height}`,
      `left=${Math.round(left)}`,
      `top=${Math.round(top)}`,
      'resizable=yes',
      'scrollbars=yes',
    ].join(',')
    const popup = window.open('', 'caseclosed-pomodoro', features)
    if (popup === null) {
      window.open('/pomodoro', '_blank')
      return
    }
    try {
      if (popup.location.href !== 'about:blank') {
        popup.focus()
        return
      }
    } catch {
      popup.focus()
      return
    }
    try {
      popup.opener = null
      popup.document.write(
        '<!doctype html><title>Pomodoro Timer</title><style>html,body{margin:0;min-height:100%;background:#fbf1df;color:#5a321f;font-family:system-ui,sans-serif;}</style>',
      )
      popup.document.close()
      popup.location.replace('/pomodoro')
      popup.focus()
    } catch {
      popup.location.href = '/pomodoro'
    }
  }

  function lockedLink(link: LinkRenderItem, className?: string) {
    if (!isLockedByPending || link.href === '/maintenance') {
      return (
        <AppLink
          className={className}
          href={link.href}
          key={link.href}
          onClick={link.href === '/pomodoro'
            ? (event) => {
                event.preventDefault()
                openPomodoroWindow()
              }
            : undefined}
          rel={link.rel}
          target={link.target}
        >
          {linkLabel(link)}
        </AppLink>
      )
    }
    return (
      <span aria-disabled="true" className={className} key={link.href}>
        {linkLabel(link)}
      </span>
    )
  }

  function pageSlot(slot: PageSlot) {
    if ('blank' in slot) {
      return <span aria-hidden="true" className="hub-link-placeholder" key={slot.key} />
    }
    return lockedLink(slot)
  }

  return (
    <main className="app-shell">
      <div className={`top-shell${isLockedByPending ? ' top-shell-locked' : ''}`}>
        <header className="top-header">
          <div>
            <p>{t('app.name')}</p>
            <h1>{t('top.heading')}</h1>
          </div>

          <p aria-label={t('session.current.label')} className="session-meta">
            {t('session.prefix')}{' '}
            {session.device_name ??
              (session.ip_address !== null
                ? `IP ${session.ip_address}`
                : t('session.loginSourceUnavailable'))}{' '}
            | {t('session.expires')} {formatJstDateTime(sessionExpiresAt)}
          </p>
        </header>

        {pendingError !== null && (
          <div className="mail-feedback">
            <p role="alert">{pendingError}</p>
          </div>
        )}

        {isLockedByPending && (
          <section className="top-pending-lock">
            <div>
              <h2>{t('top.pendingLock.heading')}</h2>
              <p>{t('top.pendingLock.body')}</p>
            </div>
            <strong>{t('mail.blocked.count', { count: String(pendingCount) })}</strong>
            <AppLink href="/contacts/pending">{t('mail.blocked.openPending')}</AppLink>
          </section>
        )}

        <div className="top-today-link">
          {lockedLink(
            { labelKey: 'nav.today', href: '/today', label: formatTopTodayLabel() },
            topTodayClassName(),
          )}
        </div>

        <section aria-label={t('top.pages.heading')} className="hub-section">
          <nav aria-label={t('top.pages.navLabel')} className="hub-links">
            <div className="hub-links-main">
              {mainPageSlots.map((slot) => pageSlot(slot))}
            </div>
            <div className="hub-links-utility">
              {utilityPageSlots.map((slot) => pageSlot(slot))}
            </div>
          </nav>
        </section>
      </div>
    </main>
  )
}

type PomodoroPhase = 'work' | 'break' | 'done'

function PomodoroView() {
  const [workMinutes, setWorkMinutes] = useState(25)
  const [breakMinutes, setBreakMinutes] = useState(5)
  const [cycleCount, setCycleCount] = useState(4)
  const [phase, setPhase] = useState<PomodoroPhase>('work')
  const [currentCycle, setCurrentCycle] = useState(1)
  const [remainingSeconds, setRemainingSeconds] = useState(25 * 60)
  const [isRunning, setIsRunning] = useState(false)
  const [isSettingsOpen, setIsSettingsOpen] = useState(false)
  const bellAudioRef = useRef<HTMLAudioElement | null>(null)

  const totalSeconds = phase === 'break' ? breakMinutes * 60 : workMinutes * 60
  const progress =
    phase === 'done' || totalSeconds <= 0
      ? 1
      : Math.min(1, Math.max(0, (totalSeconds - remainingSeconds) / totalSeconds))
  const minutes = Math.floor(remainingSeconds / 60)
  const seconds = remainingSeconds % 60
  const timeLabel = `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`

  useEffect(() => {
    if (!isRunning || phase === 'done') {
      return undefined
    }

    const timerId = window.setInterval(() => {
      setRemainingSeconds((current) => Math.max(0, current - 1))
    }, 1000)
    return () => window.clearInterval(timerId)
  }, [isRunning, phase])

  function bellAudio() {
    const audio = bellAudioRef.current ?? new Audio(pomodoroBellUrl)
    bellAudioRef.current = audio
    audio.preload = 'auto'
    return audio
  }

  function prepareTransitionBell() {
    bellAudio().load()
  }

  function playTransitionBell() {
    const audio = bellAudio()
    audio.pause()
    audio.currentTime = 0
    void audio.play().catch(() => undefined)
  }

  useEffect(() => {
    if (remainingSeconds > 0 || phase === 'done') {
      return
    }
    playTransitionBell()
    if (phase === 'work') {
      setPhase('break')
      setRemainingSeconds(breakMinutes * 60)
      return
    }
    if (currentCycle >= cycleCount) {
      setPhase('done')
      setIsRunning(false)
      setRemainingSeconds(0)
      return
    }
    setCurrentCycle((cycle) => cycle + 1)
    setPhase('work')
    setRemainingSeconds(workMinutes * 60)
  }, [breakMinutes, currentCycle, cycleCount, phase, remainingSeconds, workMinutes])

  function resetTimer(nextWorkMinutes = workMinutes) {
    setIsRunning(false)
    setPhase('work')
    setCurrentCycle(1)
    setRemainingSeconds(nextWorkMinutes * 60)
  }

  function handleSettingsSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const normalizedWorkMinutes = Math.min(180, Math.max(1, Math.round(workMinutes)))
    const normalizedBreakMinutes = Math.min(60, Math.max(1, Math.round(breakMinutes)))
    const normalizedCycleCount = Math.min(24, Math.max(1, Math.round(cycleCount)))
    setWorkMinutes(normalizedWorkMinutes)
    setBreakMinutes(normalizedBreakMinutes)
    setCycleCount(normalizedCycleCount)
    setIsSettingsOpen(false)
    resetTimer(normalizedWorkMinutes)
  }

  function skipPhase() {
    setRemainingSeconds(0)
  }

  return (
    <main className="app-shell pomodoro-app">
      <div className="maintenance-shell pomodoro-shell">
        <header className="maintenance-header pomodoro-header">
          <div>
            <p>{t('app.name')}</p>
            <div className="pomodoro-title-row">
              <h1>{t('pomodoro.heading')}</h1>
              <button
                aria-expanded={isSettingsOpen}
                aria-label={t('pomodoro.settings')}
                className="pomodoro-settings-toggle"
                onClick={() => setIsSettingsOpen((isOpen) => !isOpen)}
                title={t('pomodoro.settings')}
                type="button"
              >
                <img alt="" aria-hidden="true" src={settingsGearIconUrl} />
              </button>
            </div>
          </div>
        </header>

        <section className="pomodoro-panel">
          <div className="pomodoro-status-row">
            <span>{phase === 'done' ? t('pomodoro.done') : phase === 'work' ? t('pomodoro.work') : t('pomodoro.break')}</span>
            <strong>{t('pomodoro.cycle', { current: String(currentCycle), total: String(cycleCount) })}</strong>
          </div>

          <div
            aria-label={t('pomodoro.remaining')}
            className="pomodoro-dial"
            style={{ '--pomodoro-progress': `${progress * 360}deg` } as CSSProperties}
          >
            <strong>{timeLabel}</strong>
            <span>{phase === 'done' ? t('pomodoro.completed') : t('pomodoro.remaining')}</span>
          </div>

          <div className="pomodoro-controls">
            <button
              disabled={phase === 'done'}
              onClick={() => {
                prepareTransitionBell()
                setIsRunning((running) => !running)
              }}
              type="button"
            >
              {isRunning ? t('pomodoro.pause') : t('pomodoro.start')}
            </button>
            <button onClick={() => resetTimer()} type="button">
              {t('pomodoro.reset')}
            </button>
            <button disabled={phase === 'done'} onClick={skipPhase} type="button">
              {t('pomodoro.skip')}
            </button>
          </div>

          {isSettingsOpen && (
            <form className="pomodoro-settings" onSubmit={handleSettingsSubmit}>
              <label>
                <span>{t('pomodoro.workMinutes')}</span>
                <input
                  max={180}
                  min={1}
                  onChange={(event) => setWorkMinutes(Number(event.target.value))}
                  type="number"
                  value={workMinutes}
                />
              </label>
              <label>
                <span>{t('pomodoro.breakMinutes')}</span>
                <input
                  max={60}
                  min={1}
                  onChange={(event) => setBreakMinutes(Number(event.target.value))}
                  type="number"
                  value={breakMinutes}
                />
              </label>
              <label>
                <span>{t('pomodoro.cycles')}</span>
                <input
                  max={24}
                  min={1}
                  onChange={(event) => setCycleCount(Number(event.target.value))}
                  type="number"
                  value={cycleCount}
                />
              </label>
              <button type="submit">{t('common.update')}</button>
            </form>
          )}
        </section>
      </div>
    </main>
  )
}

function CaseToolIconsView() {
  const [items, setItems] = useState<CaseToolIconSetting[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [matchUrl, setMatchUrl] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editingMatchUrl, setEditingMatchUrl] = useState('')
  const [editingFile, setEditingFile] = useState<File | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  useEffect(() => {
    let isMounted = true
    listCaseToolIconSettings()
      .then((nextItems) => {
        if (isMounted) setItems(nextItems)
      })
      .catch((requestError) => {
        if (isMounted) {
          setError(requestError instanceof Error ? requestError.message : t('app.requestFailed'))
        }
      })
      .finally(() => {
        if (isMounted) setIsLoading(false)
      })
    return () => {
      isMounted = false
    }
  }, [])

  function startEdit(item: CaseToolIconSetting) {
    setEditingId(item.id)
    setEditingMatchUrl(item.match_url)
    setEditingFile(null)
    setError(null)
    setNotice(null)
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (selectedFile === null || matchUrl.trim() === '') return
    setIsSubmitting(true)
    setError(null)
    setNotice(null)
    try {
      const created = await createCaseToolIconSetting({
        icon_filename: selectedFile.name,
        icon_content_type: selectedFile.type || 'image/png',
        icon_data_base64: await fileToBase64(selectedFile),
        match_url: matchUrl,
      })
      setItems((current) => [...current, created])
      setSelectedFile(null)
      setMatchUrl('')
      setNotice(t('cases.toolIcons.created'))
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('app.requestFailed'))
    } finally {
      setIsSubmitting(false)
    }
  }

  async function handleUpdate(item: CaseToolIconSetting) {
    setBusyId(item.id)
    setError(null)
    setNotice(null)
    try {
      const payload: Parameters<typeof updateCaseToolIconSetting>[1] = {
        match_url: editingMatchUrl,
      }
      if (editingFile !== null) {
        payload.icon_filename = editingFile.name
        payload.icon_content_type = editingFile.type || item.icon_content_type
        payload.icon_data_base64 = await fileToBase64(editingFile)
      }
      const updated = await updateCaseToolIconSetting(item.id, payload)
      setItems((current) => current.map((candidate) => (
        candidate.id === updated.id ? updated : candidate
      )))
      setEditingId(null)
      setEditingFile(null)
      setNotice(t('cases.toolIcons.updated'))
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('app.requestFailed'))
    } finally {
      setBusyId(null)
    }
  }

  async function handleDelete(item: CaseToolIconSetting) {
    setBusyId(item.id)
    setError(null)
    setNotice(null)
    try {
      await deleteCaseToolIconSetting(item.id)
      setItems((current) => current.filter((candidate) => candidate.id !== item.id))
      setNotice(t('cases.toolIcons.deleted'))
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('app.requestFailed'))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <main className="app-shell">
      <div className="case-shell">
        <header className="maintenance-header">
          <div>
            <p>{t('app.name')}</p>
            <h1>{t('cases.toolIcons.heading')}</h1>
          </div>
          <TopNav
            ariaLabelKey="cases.navigation"
            items={[
              { href: '/cases', labelKey: 'cases.heading' },
              { href: '/', labelKey: 'top.heading' },
            ]}
          />
        </header>
        <section className="file-icons-panel">
          {error !== null && <p className="contact-error" role="alert">{error}</p>}
          {notice !== null && <p className="contact-notice">{notice}</p>}
          <div className="file-icons-table">
            <div className="file-icons-header" role="row">
              <span>{t('cases.toolIcons.icon')}</span>
              <span>{t('cases.toolIcons.matchUrl')}</span>
              <span>{t('cases.toolIcons.actions')}</span>
            </div>
            {isLoading ? (
              <p className="mail-empty">{t('session.checking.label')}</p>
            ) : items.length === 0 ? (
              <p className="mail-empty">{t('cases.toolIcons.empty')}</p>
            ) : (
              items.map((item) => (
                <div className="file-icons-row" key={item.id} role="row">
                  <div className="file-icon-preview-cell">
                    {item.icon_url != null && item.icon_url !== '' && (
                      <img alt="" aria-hidden="true" src={item.icon_url} />
                    )}
                    {editingId === item.id && (
                      <input
                        accept="image/png,image/jpeg,image/gif,image/webp,image/svg+xml"
                        onChange={(event) => setEditingFile(event.target.files?.[0] ?? null)}
                        type="file"
                      />
                    )}
                  </div>
                  <div>
                    {editingId === item.id ? (
                      <input
                        onChange={(event) => setEditingMatchUrl(event.target.value)}
                        value={editingMatchUrl}
                      />
                    ) : (
                      <span>{item.match_url}</span>
                    )}
                  </div>
                  <div className="file-icons-actions">
                    {editingId === item.id ? (
                      <>
                        <button
                          disabled={busyId === item.id}
                          onClick={() => void handleUpdate(item)}
                          type="button"
                        >
                          {t('common.save')}
                        </button>
                        <button
                          disabled={busyId === item.id}
                          onClick={() => setEditingId(null)}
                          type="button"
                        >
                          {t('common.cancel')}
                        </button>
                      </>
                    ) : (
                      <>
                        <button onClick={() => startEdit(item)} type="button">
                          {t('cases.toolIcons.edit')}
                        </button>
                        <button
                          disabled={busyId === item.id}
                          onClick={() => void handleDelete(item)}
                          type="button"
                        >
                          {t('cases.toolIcons.delete')}
                        </button>
                      </>
                    )}
                  </div>
                </div>
              ))
            )}
            <form className="file-icons-row file-icons-create-row" onSubmit={handleCreate}>
              <div>
                <input
                  accept="image/png,image/jpeg,image/gif,image/webp,image/svg+xml"
                  onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
                  type="file"
                />
              </div>
              <div>
                <input
                  onChange={(event) => setMatchUrl(event.target.value)}
                  placeholder="github.com/example"
                  value={matchUrl}
                />
              </div>
              <div className="file-icons-actions">
                <button
                  disabled={selectedFile === null || matchUrl.trim() === '' || isSubmitting}
                  type="submit"
                >
                  {t('cases.toolIcons.register')}
                </button>
              </div>
            </form>
          </div>
        </section>
      </div>
    </main>
  )
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = typeof reader.result === 'string' ? reader.result : ''
      resolve(result.includes(',') ? result.slice(result.indexOf(',') + 1) : result)
    }
    reader.onerror = () => reject(reader.error ?? new Error(t('app.requestFailed')))
    reader.readAsDataURL(file)
  })
}

function ExternalToolsView() {
  const [tools, setTools] = useState<ExternalToolLink[]>([])
  const [tagOrder, setTagOrder] = useState<string[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [isSettingsOpen, setIsSettingsOpen] = useState(false)
  const [isFormOpen, setIsFormOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [url, setUrl] = useState('')
  const [tagText, setTagText] = useState('')
  const [note, setNote] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  useEffect(() => {
    let isMounted = true
    listExternalTools()
      .then((data) => {
        if (!isMounted) return
        setTools(data.items)
        setTagOrder(data.tag_order)
      })
      .catch((requestError) => {
        if (isMounted) {
          setError(requestError instanceof Error ? requestError.message : t('externalTools.requestFailed'))
        }
      })
      .finally(() => {
        if (isMounted) setIsLoading(false)
      })
    return () => {
      isMounted = false
    }
  }, [])

  function parseTags(value: string) {
    const tags: string[] = []
    const seen = new Set<string>()
    value
      .split(/[,\n]/)
      .map((tag) => tag.trim())
      .filter(Boolean)
      .forEach((tag) => {
        const key = tag.toLocaleLowerCase()
        if (!seen.has(key)) {
          seen.add(key)
          tags.push(tag)
        }
      })
    return tags.length === 0 ? ['General'] : tags
  }

  function clearForm(close = false) {
    setEditingId(null)
    setTitle('')
    setUrl('')
    setTagText('')
    setNote('')
    if (close) setIsFormOpen(false)
  }

  function startEdit(tool: ExternalToolLink) {
    setEditingId(tool.id)
    setTitle(tool.title)
    setUrl(tool.url)
    setTagText(tool.tags.join(', '))
    setNote(tool.note ?? '')
    setIsFormOpen(true)
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusyId(editingId ?? 'create')
    setError(null)
    setNotice(null)
    try {
      const payload = {
        title,
        url,
        tags: parseTags(tagText),
        note: note.trim() === '' ? null : note,
      }
      if (editingId === null) {
        const created = await createExternalTool(payload)
        const next = await listExternalTools()
        setTools(next.items)
        setTagOrder(next.tag_order)
        setNotice(t('externalTools.created', { title: created.title }))
      } else {
        const updated = await updateExternalTool(editingId, payload)
        const next = await listExternalTools()
        setTools(next.items)
        setTagOrder(next.tag_order)
        setNotice(t('externalTools.updated', { title: updated.title }))
      }
      clearForm(true)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('externalTools.requestFailed'))
    } finally {
      setBusyId(null)
    }
  }

  function groupedTools() {
    const groups = new Map<string, ExternalToolLink[]>()
    tagOrder.forEach((tag) => groups.set(tag, []))
    tools.forEach((tool) => {
      const tags = tool.tags.length === 0 ? ['General'] : tool.tags
      tags.forEach((tag) => {
        if (!groups.has(tag)) groups.set(tag, [])
        groups.get(tag)?.push(tool)
      })
    })
    return [...groups.entries()].filter(([, items]) => items.length > 0)
  }

  async function moveTag(tag: string, direction: -1 | 1) {
    const index = tagOrder.indexOf(tag)
    const nextIndex = index + direction
    if (index < 0 || nextIndex < 0 || nextIndex >= tagOrder.length) return
    const nextOrder = [...tagOrder]
    const [item] = nextOrder.splice(index, 1)
    nextOrder.splice(nextIndex, 0, item)
    setTagOrder(nextOrder)
    const next = await reorderExternalTools({ tag_order: nextOrder })
    setTools(next.items)
    setTagOrder(next.tag_order)
  }

  async function moveTool(toolId: string, direction: -1 | 1) {
    const orderedIds = tools
      .slice()
      .sort((left, right) => left.sort_order - right.sort_order || left.title.localeCompare(right.title))
      .map((tool) => tool.id)
    const index = orderedIds.indexOf(toolId)
    const nextIndex = index + direction
    if (index < 0 || nextIndex < 0 || nextIndex >= orderedIds.length) return
    const [item] = orderedIds.splice(index, 1)
    orderedIds.splice(nextIndex, 0, item)
    const next = await reorderExternalTools({ tool_ids: orderedIds })
    setTools(next.items)
    setTagOrder(next.tag_order)
  }

  async function handleDelete(tool: ExternalToolLink) {
    if (!window.confirm(t('externalTools.deleteConfirm', { title: tool.title }))) return
    setBusyId(`delete-${tool.id}`)
    setError(null)
    try {
      await deleteExternalTool(tool.id)
      setTools((current) => current.filter((item) => item.id !== tool.id))
      setNotice(t('externalTools.deleted', { title: tool.title }))
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('externalTools.requestFailed'))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <main className="app-shell">
      <div className="maintenance-shell external-tools-shell">
        <header className="maintenance-header">
          <div>
            <p>{t('app.name')}</p>
            <h1>{t('externalTools.heading')}</h1>
          </div>
          <TopNav
            ariaLabelKey="externalTools.navigation"
            items={[
              { href: '/', labelKey: 'top.heading' },
              { href: '/cases', labelKey: 'nav.cases' },
              { href: '/extensions', labelKey: 'nav.extensions' },
              { href: '/settings', labelKey: 'nav.settings' },
            ]}
          />
        </header>

        {error !== null && <p className="maintenance-error" role="alert">{error}</p>}
        {notice !== null && <div className="mail-feedback"><p>{notice}</p></div>}

        <section className="maintenance-panel-surface external-tools-panel">
          <div className="maintenance-panel maintenance-section external-tools-main">
            <div className="section-heading">
              <h2>{t('externalTools.heading')}</h2>
              <div className="external-tools-actions">
                <button
                  onClick={() => {
                    clearForm()
                    setIsFormOpen(true)
                  }}
                  type="button"
                >
                  {t('common.add')}
                </button>
                <AppLink href="/case-tool-icons">{t('externalTools.openIconSettings')}</AppLink>
                <button
                  aria-pressed={isSettingsOpen}
                  onClick={() => setIsSettingsOpen((current) => !current)}
                  type="button"
                >
                  {t('externalTools.settings')}
                </button>
              </div>
            </div>

            {isFormOpen && (
              <form className="external-tools-form" onSubmit={handleSubmit}>
                <label>
                  <span>{t('externalTools.title')}</span>
                  <input onChange={(event) => setTitle(event.target.value)} required value={title} />
                </label>
                <label>
                  <span>{t('externalTools.url')}</span>
                  <input onChange={(event) => setUrl(event.target.value)} required type="url" value={url} />
                </label>
                <label>
                  <span>{t('externalTools.tags')}</span>
                  <input onChange={(event) => setTagText(event.target.value)} placeholder={t('externalTools.tagsPlaceholder')} value={tagText} />
                </label>
                <label>
                  <span>{t('externalTools.note')}</span>
                  <input onChange={(event) => setNote(event.target.value)} value={note} />
                </label>
                <div className="external-tools-form-actions">
                  <button onClick={() => clearForm(true)} type="button">{t('common.cancel')}</button>
                  <button className={`button-loading-dot${busyId === (editingId ?? 'create') ? ' is-loading' : ''}`} disabled={busyId !== null} type="submit">
                    {editingId === null ? t('externalTools.register') : t('common.update')}
                  </button>
                </div>
              </form>
            )}

            {isLoading ? (
              <p>{t('common.loading')}</p>
            ) : groupedTools().length === 0 ? (
              <p className="mail-empty">{t('externalTools.empty')}</p>
            ) : (
              <div className="external-tool-groups">
                {groupedTools().map(([tag, items]) => (
                  <section className="external-tool-group" key={tag}>
                    <div className="external-tool-group-heading">
                      <h3>{tag}</h3>
                      {isSettingsOpen && (
                        <div className="external-tool-order-actions">
                          <button onClick={() => { void moveTag(tag, -1) }} type="button">{t('common.up')}</button>
                          <button onClick={() => { void moveTag(tag, 1) }} type="button">{t('common.down')}</button>
                        </div>
                      )}
                    </div>
                    <div className="external-tool-icon-grid">
                      {items.map((tool) => (
                        <article className="external-tool-card" key={`${tag}-${tool.id}`}>
                          <a href={tool.url} rel="noreferrer" target="_blank">
                            <span className="external-tool-icon">
                              {tool.icon_url === null ? tool.icon_label : <img alt="" src={tool.icon_url} />}
                            </span>
                            <strong>{tool.title}</strong>
                          </a>
                          {tool.note !== null && <p>{tool.note}</p>}
                          {isSettingsOpen && (
                            <div className="external-tool-card-actions">
                              <button onClick={() => startEdit(tool)} type="button">{t('common.edit')}</button>
                              <button onClick={() => { void moveTool(tool.id, -1) }} type="button">{t('common.left')}</button>
                              <button onClick={() => { void moveTool(tool.id, 1) }} type="button">{t('common.right')}</button>
                              <button disabled={busyId === `delete-${tool.id}`} onClick={() => { void handleDelete(tool) }} type="button">{t('common.delete')}</button>
                            </div>
                          )}
                        </article>
                      ))}
                    </div>
                  </section>
                ))}
              </div>
            )}
          </div>
        </section>
      </div>
    </main>
  )
}

function FileIconsView() {
  const [items, setItems] = useState<FileIconSetting[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [extensions, setExtensions] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editingExtensions, setEditingExtensions] = useState('')
  const [editingFile, setEditingFile] = useState<File | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  useEffect(() => {
    let isMounted = true
    listFileIconSettings()
      .then((nextItems) => {
        if (isMounted) setItems(nextItems)
      })
      .catch((requestError) => {
        if (isMounted) {
          setError(requestError instanceof Error ? requestError.message : t('app.requestFailed'))
        }
      })
      .finally(() => {
        if (isMounted) setIsLoading(false)
      })
    return () => {
      isMounted = false
    }
  }, [])

  function startEdit(item: FileIconSetting) {
    setEditingId(item.id)
    setEditingExtensions(item.extensions.join(' '))
    setEditingFile(null)
    setError(null)
    setNotice(null)
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (selectedFile === null || extensions.trim() === '') return
    setIsSubmitting(true)
    setError(null)
    setNotice(null)
    try {
      const created = await createFileIconSetting({
        icon_filename: selectedFile.name,
        icon_content_type: selectedFile.type || 'image/png',
        icon_data_base64: await fileToBase64(selectedFile),
        extensions: extensions.split(/[\s,]+/).filter(Boolean),
      })
      setItems((current) => [...current, created])
      setSelectedFile(null)
      setExtensions('')
      setNotice(t('storage.fileIcons.created'))
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('app.requestFailed'))
    } finally {
      setIsSubmitting(false)
    }
  }

  async function handleUpdate(item: FileIconSetting) {
    setBusyId(item.id)
    setError(null)
    setNotice(null)
    try {
      const payload: Parameters<typeof updateFileIconSetting>[1] = {
        extensions: editingExtensions.split(/[\s,]+/).filter(Boolean),
      }
      if (editingFile !== null) {
        payload.icon_filename = editingFile.name
        payload.icon_content_type = editingFile.type || item.icon_content_type
        payload.icon_data_base64 = await fileToBase64(editingFile)
      }
      const updated = await updateFileIconSetting(item.id, payload)
      setItems((current) => current.map((candidate) => (
        candidate.id === updated.id ? updated : candidate
      )))
      setEditingId(null)
      setEditingFile(null)
      setNotice(t('storage.fileIcons.updated'))
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('app.requestFailed'))
    } finally {
      setBusyId(null)
    }
  }

  async function handleDelete(item: FileIconSetting) {
    setBusyId(item.id)
    setError(null)
    setNotice(null)
    try {
      await deleteFileIconSetting(item.id)
      setItems((current) => current.filter((candidate) => candidate.id !== item.id))
      setNotice(t('storage.fileIcons.deleted'))
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('app.requestFailed'))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <main className="app-shell">
      <div className="case-shell">
        <header className="maintenance-header">
          <div>
            <p>{t('app.name')}</p>
            <h1>{t('storage.fileIcons.heading')}</h1>
          </div>
          <TopNav
            ariaLabelKey="storage.navigation"
            items={[
              { href: '/files', labelKey: 'nav.files' },
              { href: '/cases', labelKey: 'cases.heading' },
              { href: '/', labelKey: 'top.heading' },
            ]}
          />
          </header>
          <section className="file-icons-panel">
            {error !== null && <p className="contact-error" role="alert">{error}</p>}
            {notice !== null && <p className="contact-notice">{notice}</p>}
            <div className="file-icons-table">
              <div className="file-icons-header" role="row">
                <span>{t('storage.fileIcons.icon')}</span>
                <span>{t('storage.fileIcons.extensions')}</span>
                <span>{t('storage.fileIcons.actions')}</span>
              </div>
              {isLoading ? (
                <p className="mail-empty">{t('session.checking.label')}</p>
              ) : items.length === 0 ? (
                <p className="mail-empty">{t('storage.fileIcons.empty')}</p>
              ) : (
                items.map((item) => (
                  <div className="file-icons-row" key={item.id} role="row">
                    <div className="file-icon-preview-cell">
                      {item.icon_url != null && item.icon_url !== '' && (
                        <img alt="" aria-hidden="true" src={item.icon_url} />
                      )}
                      {editingId === item.id && (
                        <input
                          accept="image/png,image/jpeg,image/gif,image/webp,image/svg+xml"
                          onChange={(event) => setEditingFile(event.target.files?.[0] ?? null)}
                          type="file"
                        />
                      )}
                    </div>
                    <div>
                      {editingId === item.id ? (
                        <input
                          onChange={(event) => setEditingExtensions(event.target.value)}
                          value={editingExtensions}
                        />
                      ) : (
                        <span>{item.extensions.join(', ')}</span>
                      )}
                    </div>
                    <div className="file-icons-actions">
                      {editingId === item.id ? (
                        <>
                          <button
                            disabled={busyId === item.id}
                            onClick={() => void handleUpdate(item)}
                            type="button"
                          >
                            {t('common.save')}
                          </button>
                          <button
                            disabled={busyId === item.id}
                            onClick={() => setEditingId(null)}
                            type="button"
                          >
                            {t('common.cancel')}
                          </button>
                        </>
                      ) : (
                        <>
                          <button onClick={() => startEdit(item)} type="button">
                            {t('storage.fileIcons.edit')}
                          </button>
                          <button
                            disabled={busyId === item.id}
                            onClick={() => void handleDelete(item)}
                            type="button"
                          >
                            {t('storage.fileIcons.delete')}
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                ))
              )}
              <form className="file-icons-row file-icons-create-row" onSubmit={handleCreate}>
                <div>
                  <input
                    accept="image/png,image/jpeg,image/gif,image/webp,image/svg+xml"
                    onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
                    type="file"
                  />
                </div>
                <div>
                  <input
                    onChange={(event) => setExtensions(event.target.value)}
                    placeholder=".pdf .docx txt"
                    value={extensions}
                  />
                </div>
                <div className="file-icons-actions">
                  <button
                    disabled={selectedFile === null || extensions.trim() === '' || isSubmitting}
                    type="submit"
                  >
                    {t('storage.fileIcons.register')}
                  </button>
                </div>
              </form>
            </div>
          </section>
        </div>
      </main>
  )
}

function shouldSuppressPendingContactNotice(path: string) {
  return path === '/' || path === '/contacts/pending'
}

function PendingContactRedirectNotice({
  notice,
  secondsLeft,
  onDismiss,
  onGoNow,
}: {
  notice: PendingContactNotice
  secondsLeft: number
  onDismiss: () => void
  onGoNow: () => void
}) {
  return (
    <aside
      aria-live="assertive"
      className="pending-contact-redirect-notice"
      role="alertdialog"
    >
      <div>
        <h2>{t('pendingContactRedirect.heading')}</h2>
        <p>{t('pendingContactRedirect.body')}</p>
        <strong>
          {t('mail.blocked.count', { count: String(notice.count) })} /{' '}
          {t('pendingContactRedirect.countdown', { seconds: secondsLeft })}
        </strong>
      </div>
      <div className="pending-contact-redirect-actions">
        <button onClick={onDismiss} type="button">
          {t('pendingContactRedirect.stay')}
        </button>
        <button onClick={onGoNow} type="button">
          {t('pendingContactRedirect.goNow')}
        </button>
      </div>
    </aside>
  )
}

function App() {
  const [password, setPassword] = useState('')
  const [session, setSession] = useState<SessionData | null>(null)
  const [sessionExpiresAt, setSessionExpiresAt] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isLocked, setIsLocked] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isSessionChecked, setIsSessionChecked] = useState(false)
  const [path, setPath] = useState(window.location.pathname)
  const [routePreload, setRoutePreload] = useState<RoutePreload | null>(null)
  const [navigationError, setNavigationError] = useState<string | null>(null)
  const [pendingContactNotice, setPendingContactNotice] =
    useState<PendingContactNotice | null>(null)
  const [pendingContactSecondsLeft, setPendingContactSecondsLeft] = useState(30)
  const routeTransitionId = useRef(0)

  function transitionToPreparedRoute(
    nextPath: string,
    historyMode: 'none' | 'push' | 'replace',
  ) {
    routeTransitionId.current += 1
    const currentTransitionId = routeTransitionId.current
    setNavigationError(null)

    preloadRoute(nextPath)
      .then((preload) => {
        if (currentTransitionId !== routeTransitionId.current) {
          return
        }
        if (historyMode === 'replace') {
          window.history.replaceState({}, '', nextPath)
        } else if (historyMode === 'push') {
          window.history.pushState({}, '', nextPath)
        }
        setRoutePreload(preload)
        setPath(new URL(nextPath, window.location.origin).pathname)
      })
      .catch((requestError) => {
        if (currentTransitionId === routeTransitionId.current) {
          setNavigationError(
            requestError instanceof Error ? requestError.message : t('app.requestFailed'),
          )
        }
      })
  }

  useEffect(() => {
    let isMounted = true

    readSession()
      .then((activeSession) => {
        if (!isMounted) {
          return
        }
        setSession(activeSession)
        setSessionExpiresAt(activeSession.session_expires_at)
      })
      .catch(() => {
        // Showing login is the expected fallback when no session exists.
      })
      .finally(() => {
        if (isMounted) {
          setIsSessionChecked(true)
        }
      })

    return () => {
      isMounted = false
    }
  }, [])

  useEffect(() => {
    function handleNavigation() {
      transitionToPreparedRoute(currentBrowserPath(), 'none')
    }

    window.addEventListener('popstate', handleNavigation)
    return () => {
      window.removeEventListener('popstate', handleNavigation)
    }
  }, [])

  useEffect(() => {
    function handleGlobalShortcut(event: KeyboardEvent) {
      if (
        event.defaultPrevented ||
        event.key !== 'Escape' ||
        event.altKey ||
        event.ctrlKey ||
        event.metaKey ||
        event.shiftKey ||
        isEditableShortcutTarget(event.target)
      ) {
        return
      }

      event.preventDefault()
      const returnTo = returnToFromLocation()
      if (returnTo !== null) {
        transitionToPreparedRoute(returnTo, 'push')
        return
      }
      const naturalReturnTarget = naturalReturnTargetFromLocation()
      if (naturalReturnTarget !== null) {
        transitionToPreparedRoute(naturalReturnTarget, 'push')
        return
      }
      window.history.back()
    }

    window.addEventListener('keydown', handleGlobalShortcut)
    return () => {
      window.removeEventListener('keydown', handleGlobalShortcut)
    }
  }, [])

  useEffect(() => {
    function syncDocumentTitle() {
      const heading = document.querySelector('h1')?.textContent?.trim()
      document.title = heading === undefined || heading === '' ? t('app.name') : heading
    }

    syncDocumentTitle()
    const observer = new MutationObserver(syncDocumentTitle)
    observer.observe(document.body, {
      childList: true,
      characterData: true,
      subtree: true,
    })
    return () => {
      observer.disconnect()
    }
  }, [path, session, isSessionChecked])

  useEffect(() => {
    function handleNavigationRequest(event: Event) {
      const navigationEvent = event as NavigationRequestEvent
      const { path: nextPath, replace } = navigationEvent.detail
      navigationEvent.preventDefault()
      transitionToPreparedRoute(nextPath, replace ? 'replace' : 'push')
    }

    window.addEventListener('caseclosed:navigate', handleNavigationRequest)
    return () => {
      window.removeEventListener('caseclosed:navigate', handleNavigationRequest)
    }
  }, [])

  useEffect(() => {
    function handlePendingContactRedirect(event: Event) {
      if (shouldSuppressPendingContactNotice(window.location.pathname)) {
        return
      }
      const pendingEvent = event as PendingContactRedirectEvent
      if (pendingEvent.detail.count <= 0) {
        return
      }
      setPendingContactNotice({
        count: pendingEvent.detail.count,
        deadlineAt: Date.now() + 30000,
      })
      setPendingContactSecondsLeft(30)
    }

    window.addEventListener(pendingContactRedirectEventName, handlePendingContactRedirect)
    return () => {
      window.removeEventListener(pendingContactRedirectEventName, handlePendingContactRedirect)
    }
  }, [])

  useEffect(() => {
    if (pendingContactNotice === null) {
      return undefined
    }
    const timerId = window.setInterval(() => {
      const nextSecondsLeft = Math.max(
        0,
        Math.ceil((pendingContactNotice.deadlineAt - Date.now()) / 1000),
      )
      setPendingContactSecondsLeft(nextSecondsLeft)
      if (nextSecondsLeft === 0) {
        setPendingContactNotice(null)
        transitionToPreparedRoute('/', 'replace')
      }
    }, 250)

    return () => {
      window.clearInterval(timerId)
    }
  }, [pendingContactNotice])

  const pendingContactNoticeElement =
    pendingContactNotice === null ? null : (
      <PendingContactRedirectNotice
        notice={pendingContactNotice}
        onDismiss={() => setPendingContactNotice(null)}
        onGoNow={() => {
          setPendingContactNotice(null)
          transitionToPreparedRoute('/', 'replace')
        }}
        secondsLeft={pendingContactSecondsLeft}
      />
    )

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setIsSubmitting(true)

    try {
      const loginSession = await login(password)
      setSessionExpiresAt(loginSession.session_expires_at)
      setSession({
        authenticated: true,
        session_expires_at: loginSession.session_expires_at,
        client_certificate_id: null,
        device_name: loginSession.device_name,
        ip_address: loginSession.ip_address,
      })
      setPassword('')
    } catch (loginError) {
      if (loginError instanceof AuthApiError) {
        setError(loginError.message)
        setIsLocked(loginError.code === 'LOGIN_LOCKED')
      } else {
        setError(t('auth.requestFailed'))
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  if (session !== null) {
    if (path === '/maintenance') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <MaintenanceView
            initialData={
              routePreload?.path === '/maintenance'
                ? routePreload.maintenance
                : undefined
            }
          />
        </>
      )
    }
    if (path === '/logs') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <LogView />
        </>
      )
    }
    if (path === '/follow-ups') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <FollowUpView />
        </>
      )
    }
    if (path === '/settings') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <SettingsView />
        </>
      )
    }
    if (path === '/manual') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <ManualView />
        </>
      )
    }
    if (path === '/external-tools') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <ExternalToolsView />
        </>
      )
    }
    if (path === '/extensions') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <ExtensionsView />
        </>
      )
    }
    if (path === '/extensions/help') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <ExtensionsHelpView />
        </>
      )
    }
    if (path === '/extensions/launch') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <ExtensionLaunchView />
        </>
      )
    }
    if (path === '/mail' || path === '/mail/action-needed') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <PreloadedMailRoute
            preload={routePreload ?? undefined}
            viewMode={path === '/mail/action-needed' ? 'action-needed' : 'normal'}
          />
        </>
      )
    }
    if (path === '/pomodoro') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <PomodoroView />
        </>
      )
    }
    if (path === '/today' || path === '/tomorrow') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <TodayView dayOffset={path === '/tomorrow' ? 1 : 0} />
        </>
      )
    }
    if (path === '/mail/compose') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <ComposeMailView />
        </>
      )
    }
    if (path.startsWith('/mail/')) {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <MailThreadView messageId={decodeURIComponent(path.slice('/mail/'.length))} />
        </>
      )
    }
    if (path === '/cases') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <CaseView />
        </>
      )
    }
    if (path === '/tasks') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <TaskView />
        </>
      )
    }
    if (path === '/calendar/new') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <CalendarNewEventView />
        </>
      )
    }
    if (path.startsWith('/calendar/events/') && path.endsWith('/edit')) {
      const eventId = path.slice('/calendar/events/'.length, -'/edit'.length)
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <CalendarEventDetailView eventId={decodeURIComponent(eventId)} mode="edit" />
        </>
      )
    }
    if (path.startsWith('/calendar/events/') && path.endsWith('/attach-mail')) {
      const eventId = path.slice('/calendar/events/'.length, -'/attach-mail'.length)
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <CalendarEventDetailView eventId={decodeURIComponent(eventId)} mode="attach-mail" />
        </>
      )
    }
    if (path.startsWith('/calendar/events/')) {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <CalendarEventDetailView eventId={decodeURIComponent(path.slice('/calendar/events/'.length))} />
        </>
      )
    }
    if (path === '/calendar') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <CalendarView />
        </>
      )
    }
    if (path === '/academic-calendar') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <AcademicCalendarView />
        </>
      )
    }
    if (path === '/tasks/new') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <TaskNewView />
        </>
      )
    }
    if (path.startsWith('/tasks/')) {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <TaskDetailView taskId={decodeURIComponent(path.slice('/tasks/'.length))} />
        </>
      )
    }
    if (path === '/cases/new') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <CaseView mode="new" />
        </>
      )
    }
    if (path.startsWith('/cases/') && path.endsWith('/mails')) {
      const caseId = path.slice('/cases/'.length, -'/mails'.length)
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <CaseView caseId={decodeURIComponent(caseId)} mode="mail-list" />
        </>
      )
    }
    if (path.startsWith('/cases/') && path.endsWith('/task-batch-generate')) {
      const caseId = path.slice('/cases/'.length, -'/task-batch-generate'.length)
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <CaseTaskBatchGenerateView caseId={decodeURIComponent(caseId)} />
        </>
      )
    }
    if (path === '/case-tool-icons') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <CaseToolIconsView />
        </>
      )
    }
    if (path === '/file-icons') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <FileIconsView />
        </>
      )
    }
    if (path === '/profile') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <ProfileView />
        </>
      )
    }
    if (path.startsWith('/cases/')) {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <CaseView caseId={decodeURIComponent(path.slice('/cases/'.length))} mode="detail" />
        </>
      )
    }
    if (path === '/contacts') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <ContactsView
            initialData={
              routePreload?.path === '/contacts'
                ? routePreload.contacts
                : undefined
            }
            mode="list"
          />
        </>
      )
    }
    if (path === '/contacts/pending') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <ContactsView
            initialData={
              routePreload?.path === '/contacts/pending'
                ? routePreload.contacts
                : undefined
            }
            mode="pending"
          />
        </>
      )
    }
    if (path === '/files') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <StorageView />
        </>
      )
    }
    if (path.startsWith('/files/')) {
      const storageObjectId = decodeURIComponent(path.slice('/files/'.length))
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <StorageView storageObjectId={storageObjectId} />
        </>
      )
    }

    return (
      <>
        {pendingContactNoticeElement}
        {navigationError !== null && <p className="route-error">{navigationError}</p>}
        <TopView
          initialPendingCount={
            routePreload?.path === '/' ? routePreload.pendingCount : undefined
          }
          session={session}
          sessionExpiresAt={sessionExpiresAt}
        />
      </>
    )
  }

  if (!isSessionChecked) {
    return <main aria-label={t('session.checking.label')} className="app-shell" />
  }

  return (
    <main className="app-shell">
      <div className="login-layout">
        <section className="login-panel">
          <header className="login-heading">
            <h1>{t('app.name')}</h1>
          </header>

          <form className="login-form" onSubmit={handleSubmit}>
            <label className="password-field">
              <span>{t('login.password.label')}</span>
              <input
                autoComplete="current-password"
                name="password"
                onChange={(event) => setPassword(event.target.value)}
                type="password"
                value={password}
              />
            </label>

            {error !== null && <p role="alert">{error}</p>}
            {isLocked && <p className="lock-status">{t('login.locked')}</p>}

            <button
              className={`button-loading-dot${isSubmitting ? ' is-loading' : ''}`}
              disabled={isSubmitting}
              type="submit"
            >
              {t('login.submit')}
            </button>
          </form>
        </section>

        <figure className="login-illustration">
          <img alt={t('login.mascot.alt')} src={loginDoorTanuki} />
        </figure>
      </div>
    </main>
  )
}

export default App

