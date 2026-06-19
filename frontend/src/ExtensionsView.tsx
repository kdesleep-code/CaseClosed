import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import {
  listExtensions,
  registerExtension,
  stopExtensionInstance,
} from './extensionsApi'
import type { ExtensionDefinition, ExtensionInstance } from './extensionsApi'
import {
  defaultExtensionIdleTimeoutMinutes,
  extensionInstancesChangedStorageKey,
  extensionIdleTimeoutByExtensionStorageKey,
} from './ExtensionLaunchView'
import { t } from './i18n'
import { AppLink, TopNav } from './navigation'
import { listCases } from './phase7Api'
import type { CaseItem } from './phase7Api'

const sampleManifestPath = 'extensions/user-extensions/information-literacy-report-1-1/caseclosed-extension.json'

function initialIdleTimeoutMinutesByExtension() {
  try {
    const storedValue = JSON.parse(
      window.localStorage.getItem(extensionIdleTimeoutByExtensionStorageKey) ?? '{}',
    ) as Record<string, unknown>
    return Object.fromEntries(
      Object.entries(storedValue).map(([extensionId, value]) => {
        const minutes = Number.parseInt(String(value), 10)
        return [
          extensionId,
          Number.isFinite(minutes)
            ? String(Math.max(1, Math.min(minutes, 24 * 60)))
            : String(defaultExtensionIdleTimeoutMinutes),
        ]
      }),
    )
  } catch {
    return {}
  }
}

function formatDateTime(value: string | null) {
  if (value === null || value.trim() === '') return t('common.none')
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('ja-JP', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

function extensionCaseName(instance: ExtensionInstance, cases: CaseItem[]) {
  if (instance.case_id === null) return t('extensions.noCase')
  return cases.find((item) => item.id === instance.case_id)?.name ?? instance.case_id
}

function extensionLaunchPath(extensionId: string) {
  return `/extensions/launch?extension_id=${encodeURIComponent(extensionId)}`
}

function extensionLaunchTarget(extensionId: string) {
  return `caseclosed_extension_${extensionId}_no_case`.replace(/[^a-zA-Z0-9_]/g, '_')
}

export default function ExtensionsView() {
  const [extensions, setExtensions] = useState<ExtensionDefinition[]>([])
  const [instances, setInstances] = useState<ExtensionInstance[]>([])
  const [cases, setCases] = useState<CaseItem[]>([])
  const [manifestPath, setManifestPath] = useState(sampleManifestPath)
  const [rootPath, setRootPath] = useState('')
  const [idleTimeoutMinutesByExtension, setIdleTimeoutMinutesByExtension] = useState<Record<string, string>>(
    initialIdleTimeoutMinutesByExtension,
  )
  const [isLoading, setIsLoading] = useState(true)
  const [isFormOpen, setIsFormOpen] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  async function refresh() {
    setError(null)
    const [extensionList, caseList] = await Promise.all([listExtensions(), listCases('all')])
    setExtensions(extensionList.items)
    setInstances(extensionList.running_instances)
    setCases(caseList)
  }

  useEffect(() => {
    let isActive = true
    setIsLoading(true)
    void Promise.all([listExtensions(), listCases('all')])
      .then(([extensionList, caseList]) => {
        if (!isActive) return
        setExtensions(extensionList.items)
        setInstances(extensionList.running_instances)
        setCases(caseList)
      })
      .catch((requestError) => {
        if (!isActive) return
        setError(requestError instanceof Error ? requestError.message : t('extensions.requestFailed'))
      })
      .finally(() => {
        if (isActive) setIsLoading(false)
      })
    return () => {
      isActive = false
    }
  }, [])

  useEffect(() => {
    let isRefreshing = false
    async function refreshIfIdle() {
      if (isRefreshing) return
      isRefreshing = true
      try {
        await refresh()
      } catch (requestError) {
        setError(requestError instanceof Error ? requestError.message : t('extensions.requestFailed'))
      } finally {
        isRefreshing = false
      }
    }
    function handleStorage(event: StorageEvent) {
      if (event.key === extensionInstancesChangedStorageKey) {
        void refreshIfIdle()
      }
    }
    function handleVisibilityChange() {
      if (document.visibilityState === 'visible') {
        void refreshIfIdle()
      }
    }
    window.addEventListener('storage', handleStorage)
    window.addEventListener('focus', refreshIfIdle)
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => {
      window.removeEventListener('storage', handleStorage)
      window.removeEventListener('focus', refreshIfIdle)
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [])

  const instancesByExtensionId = useMemo(() => {
    const grouped = new Map<string, ExtensionInstance[]>()
    for (const instance of instances) {
      const current = grouped.get(instance.extension_id) ?? []
      current.push(instance)
      grouped.set(instance.extension_id, current)
    }
    return grouped
  }, [instances])

  const defaultExtensions = useMemo(
    () => extensions.filter((extension) => extension.source === 'default'),
    [extensions],
  )
  const userExtensions = useMemo(
    () => extensions.filter((extension) => extension.source !== 'default'),
    [extensions],
  )

  async function handleRefresh() {
    setBusyId('refresh')
    try {
      await refresh()
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('extensions.requestFailed'))
    } finally {
      setBusyId(null)
    }
  }

  async function handleRegister(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (manifestPath.trim() === '' && rootPath.trim() === '') return
    setBusyId('register')
    setError(null)
    setNotice(null)
    try {
      const extension = await registerExtension({
        manifest_path: manifestPath.trim() === '' ? null : manifestPath.trim(),
        root_path: rootPath.trim() === '' ? null : rootPath.trim(),
      })
      setNotice(t('extensions.registered', { name: extension.name }))
      setIsFormOpen(false)
      await refresh()
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('extensions.requestFailed'))
    } finally {
      setBusyId(null)
    }
  }

  function handleIdleTimeoutChange(extensionId: string, value: string) {
    const nextValues = { ...idleTimeoutMinutesByExtension, [extensionId]: value }
    setIdleTimeoutMinutesByExtension(nextValues)
    const minutes = Number.parseInt(value, 10)
    if (!Number.isFinite(minutes)) return
    window.localStorage.setItem(extensionIdleTimeoutByExtensionStorageKey, JSON.stringify({
      ...nextValues,
      [extensionId]: String(Math.max(1, Math.min(minutes, 24 * 60))),
    }))
  }

  async function handleStop(instance: ExtensionInstance) {
    setBusyId(`stop-${instance.id}`)
    setError(null)
    setNotice(null)
    try {
      await stopExtensionInstance(instance.id)
      setNotice(t('extensions.stopped'))
      await refresh()
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('extensions.requestFailed'))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <main className="app-shell">
      <div className="maintenance-shell extensions-shell">
        <header className="maintenance-header">
          <div>
            <p>{t('app.name')}</p>
            <h1>{t('extensions.heading')}</h1>
          </div>
          <TopNav
            ariaLabelKey="extensions.navigation"
            items={[
              { href: '/external-tools', labelKey: 'nav.externalTools' },
              { href: '/', labelKey: 'top.heading' },
            ]}
          />
        </header>

        {error !== null && <p className="maintenance-error" role="alert">{error}</p>}
        {notice !== null && <div className="mail-feedback"><p>{notice}</p></div>}

        <section className="maintenance-panel-surface extensions-panel">
          <div className="maintenance-panel extensions-main">
            <div className="section-heading">
              <div>
                <h2>{t('extensions.management')}</h2>
                <p>{t('extensions.summary')}</p>
              </div>
              <div className="extensions-actions">
                <AppLink href="/extensions/help">{t('extensions.guide')}</AppLink>
                <button onClick={() => setIsFormOpen((current) => !current)} type="button">
                  {isFormOpen ? t('common.cancel') : t('extensions.register')}
                </button>
                <button disabled={busyId === 'refresh'} onClick={() => { void handleRefresh() }} type="button">
                  {t('extensions.refresh')}
                </button>
              </div>
            </div>

            {isFormOpen && (
              <form className="extensions-register-form" onSubmit={handleRegister}>
                <label>
                  <span>{t('extensions.manifestPath')}</span>
                  <input onChange={(event) => setManifestPath(event.target.value)} value={manifestPath} />
                </label>
                <label>
                  <span>{t('extensions.rootPath')}</span>
                  <input onChange={(event) => setRootPath(event.target.value)} value={rootPath} />
                </label>
                <button className={`button-loading-dot${busyId === 'register' ? ' is-loading' : ''}`} disabled={busyId !== null} type="submit">
                  {t('extensions.register')}
                </button>
              </form>
            )}

            {isLoading ? (
              <p>{t('common.loading')}</p>
            ) : extensions.length === 0 ? (
              <p className="mail-empty">{t('extensions.empty')}</p>
            ) : (
              <div className="extension-groups">
                <ExtensionGroup
                  busyId={busyId}
                  cases={cases}
                  extensions={defaultExtensions}
                  idleTimeoutMinutesByExtension={idleTimeoutMinutesByExtension}
                  instancesByExtensionId={instancesByExtensionId}
                  onIdleTimeoutChange={handleIdleTimeoutChange}
                  onStop={handleStop}
                  title={t('extensions.defaultGroup')}
                />
                <ExtensionGroup
                  busyId={busyId}
                  cases={cases}
                  extensions={userExtensions}
                  idleTimeoutMinutesByExtension={idleTimeoutMinutesByExtension}
                  instancesByExtensionId={instancesByExtensionId}
                  onIdleTimeoutChange={handleIdleTimeoutChange}
                  onStop={handleStop}
                  title={t('extensions.userGroup')}
                />
              </div>
            )}
          </div>
        </section>
      </div>
    </main>
  )
}

function ExtensionGroup({
  busyId,
  cases,
  extensions,
  idleTimeoutMinutesByExtension,
  instancesByExtensionId,
  onIdleTimeoutChange,
  onStop,
  title,
}: {
  busyId: string | null
  cases: CaseItem[]
  extensions: ExtensionDefinition[]
  idleTimeoutMinutesByExtension: Record<string, string>
  instancesByExtensionId: Map<string, ExtensionInstance[]>
  onIdleTimeoutChange: (extensionId: string, value: string) => void
  onStop: (instance: ExtensionInstance) => Promise<void>
  title: string
}) {
  const [copiedExtensionId, setCopiedExtensionId] = useState<string | null>(null)

  async function handleCopyLaunchUrl(extensionId: string) {
    const url = extensionLaunchPath(extensionId)
    if (navigator.clipboard !== undefined) {
      await navigator.clipboard.writeText(url)
    } else {
      const textarea = document.createElement('textarea')
      textarea.value = url
      textarea.setAttribute('readonly', 'true')
      textarea.style.position = 'fixed'
      textarea.style.left = '-9999px'
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      textarea.remove()
    }
    setCopiedExtensionId(extensionId)
    window.setTimeout(() => {
      setCopiedExtensionId((current) => (current === extensionId ? null : current))
    }, 1400)
  }

  if (extensions.length === 0) return null
  return (
    <section className="extension-group">
      <div className="extension-group-heading">
        <h3>{title}</h3>
      </div>
      <div className="extensions-grid">
        {extensions.map((extension) => {
          const extensionInstances = instancesByExtensionId.get(extension.id) ?? []
          return (
            <article className="extension-card" key={extension.id}>
              <div className="extension-card-header">
                <div>
                  <h3>{extension.name}</h3>
                  <p>{extension.description ?? extension.slug}</p>
                </div>
                <div className="extension-card-actions">
                  <span className="extension-status">{extension.source === 'default' ? t('extensions.defaultBadge') : extension.status}</span>
                  <AppLink href={extensionLaunchPath(extension.id)} target={extensionLaunchTarget(extension.id)}>{t('extensions.openLauncher')}</AppLink>
                </div>
              </div>
              {extension.tags.length > 0 && (
                <div className="extension-tags">
                  {extension.tags.map((tag) => <span key={tag}>{tag}</span>)}
                </div>
              )}
              {extensionInstances.length > 0 && (
                <div className="extension-instance-list">
                  <h4>{t('extensions.running')}</h4>
                  {extensionInstances.map((instance) => (
                    <div className="extension-instance" key={instance.id}>
                      <div>
                        <strong>{extensionCaseName(instance, cases)}</strong>
                        <span>
                          {t('extensions.port')} {instance.port} · {t('extensions.startedAt', { value: formatDateTime(instance.started_at) })}
                        </span>
                      </div>
                      <div className="extension-instance-actions">
                        <a href={instance.base_url} rel="noreferrer" target="_blank">{t('extensions.open')}</a>
                        <button
                          disabled={busyId === `stop-${instance.id}`}
                          onClick={() => { void onStop(instance) }}
                          type="button"
                        >
                          {t('extensions.stop')}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
              <details className="extension-details">
                <summary>{t('extensions.details')}</summary>
                <dl className="extension-meta">
                  <div>
                    <dt>{t('extensions.path')}</dt>
                    <dd>{extension.root_path}</dd>
                  </div>
                  <div>
                    <dt>{t('extensions.command')}</dt>
                    <dd>{extension.command.join(' ')}</dd>
                  </div>
                </dl>
                <div className="extension-launch-row">
                  <div>
                    <span>{t('extensions.launchUrl')}</span>
                    <div className="extension-launch-url">
                      <code>{extensionLaunchPath(extension.id)}</code>
                      <button
                        onClick={() => { void handleCopyLaunchUrl(extension.id) }}
                        type="button"
                      >
                        {copiedExtensionId === extension.id ? t('extensions.copied') : t('extensions.copy')}
                      </button>
                    </div>
                  </div>
                  <label>
                    <span>{t('extensions.idleMinutes')}</span>
                    <input
                      min="1"
                      onChange={(event) => onIdleTimeoutChange(extension.id, event.target.value)}
                      type="number"
                      value={idleTimeoutMinutesByExtension[extension.id] ?? String(defaultExtensionIdleTimeoutMinutes)}
                    />
                  </label>
                </div>
              </details>
            </article>
          )
        })}
      </div>
    </section>
  )
}
