import { useEffect, useState } from 'react'
import { startExtension } from './extensionsApi'
import { t } from './i18n'
import { TopNav } from './navigation'

const launchPromises = new Map<string, Promise<{ open_url: string }>>()
export const extensionInstancesChangedStorageKey = 'caseclosed.extensionInstancesChangedAt'
export const extensionIdleTimeoutStorageKey = 'caseclosed.extensionIdleTimeoutMinutes'
export const extensionIdleTimeoutByExtensionStorageKey = 'caseclosed.extensionIdleTimeoutMinutesByExtension'
export const defaultExtensionIdleTimeoutMinutes = 30

function queryParam(search: string, name: string) {
  return new URLSearchParams(search).get(name)?.trim() ?? ''
}

function launchContextFromSettings(search: string) {
  const params = new URLSearchParams(search)
  const genreId = queryParam(search, 'genre_id')
  const genreTitle = queryParam(search, 'genre_title')
  const context: Record<string, unknown> = {}
  for (const [key, value] of params.entries()) {
    if (key.startsWith('context_')) {
      context[key.slice('context_'.length)] = value
    }
  }
  if (genreId !== '') context.genre_id = genreId
  if (genreTitle !== '') context.genre_title = genreTitle
  return Object.keys(context).length === 0 ? null : context
}

function idleTimeoutSecondsFromSettings(search: string) {
  const extensionId = queryParam(search, 'extension_id')
  const queryValue = Number.parseInt(queryParam(search, 'idle_timeout_seconds'), 10)
  if (Number.isFinite(queryValue) && queryValue >= 60) {
    return Math.min(queryValue, 24 * 60 * 60)
  }
  try {
    const storedByExtension = JSON.parse(
      window.localStorage.getItem(extensionIdleTimeoutByExtensionStorageKey) ?? '{}',
    ) as Record<string, unknown>
    const extensionMinutes = Number.parseInt(String(storedByExtension[extensionId] ?? ''), 10)
    if (Number.isFinite(extensionMinutes)) {
      return Math.max(1, Math.min(extensionMinutes, 24 * 60)) * 60
    }
  } catch {
    // Fall back to the legacy global value below.
  }
  const storedMinutes = Number.parseInt(
    window.localStorage.getItem(extensionIdleTimeoutStorageKey) ?? '',
    10,
  )
  const minutes = Number.isFinite(storedMinutes) ? storedMinutes : defaultExtensionIdleTimeoutMinutes
  return Math.max(1, Math.min(minutes, 24 * 60)) * 60
}

export default function ExtensionLaunchView() {
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let isActive = true
    const extensionId = queryParam(window.location.search, 'extension_id')
    const caseId = queryParam(window.location.search, 'case_id')
    if (extensionId === '') {
      setError(t('extensions.launchMissingExtension'))
      return
    }
    const idleTimeoutSeconds = idleTimeoutSecondsFromSettings(window.location.search)
    const launchContext = launchContextFromSettings(window.location.search)
    const launchContextKey = JSON.stringify(launchContext ?? {})
    const launchKey = `${extensionId}:${caseId}:${idleTimeoutSeconds}:${launchContextKey}`
    const existingPromise = launchPromises.get(launchKey)
    const launchPromise = existingPromise ?? startExtension(extensionId, {
      case_id: caseId === '' ? null : caseId,
      context: launchContext ?? undefined,
      idle_timeout_seconds: idleTimeoutSeconds,
    })
    if (existingPromise === undefined) {
      launchPromises.set(launchKey, launchPromise)
      window.setTimeout(() => launchPromises.delete(launchKey), 10000)
    }
    void launchPromise
      .then((result) => {
        if (!isActive) return
        window.localStorage.setItem(extensionInstancesChangedStorageKey, new Date().toISOString())
        window.location.replace(result.open_url)
      })
      .catch((requestError) => {
        if (!isActive) return
        launchPromises.delete(launchKey)
        setError(requestError instanceof Error ? requestError.message : t('extensions.requestFailed'))
      })
    return () => {
      isActive = false
    }
  }, [])

  return (
    <main className="app-shell">
      <div className="maintenance-shell extensions-shell">
        <header className="maintenance-header">
          <div>
            <p>{t('app.name')}</p>
            <h1>{t('extensions.launchHeading')}</h1>
          </div>
          <TopNav
            ariaLabelKey="extensions.navigation"
            items={[
              { href: '/', labelKey: 'top.heading' },
              { href: '/extensions', labelKey: 'extensions.heading' },
              { href: '/external-tools', labelKey: 'nav.externalTools' },
              { href: '/cases', labelKey: 'nav.cases' },
            ]}
          />
        </header>
        <section className="maintenance-panel-surface extensions-panel">
          <div className="maintenance-panel extensions-main">
            {error === null ? (
              <p>{t('extensions.launching')}</p>
            ) : (
              <p className="maintenance-error" role="alert">{error}</p>
            )}
          </div>
        </section>
      </div>
    </main>
  )
}
