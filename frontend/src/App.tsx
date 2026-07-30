import { useEffect, useRef, useState } from 'react'
import type { CSSProperties, FormEvent } from 'react'
import {
  AuthApiError,
  login,
  logout,
  readSession,
  resetPasswordByEmail,
} from './authApi'
import type { SessionData } from './authApi'
import AcademicCalendarView from './AcademicCalendarView'
import loginDoorTanuki from './assets/login-door-tanuki.png'
import settingsGearIconUrl from './assets/settings-gear.svg'
import pomodoroBellUrl from './assets/pomodoro-school-bell.mp3'
import topBookshelfTanukiIconUrl from './assets/top-bookshelf-tanuki-icon-v2.webp'
import topCalendarTanukiIconUrl from './assets/top-calendar-tanuki-icon-v2.webp'
import topCasesTanukiIconUrl from './assets/top-cases-tanuki-icon-v2.webp'
import topContactsTanukiIconUrl from './assets/top-contacts-tanuki-icon-v2.webp'
import topExtensionsTanukiIconUrl from './assets/top-extensions-tanuki-icon-v2.webp'
import topExternalToolsTanukiIconUrl from './assets/top-external-tools-tanuki-icon-v2.webp'
import topFilesTanukiIconUrl from './assets/top-files-tanuki-icon-v2.webp'
import topMailTanukiIconUrl from './assets/top-mail-tanuki-icon.png'
import topPapersTanukiIconUrl from './assets/top-papers-tanuki-icon-v2.webp'
import topTasksTanukiIconUrl from './assets/top-tasks-tanuki-icon-v2.webp'
import topPomodoroTanukiIconUrl from './assets/top-pomodoro-tanuki-icon-v3.webp'
import CalendarView from './CalendarView'
import BookshelfView from './BookshelfView'
import BookshelfReaderView from './BookshelfReaderView'
import BookshelfTagHierarchyView from './BookshelfTagHierarchyView'
import CalendarConflictView from './CalendarConflictView'
import CalendarEventDetailView from './CalendarEventDetailView'
import CalendarNewEventView from './CalendarNewEventView'
import CaseTaskBatchGenerateView from './CaseTaskBatchGenerateView'
import CaseAutoAssignRulesView from './CaseAutoAssignRulesView'
import CaseView from './CaseView'
import ComposeMailView from './ComposeMailView'
import ContactsView from './ContactsView'
import ContactAutoTagRulesView from './ContactAutoTagRulesView'
import type { ContactsInitialData } from './ContactsView'
import ExtensionLaunchView from './ExtensionLaunchView'
import ExtensionsHelpView from './ExtensionsHelpView'
import ExtensionsView from './ExtensionsView'
import FollowUpView from './FollowUpView'
import LogView from './LogView'
import LowMailReviewView, { LowMailReviewDetailView } from './LowMailReviewView'
import ManualView from './ManualView'
import MailView from './MailView'
import type { MailInitialData } from './MailView'
import type { MailTab } from './MailView'
import MailThreadView from './MailThreadView'
import MobileTopView from './MobileTopView'
import MobileCalendarDayView from './MobileCalendarDayView'
import MobileMailDayView from './MobileMailDayView'
import MobileMailThreadView from './MobileMailThreadView'
import MobileSettingsView from './MobileSettingsView'
import { MobileTaskDetailView, MobileTaskListView } from './MobileTaskView'
import MaintenanceView from './MaintenanceView'
import PaperShelfView from './PaperShelfView'
import PaperDetailView from './PaperDetailView'
import PaperJournalIconsView from './PaperJournalIconsView'
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
import { imageUploadAccept, imageUploadContentType } from './imageUpload'
import { installZoomLayoutGuard } from './zoomLayout'
import { listTasks } from './phase8Api'
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
import { getMailDayStats, listMailDates, listMailPage } from './phase4Api'
import {
  pendingContactRedirectEventName,
  type PendingContactRedirectEvent,
} from './pendingContactRedirect'
import {
  pausePomodoro,
  readPomodoroState,
  resetPomodoro,
  skipPomodoro,
  startPomodoro,
  updatePomodoroSettings,
} from './pomodoroApi'
import type { PomodoroState } from './pomodoroApi'
import './App.css'

type LinkItem = {
  labelKey: MessageKey
  href: string
  target?: '_blank'
  rel?: string
  iconUrl?: string
}

type LinkRenderItem = LinkItem & {
  label?: string
}

type TopAttentionState = {
  mail: boolean
  tasks: boolean
  maintenance: boolean
}

const emptyTopAttentionState: TopAttentionState = {
  mail: false,
  tasks: false,
  maintenance: false,
}

type PageSlot = LinkItem | { blank: true; key: string }

const pomodoroSettingsStorageKey = 'caseclosed.pomodoroSettings'
const viewModeStorageKey = 'caseclosed.viewMode'

type ViewModePreference = 'desktop' | 'mobile'

function requestedViewModeFromLocation(): ViewModePreference | null {
  const value = new URLSearchParams(window.location.search).get('view')
  return value === 'desktop' || value === 'mobile' ? value : null
}

function rememberedViewMode(): ViewModePreference | null {
  try {
    const value = window.localStorage.getItem(viewModeStorageKey)
    return value === 'desktop' || value === 'mobile' ? value : null
  } catch {
    return null
  }
}

function rememberViewMode(value: ViewModePreference) {
  try {
    window.localStorage.setItem(viewModeStorageKey, value)
  } catch {
    // localStorage can be unavailable in private or restricted contexts.
  }
}

function isMobileTopViewport() {
  return window.matchMedia('(max-width: 720px), (pointer: coarse) and (max-width: 900px)').matches
}

function shouldOpenMobileTop(requested: ViewModePreference | null) {
  if (requested === 'desktop') return false
  if (requested === 'mobile') return true
  const remembered = rememberedViewMode()
  if (remembered === 'desktop') return false
  if (remembered === 'mobile') return true
  return isMobileTopViewport()
}

const pageLinks: LinkItem[] = [
  { labelKey: 'nav.mail', href: '/mail', iconUrl: topMailTanukiIconUrl },
  { labelKey: 'nav.cases', href: '/cases', iconUrl: topCasesTanukiIconUrl },
  { labelKey: 'nav.tasks', href: '/tasks', iconUrl: topTasksTanukiIconUrl },
  { labelKey: 'nav.calendar', href: '/calendar', iconUrl: topCalendarTanukiIconUrl },
  { labelKey: 'nav.contacts', href: '/contacts', iconUrl: topContactsTanukiIconUrl },
  { labelKey: 'nav.files', href: '/files', iconUrl: topFilesTanukiIconUrl },
  { labelKey: 'nav.bookshelf', href: '/bookshelf', iconUrl: topBookshelfTanukiIconUrl },
  { labelKey: 'nav.papers', href: '/papers', iconUrl: topPapersTanukiIconUrl },
  { labelKey: 'nav.pomodoro', href: '/pomodoro', target: '_blank', rel: 'noopener noreferrer', iconUrl: topPomodoroTanukiIconUrl },
  { labelKey: 'nav.externalTools', href: '/external-tools', iconUrl: topExternalToolsTanukiIconUrl },
  { labelKey: 'nav.extensions', href: '/extensions', iconUrl: topExtensionsTanukiIconUrl },
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
  { labelKey: 'nav.logout', href: '/logout' },
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

function topAttentionTitle(href: string) {
  if (href === '/mail') return t('top.attention.mail')
  if (href === '/tasks') return t('top.attention.tasks')
  if (href === '/maintenance') return t('top.attention.maintenance')
  return null
}

function hasTopAttention(attentionState: TopAttentionState, href: string) {
  if (href === '/mail') return attentionState.mail
  if (href === '/tasks') return attentionState.tasks
  if (href === '/maintenance') return attentionState.maintenance
  return false
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
  const searchQuery = routeUrl.searchParams.get('q')?.trim() ?? ''
  const contactId = routeUrl.searchParams.get('contact_id')?.trim() ?? ''
  const listSort = routeUrl.searchParams.get('sort') === 'newest' ? 'newest' : 'importance'
  const requestedDate = requestedDateFromSearchParams(routeUrl.searchParams)
  const today = jstDateToday()
  const provisionalDate = requestedDate ?? today
  const isSearchLike = viewMode === 'action-needed' || searchQuery !== '' || contactId !== ''

  function loadPage(date: string) {
    if (viewMode === 'action-needed') {
      return listMailPage({
        tab: 'all',
        needs_action: true,
        sort: listSort,
        limit: 25,
      })
    }
    if (searchQuery !== '' || contactId !== '') {
      return listMailPage({
        tab: 'all',
        q: searchQuery || undefined,
        contact_id: contactId || undefined,
        sort: listSort,
        limit: 25,
      })
    }
    return listMailPage({
      tab: activeTab,
      date_from: startOfDate(date),
      date_to: endOfDate(date),
      sort: listSort,
      limit: 25,
    })
  }

  let [mailDates, page, mailDayStats] = await Promise.all([
    viewMode === 'action-needed' || contactId !== ''
      ? Promise.resolve([])
      : listMailDates(activeTab),
    loadPage(provisionalDate),
    isSearchLike ? Promise.resolve(null) : getMailDayStats(provisionalDate),
  ])
  const selectedDate =
    requestedDate ??
    (mailDates.some((item) => item.date === today)
      ? today
      : mailDates.at(-1)?.date ?? today)
  if (!isSearchLike && selectedDate !== provisionalDate) {
    ;[page, mailDayStats] = await Promise.all([
      loadPage(selectedDate),
      getMailDayStats(selectedDate),
    ])
  }

  return {
    mails: page.items,
    mailDates,
    mailDayStats,
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
  const [attentionState, setAttentionState] = useState<TopAttentionState>(
    emptyTopAttentionState,
  )

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

  useEffect(() => {
    let isMounted = true

    Promise.allSettled([
      listMailPage({ tab: 'all', needs_action: true, limit: 1 }),
      listTasks({ status: 'open', due: 'today', limit: 1 }),
      listTasks({ status: 'open', due: 'overdue', limit: 1 }),
      readMaintenanceStatus(),
    ]).then(([mailResult, todayTasksResult, overdueTasksResult, maintenanceResult]) => {
      if (!isMounted) {
        return
      }
      setAttentionState({
        mail: mailResult.status === 'fulfilled' && mailResult.value.items.length > 0,
        tasks:
          (todayTasksResult.status === 'fulfilled' && todayTasksResult.value.length > 0) ||
          (overdueTasksResult.status === 'fulfilled' && overdueTasksResult.value.length > 0),
        maintenance:
          maintenanceResult.status === 'fulfilled' &&
          ((maintenanceResult.value.action_required_jobs ?? 0) > 0 ||
            maintenanceResult.value.external_unknown_count > 0),
      })
    })

    return () => {
      isMounted = false
    }
  }, [])

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

  async function handleLogout() {
    setPendingError(null)
    try {
      await logout()
      window.location.assign('/')
    } catch (requestError) {
      setPendingError(
        requestError instanceof Error ? requestError.message : t('auth.requestFailed'),
      )
    }
  }

  function linkContent(link: LinkRenderItem) {
    const attentionTitle = topAttentionTitle(link.href)
    const showAttention = attentionTitle !== null && hasTopAttention(attentionState, link.href)

    return (
      <>
        {link.iconUrl !== undefined ? (
          <span className="hub-link-content-with-icon">
            <img alt="" aria-hidden="true" src={link.iconUrl} />
            <span>{linkLabel(link)}</span>
          </span>
        ) : (
          linkLabel(link)
        )}
        {showAttention && (
          <small
            aria-label={attentionTitle}
            className="top-attention-badge"
            title={attentionTitle}
          >
            {t('top.attention.mark')}
          </small>
        )}
      </>
    )
  }

  function lockedLink(link: LinkRenderItem, className?: string) {
    if (
      !isLockedByPending ||
      link.href === '/maintenance' ||
      link.href === '/logout'
    ) {
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
            : link.href === '/logout'
              ? (event) => {
                  event.preventDefault()
                  void handleLogout()
                }
              : undefined}
          rel={link.rel}
          target={link.target}
        >
          {linkContent(link)}
        </AppLink>
      )
    }
    return (
      <span aria-disabled="true" className={className} key={link.href}>
        {linkContent(link)}
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

type RememberedPomodoroSettings = {
  work_minutes: number
  break_minutes: number
  cycle_count: number
}

function readRememberedPomodoroSettings(): RememberedPomodoroSettings | null {
  try {
    const value = window.localStorage.getItem(pomodoroSettingsStorageKey)
    if (value === null) return null
    const parsed = JSON.parse(value) as Partial<RememberedPomodoroSettings>
    const workMinutes = Number(parsed.work_minutes)
    const breakMinutes = Number(parsed.break_minutes)
    const cycleCount = Number(parsed.cycle_count)
    if (!Number.isFinite(workMinutes) || !Number.isFinite(breakMinutes) || !Number.isFinite(cycleCount)) {
      return null
    }
    return {
      work_minutes: Math.min(180, Math.max(1, Math.round(workMinutes))),
      break_minutes: Math.min(60, Math.max(1, Math.round(breakMinutes))),
      cycle_count: Math.min(24, Math.max(1, Math.round(cycleCount))),
    }
  } catch {
    return null
  }
}

function writeRememberedPomodoroSettings(settings: RememberedPomodoroSettings) {
  window.localStorage.setItem(pomodoroSettingsStorageKey, JSON.stringify(settings))
}

function shouldApplyRememberedPomodoroSettings(state: PomodoroState, settings: RememberedPomodoroSettings) {
  if (state.is_running || state.phase !== 'work' || state.current_cycle !== 1) return false
  if (state.remaining_seconds !== state.work_minutes * 60) return false
  return (
    state.work_minutes !== settings.work_minutes ||
    state.break_minutes !== settings.break_minutes ||
    state.cycle_count !== settings.cycle_count
  )
}

function initialPomodoroState(): PomodoroState {
  return {
    work_minutes: 25,
    break_minutes: 5,
    cycle_count: 4,
    phase: 'work',
    current_cycle: 1,
    is_running: false,
    remaining_seconds: 25 * 60,
    total_seconds: 25 * 60,
    phase_ends_at_epoch_ms: null,
    updated_at_epoch_ms: Date.now(),
    version: 1,
  }
}

type PomodoroWorkerEvent = { type: 'tick' } | { type: 'sync' }
type PomodoroSsePayload = {
  state: PomodoroState
}


function displayRemainingSeconds(state: PomodoroState) {
  if (!state.is_running || state.phase === 'done' || state.phase_ends_at_epoch_ms === null) {
    return state.remaining_seconds
  }
  return Math.max(0, Math.ceil((state.phase_ends_at_epoch_ms - Date.now()) / 1000))
}

function PomodoroView() {
  const [state, setState] = useState<PomodoroState>(initialPomodoroState)
  const [workMinutes, setWorkMinutes] = useState(25)
  const [breakMinutes, setBreakMinutes] = useState(5)
  const [cycleCount, setCycleCount] = useState(4)
  const [displayTick, setDisplayTick] = useState(0)
  const [isSettingsOpen, setIsSettingsOpen] = useState(false)
  const isSettingsOpenRef = useRef(false)
  const bellAudioRef = useRef<HTMLAudioElement | null>(null)
  const lastTransitionRef = useRef<{ phase: PomodoroState['phase']; cycle: number; version: number } | null>(null)

  const remainingSeconds = displayRemainingSeconds(state)
  const totalSeconds = state.total_seconds
  const progress =
    state.phase === 'done' || totalSeconds <= 0
      ? 1
      : Math.min(1, Math.max(0, (totalSeconds - remainingSeconds) / totalSeconds))
  const minutes = Math.floor(remainingSeconds / 60)
  const seconds = remainingSeconds % 60
  const timeLabel = `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`

  function applyState(nextState: PomodoroState, playBell = true) {
    const previous = lastTransitionRef.current
    const changedPhase = previous !== null && (
      previous.phase !== nextState.phase || previous.cycle !== nextState.current_cycle
    )
    lastTransitionRef.current = {
      phase: nextState.phase,
      cycle: nextState.current_cycle,
      version: nextState.version,
    }
    setState(nextState)
    if (!isSettingsOpenRef.current) {
      setWorkMinutes(nextState.work_minutes)
      setBreakMinutes(nextState.break_minutes)
      setCycleCount(nextState.cycle_count)
    }
    if (playBell && changedPhase) {
      playTransitionBell()
    }
  }

  async function refreshState(playBell = true) {
    const nextState = await readPomodoroState()
    applyState(nextState, playBell)
  }

  useEffect(() => {
    isSettingsOpenRef.current = isSettingsOpen
    if (isSettingsOpen) {
      setWorkMinutes(state.work_minutes)
      setBreakMinutes(state.break_minutes)
      setCycleCount(state.cycle_count)
    }
  }, [isSettingsOpen, state.break_minutes, state.cycle_count, state.work_minutes])

  useEffect(() => {
    let isActive = true
    void readPomodoroState()
      .then(async (nextState) => {
        if (!isActive) return
        const rememberedSettings = readRememberedPomodoroSettings()
        if (
          rememberedSettings !== null &&
          shouldApplyRememberedPomodoroSettings(nextState, rememberedSettings)
        ) {
          const rememberedState = await updatePomodoroSettings(rememberedSettings)
          if (!isActive) return
          applyState(rememberedState, false)
          return
        }
        applyState(nextState, false)
      })
      .catch(() => undefined)
    return () => {
      isActive = false
    }
  }, [])

  useEffect(() => {
    const worker = new Worker(new URL('./pomodoroWorker.ts', import.meta.url), { type: 'module' })
    worker.addEventListener('message', (event: MessageEvent<PomodoroWorkerEvent>) => {
      if (event.data.type === 'tick') {
        setDisplayTick((tick) => tick + 1)
        return
      }
      if (event.data.type === 'sync') {
        void refreshState(true).catch(() => undefined)
      }
    })
    worker.postMessage({ type: 'start', intervalMs: 30_000 })
    return () => {
      worker.postMessage({ type: 'stop' })
      worker.terminate()
    }
  }, [])
  useEffect(() => {
    const eventSource = new EventSource('/api/v1/pomodoro/events', {
      withCredentials: true,
    })
    function handleStateEvent(event: MessageEvent<string>) {
      try {
        const payload = JSON.parse(event.data) as PomodoroSsePayload
        if (payload.state !== undefined) {
          applyState(payload.state, true)
        }
      } catch {
        // EventSource reconnects automatically; periodic sync remains the fallback.
      }
    }
    eventSource.addEventListener('state', handleStateEvent as EventListener)
    return () => {
      eventSource.removeEventListener('state', handleStateEvent as EventListener)
      eventSource.close()
    }
  }, [])


  useEffect(() => {
    function handleVisibilityChange() {
      if (document.visibilityState === 'visible') {
        void refreshState(true).catch(() => undefined)
      }
    }
    window.addEventListener('focus', handleVisibilityChange)
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => {
      window.removeEventListener('focus', handleVisibilityChange)
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [])

  void displayTick

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

  async function handleSettingsSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const nextSettings = {
      work_minutes: workMinutes,
      break_minutes: breakMinutes,
      cycle_count: cycleCount,
    }
    const nextState = await updatePomodoroSettings(nextSettings)
    writeRememberedPomodoroSettings({
      work_minutes: nextState.work_minutes,
      break_minutes: nextState.break_minutes,
      cycle_count: nextState.cycle_count,
    })
    setIsSettingsOpen(false)
    applyState(nextState, false)
  }

  async function handleStartPause() {
    prepareTransitionBell()
    const nextState = state.is_running ? await pausePomodoro() : await startPomodoro()
    applyState(nextState, false)
  }

  async function handleReset() {
    const nextState = await resetPomodoro()
    applyState(nextState, false)
  }

  async function handleSkipPhase() {
    const nextState = await skipPomodoro()
    applyState(nextState, true)
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
            <span>{state.phase === 'done' ? t('pomodoro.done') : state.phase === 'work' ? t('pomodoro.work') : t('pomodoro.break')}</span>
            <strong>{t('pomodoro.cycle', { current: String(state.current_cycle), total: String(state.cycle_count) })}</strong>
          </div>

          <div
            aria-label={t('pomodoro.remaining')}
            className="pomodoro-dial"
            style={{ '--pomodoro-progress': `${progress * 360}deg` } as CSSProperties}
          >
            <strong>{timeLabel}</strong>
            <span>{state.phase === 'done' ? t('pomodoro.completed') : t('pomodoro.remaining')}</span>
          </div>

          <div className="pomodoro-controls">
            <button
              disabled={state.phase === 'done'}
              onClick={() => { void handleStartPause() }}
              type="button"
            >
              {state.is_running ? t('pomodoro.pause') : t('pomodoro.start')}
            </button>
            <button onClick={() => { void handleReset() }} type="button">
              {t('pomodoro.reset')}
            </button>
            <button disabled={state.phase === 'done'} onClick={() => { void handleSkipPhase() }} type="button">
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
        icon_content_type: imageUploadContentType(selectedFile),
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
        payload.icon_content_type = imageUploadContentType(editingFile)
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
                        accept={imageUploadAccept}
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
                  accept={imageUploadAccept}
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
        icon_content_type: imageUploadContentType(selectedFile),
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
        payload.icon_content_type = imageUploadContentType(editingFile)
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
                          accept={imageUploadAccept}
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
                    accept={imageUploadAccept}
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
  const [isResettingPassword, setIsResettingPassword] = useState(false)
  const [passwordResetNotice, setPasswordResetNotice] = useState<string | null>(null)
  const [isSessionChecked, setIsSessionChecked] = useState(false)
  const [path, setPath] = useState(window.location.pathname)
  const [routePreload, setRoutePreload] = useState<RoutePreload | null>(null)
  const [navigationError, setNavigationError] = useState<string | null>(null)
  const [pendingContactNotice, setPendingContactNotice] =
    useState<PendingContactNotice | null>(null)
  const [pendingContactSecondsLeft, setPendingContactSecondsLeft] = useState(30)
  const routeTransitionId = useRef(0)

  useEffect(() => installZoomLayoutGuard(), [])

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
    if (session === null || !isSessionChecked) {
      return
    }
    const requested = requestedViewModeFromLocation()
    if (requested !== null) {
      rememberViewMode(requested)
    }
    if (path === '/' && shouldOpenMobileTop(requested)) {
      transitionToPreparedRoute('/m', 'replace')
    }
  }, [path, session, isSessionChecked])

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
    setPasswordResetNotice(null)
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
        access_mode: loginSession.access_mode,
      })
      if (loginSession.access_mode === 'low_mail_review') {
        window.history.replaceState({}, '', '/mail/review')
        setRoutePreload(null)
        setPath('/mail/review')
      }
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

  async function handlePasswordReset() {
    setError(null)
    setPasswordResetNotice(null)
    setIsResettingPassword(true)
    try {
      await resetPasswordByEmail()
      setPassword('')
      setIsLocked(false)
      setPasswordResetNotice(t('login.reset.sent'))
    } catch (resetError) {
      setError(
        resetError instanceof AuthApiError
          ? resetError.message
          : t('auth.requestFailed'),
      )
    } finally {
      setIsResettingPassword(false)
    }
  }

  if (session !== null) {
    if (session.access_mode === 'low_mail_review') {
      const reviewDetailPrefix = '/mail/review/'
      if (path.startsWith(reviewDetailPrefix)) {
        return (
          <LowMailReviewDetailView
            messageId={decodeURIComponent(path.slice(reviewDetailPrefix.length))}
          />
        )
      }
      return <LowMailReviewView />
    }
    if (path === '/m/calendar' || path === '/mobile/calendar') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <MobileCalendarDayView />
        </>
      )
    }
    if (path === '/m/mail/action-needed' || path === '/mobile/mail/action-needed') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <MobileMailDayView mode="action-needed" />
        </>
      )
    }
    if (path.startsWith('/m/mail/') || path.startsWith('/mobile/mail/')) {
      const prefix = path.startsWith('/m/mail/') ? '/m/mail/' : '/mobile/mail/'
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <MobileMailThreadView messageId={decodeURIComponent(path.slice(prefix.length))} />
        </>
      )
    }
    if (path === '/m/mail' || path === '/mobile/mail') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <MobileMailDayView />
        </>
      )
    }
    if (path.startsWith('/m/tasks/') || path.startsWith('/mobile/tasks/')) {
      const prefix = path.startsWith('/m/tasks/') ? '/m/tasks/' : '/mobile/tasks/'
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <MobileTaskDetailView taskId={decodeURIComponent(path.slice(prefix.length))} />
        </>
      )
    }
    if (path === '/m/tasks' || path === '/mobile/tasks') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <MobileTaskListView />
        </>
      )
    }
    if (path === '/m/settings' || path === '/mobile/settings') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <MobileSettingsView />
        </>
      )
    }
    if (path === '/m' || path === '/mobile') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <MobileTopView />
        </>
      )
    }
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
    if (path === '/bookshelf') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <BookshelfView />
        </>
      )
    }
    if (path === '/bookshelf/tag-hierarchy') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <BookshelfTagHierarchyView />
        </>
      )
    }
    if (path === '/papers') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <PaperShelfView />
        </>
      )
    }
    if (path === '/paper-journal-icons') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <PaperJournalIconsView />
        </>
      )
    }
    if (path.startsWith('/papers/')) {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <PaperDetailView paperId={decodeURIComponent(path.slice('/papers/'.length))} />
        </>
      )
    }
    if (path.startsWith('/bookshelf/')) {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <BookshelfReaderView storageObjectId={decodeURIComponent(path.slice('/bookshelf/'.length))} />
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
    if (path === '/case-auto-assign-rules') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <CaseAutoAssignRulesView />
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
    if (path === '/calendar/conflicts') {
      return (
        <>
          {pendingContactNoticeElement}
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <CalendarConflictView />
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
    if (path === '/contact-auto-tag-rules') {
      return <><ContactAutoTagRulesView /></>
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
            {passwordResetNotice !== null && (
              <p className="login-reset-notice" role="status">
                {passwordResetNotice}
              </p>
            )}
            {isLocked && <p className="lock-status">{t('login.locked')}</p>}

            <button
              className={`button-loading-dot${isSubmitting ? ' is-loading' : ''}`}
              disabled={isSubmitting || isResettingPassword}
              type="submit"
            >
              {t('login.submit')}
            </button>
            <p className="login-reset-description">
              {t('login.reset.description')}
            </p>
            <button
              className="login-reset-button"
              disabled={isSubmitting || isResettingPassword}
              onClick={() => void handlePasswordReset()}
              type="button"
            >
              {isResettingPassword
                ? t('login.reset.sending')
                : t('login.reset.submit')}
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
