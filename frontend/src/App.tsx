import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { AuthApiError, login, readSession } from './authApi'
import type { SessionData } from './authApi'
import loginDoorTanuki from './assets/login-door-tanuki.png'
import ContactsView from './ContactsView'
import MaintenanceView from './MaintenanceView'
import { t } from './i18n'
import type { MessageKey } from './i18n'
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
  { labelKey: 'work.composeMail', href: '/mail/compose' },
  { labelKey: 'work.newCase', href: '/cases/new' },
  { labelKey: 'work.newTask', href: '/tasks/new' },
  { labelKey: 'work.pendingContacts', href: '/contacts/pending' },
]

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

function App() {
  const [password, setPassword] = useState('')
  const [session, setSession] = useState<SessionData | null>(null)
  const [sessionExpiresAt, setSessionExpiresAt] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isLocked, setIsLocked] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isSessionChecked, setIsSessionChecked] = useState(false)

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
    if (window.location.pathname === '/maintenance') {
      return <MaintenanceView />
    }
    if (window.location.pathname === '/contacts') {
      return <ContactsView mode="list" />
    }
    if (window.location.pathname === '/contacts/pending') {
      return <ContactsView mode="pending" />
    }

    return (
      <main className="app-shell">
        <div className="top-shell">
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
              | {t('session.expires')}{' '}
              {formatJstDateTime(sessionExpiresAt)}
            </p>
          </header>

          <section aria-labelledby="pages-heading" className="hub-section">
            <h2 id="pages-heading">{t('top.pages.heading')}</h2>

            <nav aria-label={t('top.pages.navLabel')} className="hub-links">
              {pageLinks.map((link) => (
                <a href={link.href} key={link.href}>
                  {t(link.labelKey)}
                </a>
              ))}
            </nav>
          </section>

          <section aria-labelledby="work-heading" className="hub-section">
            <h2 id="work-heading">{t('top.work.heading')}</h2>

            <nav aria-label={t('top.work.navLabel')} className="work-links">
              {workLinks.map((link) => (
                <a href={link.href} key={link.href}>
                  {t(link.labelKey)}
                </a>
              ))}
            </nav>
          </section>
        </div>
      </main>
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
