import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { AuthApiError, login, readSession } from './authApi'
import type { SessionData } from './authApi'
import loginDoorTanuki from './assets/login-door-tanuki.png'
import ComposeMailView from './ComposeMailView'
import ContactsView from './ContactsView'
import type { ContactsInitialData } from './ContactsView'
import MailView from './MailView'
import type { MailInitialData } from './MailView'
import type { MailTab } from './MailView'
import MailThreadView from './MailThreadView'
import MaintenanceView from './MaintenanceView'
import type { MaintenanceInitialData } from './MaintenanceView'
import { t } from './i18n'
import type { MessageKey } from './i18n'
import { AppLink } from './navigation'
import {
  listExternalOperations,
  listJobs,
  listPendingMails,
  readMaintenanceStatus,
} from './phase2Api'
import { listContacts, listUnresolvedFromAddresses } from './phase3Api'
import { listMailDates, listMailPage } from './phase4Api'
import './App.css'

type LinkItem = {
  labelKey: MessageKey
  href: string
}

const pageLinks: LinkItem[] = [
  { labelKey: 'nav.mail', href: '/mail' },
  { labelKey: 'nav.cases', href: '/cases' },
  { labelKey: 'nav.tasks', href: '/tasks' },
  { labelKey: 'nav.calendar', href: '/calendar' },
  { labelKey: 'nav.contacts', href: '/contacts' },
  { labelKey: 'nav.files', href: '/files' },
  { labelKey: 'nav.logs', href: '/logs' },
  { labelKey: 'nav.settings', href: '/settings' },
  { labelKey: 'nav.maintenance', href: '/maintenance' },
]

const workLinks: LinkItem[] = [
  { labelKey: 'work.newCase', href: '/cases/new' },
  { labelKey: 'work.newTask', href: '/tasks/new' },
]

type RoutePreload =
  | { path: '/'; pendingCount: number }
  | { path: '/mail'; pendingCount: number; mail?: MailInitialData }
  | { path: '/contacts'; contacts: ContactsInitialData }
  | { path: '/contacts/pending'; contacts: ContactsInitialData }
  | { path: '/maintenance'; maintenance: MaintenanceInitialData }
  | { path: 'other'; routePath: string }

type NavigationRequestEvent = CustomEvent<{
  path: string
  replace: boolean
}>

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

function startOfDate(date: string) {
  return `${date}T00:00:00+09:00`
}

function endOfDate(date: string) {
  return `${date}T23:59:59+09:00`
}

function currentBrowserPath() {
  return `${window.location.pathname}${window.location.search}${window.location.hash}`
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

async function loadMailInitialData(routeUrl: URL): Promise<MailInitialData> {
  const activeTab = mailTabFromSearchParams(routeUrl.searchParams)
  const requestedDate = requestedDateFromSearchParams(routeUrl.searchParams)
  const mailDates = await listMailDates(activeTab)
  const today = jstDateToday()
  const selectedDate =
    requestedDate ??
    (mailDates.some((item) => item.date === today)
      ? today
      : mailDates.at(-1)?.date ?? today)
  const page = await listMailPage({
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

  if (routePath === '/mail') {
    const pendingContacts = await listUnresolvedFromAddresses()
    if (pendingContacts.length > 0) {
      return { path: '/mail', pendingCount: pendingContacts.length }
    }

    const mail = await loadMailInitialData(routeUrl)
    return {
      path: '/mail',
      pendingCount: 0,
      mail,
    }
  }

  return { path: 'other', routePath: path }
}

function MailRouteGate() {
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

function PreloadedMailRoute({ preload }: { preload?: RoutePreload }) {
  if (preload?.path === '/mail' && preload.pendingCount > 0) {
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

  if (preload?.path === '/mail' && preload.mail !== undefined) {
    return <MailView initialData={preload.mail} />
  }

  return <MailRouteGate />
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

  function lockedLink(link: LinkItem, className?: string) {
    if (!isLockedByPending) {
      return (
        <AppLink className={className} href={link.href} key={link.href}>
          {t(link.labelKey)}
        </AppLink>
      )
    }
    return (
      <span aria-disabled="true" className={className} key={link.href}>
        {t(link.labelKey)}
      </span>
    )
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

        <section aria-labelledby="pages-heading" className="hub-section">
          <h2 id="pages-heading">{t('top.pages.heading')}</h2>

          <nav aria-label={t('top.pages.navLabel')} className="hub-links">
            {pageLinks.map((link) => lockedLink(link))}
          </nav>
        </section>

        <section aria-labelledby="work-heading" className="hub-section">
          <h2 id="work-heading">{t('top.work.heading')}</h2>

          <nav aria-label={t('top.work.navLabel')} className="work-links">
            {workLinks.map((link) => lockedLink(link))}
          </nav>
        </section>
      </div>
    </main>
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
    if (path === '/mail') {
      return (
        <>
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <PreloadedMailRoute preload={routePreload ?? undefined} />
        </>
      )
    }
    if (path === '/mail/compose') {
      return (
        <>
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <ComposeMailView />
        </>
      )
    }
    if (path.startsWith('/mail/')) {
      return (
        <>
          {navigationError !== null && <p className="route-error">{navigationError}</p>}
          <MailThreadView messageId={decodeURIComponent(path.slice('/mail/'.length))} />
        </>
      )
    }
    if (path === '/contacts') {
      return (
        <>
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

    return (
      <>
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

            <button disabled={isSubmitting} type="submit">
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
