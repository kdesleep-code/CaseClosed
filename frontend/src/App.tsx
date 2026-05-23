import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { AuthApiError, login, readSession } from './authApi'
import type { SessionData } from './authApi'
import loginDoorTanuki from './assets/login-door-tanuki.png'
import MaintenanceView from './MaintenanceView'
import './App.css'

const pageLinks = [
  { label: 'Mail', href: '/mail' },
  { label: 'Cases', href: '/cases' },
  { label: 'Tasks', href: '/tasks' },
  { label: 'Calendar', href: '/calendar' },
  { label: 'Contacts', href: '/contacts' },
  { label: 'Files', href: '/files' },
  { label: 'Logs', href: '/logs' },
  { label: 'Settings', href: '/settings' },
  { label: 'Maintenance', href: '/maintenance' },
]

const workLinks = [
  { label: 'Compose Mail', href: '/mail/compose' },
  { label: 'New Case', href: '/cases/new' },
  { label: 'New Task', href: '/tasks/new' },
  { label: 'Pending Contacts', href: '/contacts/pending' },
]

function formatJstDateTime(value: string | null) {
  if (value === null) {
    return 'Unavailable'
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
        setError('Authentication request failed.')
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  if (session !== null) {
    if (window.location.pathname === '/maintenance') {
      return <MaintenanceView />
    }

    return (
      <main className="app-shell">
        <div className="top-shell">
          <header className="top-header">
            <div>
              <p>CaseClosed</p>
              <h1>Top</h1>
            </div>

            <p aria-label="Current session" className="session-meta">
              Session:{' '}
              {session.device_name ??
                (session.ip_address !== null
                  ? `IP ${session.ip_address}`
                  : 'Login source unavailable')}{' '}
              | Expires:{' '}
              {formatJstDateTime(sessionExpiresAt)}
            </p>
          </header>

          <section aria-labelledby="pages-heading" className="hub-section">
            <h2 id="pages-heading">Pages</h2>

            <nav aria-label="Main pages" className="hub-links">
              {pageLinks.map((link) => (
                <a href={link.href} key={link.href}>
                  {link.label}
                </a>
              ))}
            </nav>
          </section>

          <section aria-labelledby="work-heading" className="hub-section">
            <h2 id="work-heading">Work</h2>

            <nav aria-label="Main work" className="work-links">
              {workLinks.map((link) => (
                <a href={link.href} key={link.href}>
                  {link.label}
                </a>
              ))}
            </nav>
          </section>
        </div>
      </main>
    )
  }

  if (!isSessionChecked) {
    return <main aria-label="Checking session" className="app-shell" />
  }

  return (
    <main className="app-shell">
      <div className="login-layout">
        <section className="login-panel">
          <header className="login-heading">
            <h1>CaseClosed</h1>
          </header>

          <form className="login-form" onSubmit={handleSubmit}>
            <label className="password-field">
              <span>Password</span>
              <input
                autoComplete="current-password"
                name="password"
                onChange={(event) => setPassword(event.target.value)}
                type="password"
                value={password}
              />
            </label>

            {error !== null && <p role="alert">{error}</p>}
            {isLocked && <p className="lock-status">Locked</p>}

            <button disabled={isSubmitting} type="submit">
              Log in
            </button>
          </form>
        </section>

        <figure className="login-illustration">
          <img alt="CaseClosed mascot" src={loginDoorTanuki} />
        </figure>
      </div>
    </main>
  )
}

export default App
