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
import { createCaseGenre, listCaseGenres, listCases, updateCaseGenre } from './phase7Api'
import type { CaseGenre, CaseItem } from './phase7Api'

const sampleManifestPath = 'extensions/user-extensions/information-literacy-report-1-1/caseclosed-extension.json'
const caseTemplateTag = 'case-template'

type RegisterFormType = 'tool' | 'case-template'
type TemplateGenreMode = 'new' | 'existing'

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


function extensionIsCaseTemplate(extension: ExtensionDefinition, genres: CaseGenre[]) {
  if (extension.tags.some((tag) => tag.trim().toLowerCase() === caseTemplateTag)) return true
  return genres.some((genre) => genre.template_extension_id === extension.id)
}

function extensionTemplateGenreNames(extension: ExtensionDefinition, genres: CaseGenre[]) {
  return genres
    .filter((genre) => genre.template_extension_id === extension.id)
    .map((genre) => genre.title)
}

export default function ExtensionsView() {
  const [extensions, setExtensions] = useState<ExtensionDefinition[]>([])
  const [instances, setInstances] = useState<ExtensionInstance[]>([])
  const [cases, setCases] = useState<CaseItem[]>([])
  const [genres, setGenres] = useState<CaseGenre[]>([])
  const [manifestPath, setManifestPath] = useState(sampleManifestPath)
  const [rootPath, setRootPath] = useState('')
  const [templateManifestPath, setTemplateManifestPath] = useState(sampleManifestPath)
  const [templateRootPath, setTemplateRootPath] = useState('')
  const [templateGenreMode, setTemplateGenreMode] = useState<TemplateGenreMode>('new')
  const [templateGenreTitle, setTemplateGenreTitle] = useState('')
  const [templateGenreColor, setTemplateGenreColor] = useState('#88ccff')
  const [templateExistingGenreId, setTemplateExistingGenreId] = useState('')
  const [idleTimeoutMinutesByExtension, setIdleTimeoutMinutesByExtension] = useState<Record<string, string>>(
    initialIdleTimeoutMinutesByExtension,
  )
  const [isLoading, setIsLoading] = useState(true)
  const [openForm, setOpenForm] = useState<RegisterFormType | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  async function refresh() {
    setError(null)
    const [extensionList, caseList, genreList] = await Promise.all([
      listExtensions(),
      listCases('all'),
      listCaseGenres(),
    ])
    setExtensions(extensionList.items)
    setInstances(extensionList.running_instances)
    setCases(caseList)
    setGenres(genreList)
  }

  useEffect(() => {
    let isActive = true
    setIsLoading(true)
    void Promise.all([listExtensions(), listCases('all'), listCaseGenres()])
      .then(([extensionList, caseList, genreList]) => {
        if (!isActive) return
        setExtensions(extensionList.items)
        setInstances(extensionList.running_instances)
        setCases(caseList)
        setGenres(genreList)
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

  const caseTemplateExtensions = useMemo(
    () => extensions.filter((extension) => extensionIsCaseTemplate(extension, genres)),
    [extensions, genres],
  )
  const toolExtensions = useMemo(
    () => extensions.filter((extension) => !extensionIsCaseTemplate(extension, genres)),
    [extensions, genres],
  )
  const defaultExtensions = useMemo(
    () => toolExtensions.filter((extension) => extension.source === 'default'),
    [toolExtensions],
  )
  const userExtensions = useMemo(
    () => toolExtensions.filter((extension) => extension.source !== 'default'),
    [toolExtensions],
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
      setOpenForm(null)
      await refresh()
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('extensions.requestFailed'))
    } finally {
      setBusyId(null)
    }
  }

  async function handleRegisterCaseTemplate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (templateManifestPath.trim() === '' && templateRootPath.trim() === '') return
    if (templateGenreMode === 'new' && templateGenreTitle.trim() === '') return
    if (templateGenreMode === 'existing' && templateExistingGenreId.trim() === '') return
    setBusyId('register-case-template')
    setError(null)
    setNotice(null)
    try {
      const extension = await registerExtension({
        manifest_path: templateManifestPath.trim() === '' ? null : templateManifestPath.trim(),
        root_path: templateRootPath.trim() === '' ? null : templateRootPath.trim(),
      })
      const templateContext = { mode: 'case_template' }
      if (templateGenreMode === 'new') {
        await createCaseGenre({
          title: templateGenreTitle.trim(),
          color_hex: templateGenreColor,
          template_extension_id: extension.id,
          template_context: templateContext,
        })
      } else {
        await updateCaseGenre(templateExistingGenreId, {
          template_extension_id: extension.id,
          template_context: templateContext,
        })
      }
      setNotice(t('extensions.caseTemplateRegistered', { name: extension.name }))
      setOpenForm(null)
      setTemplateGenreTitle('')
      setTemplateExistingGenreId('')
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
              { href: '/', labelKey: 'top.heading' },
              { href: '/external-tools', labelKey: 'nav.externalTools' },
              { href: '/cases', labelKey: 'nav.cases' },
              { href: '/settings', labelKey: 'nav.settings' },
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
                <button onClick={() => setOpenForm((current) => (current === 'tool' ? null : 'tool'))} type="button">
                  {openForm === 'tool' ? t('common.cancel') : t('extensions.registerTool')}
                </button>
                <button onClick={() => setOpenForm((current) => (current === 'case-template' ? null : 'case-template'))} type="button">
                  {openForm === 'case-template' ? t('common.cancel') : t('extensions.registerCaseTemplate')}
                </button>
                <button disabled={busyId === 'refresh'} onClick={() => { void handleRefresh() }} type="button">
                  {t('extensions.refresh')}
                </button>
              </div>
            </div>

            {openForm === 'tool' && (
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
                  {t('extensions.registerTool')}
                </button>
              </form>
            )}

            {openForm === 'case-template' && (
              <form className="extensions-register-form extensions-template-form" onSubmit={handleRegisterCaseTemplate}>
                <label>
                  <span>{t('extensions.manifestPath')}</span>
                  <input onChange={(event) => setTemplateManifestPath(event.target.value)} value={templateManifestPath} />
                </label>
                <label>
                  <span>{t('extensions.rootPath')}</span>
                  <input onChange={(event) => setTemplateRootPath(event.target.value)} value={templateRootPath} />
                </label>
                <label>
                  <span>{t('extensions.templateGenreMode')}</span>
                  <select
                    onChange={(event) => setTemplateGenreMode(event.target.value as TemplateGenreMode)}
                    value={templateGenreMode}
                  >
                    <option value="new">{t('extensions.templateGenreNew')}</option>
                    <option value="existing">{t('extensions.templateGenreExisting')}</option>
                  </select>
                </label>
                {templateGenreMode === 'new' ? (
                  <>
                    <label>
                      <span>{t('extensions.templateGenreTitle')}</span>
                      <input onChange={(event) => setTemplateGenreTitle(event.target.value)} value={templateGenreTitle} />
                    </label>
                    <label>
                      <span>{t('extensions.templateGenreColor')}</span>
                      <input onChange={(event) => setTemplateGenreColor(event.target.value)} type="color" value={templateGenreColor} />
                    </label>
                  </>
                ) : (
                  <label>
                    <span>{t('extensions.templateGenreExisting')}</span>
                    <select
                      onChange={(event) => setTemplateExistingGenreId(event.target.value)}
                      value={templateExistingGenreId}
                    >
                      <option value="">{t('common.none')}</option>
                      {genres.map((genre) => (
                        <option key={genre.id} value={genre.id}>{genre.title}</option>
                      ))}
                    </select>
                  </label>
                )}
                <button className={`button-loading-dot${busyId === 'register-case-template' ? ' is-loading' : ''}`} disabled={busyId !== null} type="submit">
                  {t('extensions.registerCaseTemplate')}
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
                  extensions={caseTemplateExtensions}
                  genres={genres}
                  idleTimeoutMinutesByExtension={idleTimeoutMinutesByExtension}
                  instancesByExtensionId={instancesByExtensionId}
                  onIdleTimeoutChange={handleIdleTimeoutChange}
                  onStop={handleStop}
                  title={t('extensions.caseTemplateGroup')}
                />
                <ExtensionGroup
                  busyId={busyId}
                  cases={cases}
                  extensions={defaultExtensions}
                  genres={genres}
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
                  genres={genres}
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
  genres,
  idleTimeoutMinutesByExtension,
  instancesByExtensionId,
  onIdleTimeoutChange,
  onStop,
  title,
}: {
  busyId: string | null
  cases: CaseItem[]
  extensions: ExtensionDefinition[]
  genres: CaseGenre[]
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
              {extensionTemplateGenreNames(extension, genres).length > 0 && (
                <div className="extension-tags extension-genre-links">
                  {extensionTemplateGenreNames(extension, genres).map((genreName) => (
                    <span key={genreName}>{genreName}</span>
                  ))}
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
