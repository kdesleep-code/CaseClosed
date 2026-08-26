import { useEffect, useState } from 'react'
import type { ChangeEvent, FormEvent } from 'react'
import { readUiLanguage, t, writeUiLanguage } from './i18n'
import { TopNav } from './navigation'
import { readLlmCostHistory, runGoogleSpeedTest, updateLlmCostSettings } from './phase2Api'
import type { GoogleSpeedTestResult, LlmCostHistory } from './phase2Api'
import {
  applyMailLlmBlockFilter,
  createGoogleGmailConnectUrl,
  disconnectGoogleGmail,
  getGoogleGmailStatus,
  getLlmModelConfig,
  getLlmPersonalization,
  listLlmBlockFilters,
  listLlmBlockedMails,
  updateGoogleCalendarAutoSyncSettings,
  updateGoogleGmailAutoImportSettings,
  updateLlmBlockFilter,
  updateLlmModelAssignment,
  updateLlmFunctionInstruction,
} from './phase4Api'
import type {
  GoogleGmailStatus,
  LlmBlockedMail,
  LlmBlockFilter,
  LlmModelConfig,
  LlmPersonalizationConfig,
} from './phase4Api'
type SettingsTab = 'google' | 'llm' | 'budget' | 'language'

const settingsTabs = [
  { key: 'google', labelKey: 'settings.tab.google' },
  { key: 'llm', labelKey: 'settings.tab.llm' },
  { key: 'budget', labelKey: 'settings.tab.budget' },
  { key: 'language', labelKey: 'settings.tab.language' },
] as const

function describeError(error: unknown) {
  return error instanceof Error ? error.message : t('settings.requestFailed')
}

function formatMoney(value: number | null | undefined, currency: string) {
  if (value === null || value === undefined) return t('common.none')
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: currency.toUpperCase(),
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  }).format(value)
}

function initialSettingsNotice() {
  const status = new URLSearchParams(window.location.search).get('google_gmail')
  if (status === 'connected') {
    return t('maintenance.debug.googleGmailConnectedNotice')
  }
  if (status === 'error') {
    return t('maintenance.debug.googleGmailErrorNotice')
  }
  return null
}

function initialSettingsTab(): SettingsTab {
  const tab = new URLSearchParams(window.location.search).get("tab")
  return settingsTabs.some((item) => item.key === tab) ? tab as SettingsTab : "google"
}

function fitTextareaToContent(textarea: HTMLTextAreaElement | null) {
  if (textarea === null) return
  textarea.style.height = "auto"
  textarea.style.height = `${textarea.scrollHeight}px`
}

function SettingsView() {
  const [activeTab, setActiveTab] = useState<SettingsTab>(initialSettingsTab)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(initialSettingsNotice)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [googleStatus, setGoogleStatus] = useState<GoogleGmailStatus | null>(null)
  const [llmModelConfig, setLlmModelConfig] = useState<LlmModelConfig | null>(null)
  const [llmPersonalization, setLlmPersonalization] = useState<LlmPersonalizationConfig | null>(null)
  const [llmInstructionDrafts, setLlmInstructionDrafts] = useState<Record<string, string>>({})
  const [llmBlockFilters, setLlmBlockFilters] = useState<LlmBlockFilter[] | null>(null)
  const [llmBlockedMails, setLlmBlockedMails] = useState<LlmBlockedMail[] | null>(null)
  const [llmCostHistory, setLlmCostHistory] = useState<LlmCostHistory | null>(null)
  const [gmailAutoImportEnabled, setGmailAutoImportEnabled] = useState(true)
  const [gmailAutoImportInterval, setGmailAutoImportInterval] = useState('10')
  const [gmailAutoImportMaxMessages, setGmailAutoImportMaxMessages] = useState('100')
  const [calendarAutoSyncEnabled, setCalendarAutoSyncEnabled] = useState(true)
  const [calendarAutoSyncInterval, setCalendarAutoSyncInterval] = useState('60')
  const [calendarAutoSyncMonthCount, setCalendarAutoSyncMonthCount] = useState('3')
  const [googleSpeedTest, setGoogleSpeedTest] = useState<GoogleSpeedTestResult | null>(null)
  const [llmBlockQuery, setLlmBlockQuery] = useState('password')
  const [llmBlockReason, setLlmBlockReason] = useState('May contain password.')
  const [llmMonthlyBudget, setLlmMonthlyBudget] = useState('')
  const [uiLanguage, setUiLanguage] = useState(() => readUiLanguage())

  useEffect(() => {
    document
      .querySelectorAll<HTMLTextAreaElement>(".settings-llm-instruction-form textarea")
      .forEach(fitTextareaToContent)
  }, [llmInstructionDrafts])

  useEffect(() => {
    if (!new URLSearchParams(window.location.search).has('google_gmail')) return
    window.history.replaceState({}, '', '/settings')
  }, [])


  useEffect(() => {
    if (activeTab !== 'google' || googleStatus !== null) return
    let isMounted = true
    getGoogleGmailStatus()
      .then((status) => {
        if (isMounted) setGoogleStatus(status)
      })
      .catch((requestError) => {
        if (isMounted) setError(describeError(requestError))
      })
    return () => {
      isMounted = false
    }
  }, [activeTab, googleStatus])

  useEffect(() => {
    if (googleStatus === null) return
    setGmailAutoImportEnabled(googleStatus.auto_import.enabled)
    setGmailAutoImportInterval(String(googleStatus.auto_import.interval_minutes))
    setGmailAutoImportMaxMessages(String(googleStatus.auto_import.max_messages_per_run))
    setCalendarAutoSyncEnabled(googleStatus.calendar_auto_sync.enabled)
    setCalendarAutoSyncInterval(String(googleStatus.calendar_auto_sync.interval_minutes))
    setCalendarAutoSyncMonthCount(String(googleStatus.calendar_auto_sync.month_count))
  }, [googleStatus])

  useEffect(() => {
    if (activeTab !== 'llm' || llmModelConfig !== null) return
    let isMounted = true
    Promise.all([getLlmModelConfig(), getLlmPersonalization()])
      .then(([config, personalization]) => {
        if (!isMounted) return
        setLlmModelConfig(config)
        setLlmPersonalization(personalization)
        setLlmInstructionDrafts(Object.fromEntries(
          personalization.functions.map((item) => [item.function_type, item.instruction_text]),
        ))
      })
      .catch((requestError) => {
        if (isMounted) setError(describeError(requestError))
      })
    return () => {
      isMounted = false
    }
  }, [activeTab, llmModelConfig, llmPersonalization])

  useEffect(() => {
    if (
      activeTab !== 'llm' ||
      (llmBlockFilters !== null && llmBlockedMails !== null)
    ) {
      return
    }
    let isMounted = true
    Promise.all([listLlmBlockFilters(), listLlmBlockedMails()])
      .then(([nextFilters, nextMails]) => {
        if (!isMounted) return
        setLlmBlockFilters(nextFilters)
        setLlmBlockedMails(nextMails)
      })
      .catch((requestError) => {
        if (!isMounted) return
        setError(describeError(requestError))
        setLlmBlockFilters([])
        setLlmBlockedMails([])
      })
    return () => {
      isMounted = false
    }
  }, [activeTab, llmBlockFilters, llmBlockedMails])

  useEffect(() => {
    if (activeTab !== 'budget' || llmCostHistory !== null) return
    let isMounted = true
    readLlmCostHistory()
      .then((history) => {
        if (!isMounted) return
        setLlmCostHistory(history)
        setLlmMonthlyBudget(history.monthly_budget === null ? '' : String(history.monthly_budget))
      })
      .catch((requestError) => {
        if (isMounted) setError(describeError(requestError))
      })
    return () => {
      isMounted = false
    }
  }, [activeTab, llmCostHistory])

  async function refreshGoogleStatus() {
    setBusyId('google-refresh')
    setError(null)
    try {
      setGoogleStatus(await getGoogleGmailStatus())
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setBusyId(null)
    }
  }

  async function handleGoogleGmailConnect() {
    setBusyId('google-connect')
    setError(null)
    setNotice(null)
    try {
      const result = await createGoogleGmailConnectUrl()
      window.location.href = result.authorization_url
    } catch (requestError) {
      setError(describeError(requestError))
      setBusyId(null)
    }
  }

  async function handleGoogleGmailDisconnect() {
    setBusyId('google-disconnect')
    setError(null)
    setNotice(null)
    try {
      setGoogleStatus(await disconnectGoogleGmail())
      setNotice(t('maintenance.debug.googleGmailDisconnected'))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setBusyId(null)
    }
  }

  async function handleGoogleGmailAutoImportSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusyId('gmail-auto-import')
    setError(null)
    setNotice(null)
    try {
      const intervalMinutes = Math.max(1, Math.min(24 * 60, Number.parseInt(gmailAutoImportInterval, 10) || 10))
      const maxMessagesPerRun = Math.max(1, Math.min(100, Number.parseInt(gmailAutoImportMaxMessages, 10) || 100))
      const settings = await updateGoogleGmailAutoImportSettings({
        enabled: gmailAutoImportEnabled,
        interval_minutes: intervalMinutes,
        max_messages_per_run: maxMessagesPerRun,
      })
      setGoogleStatus((current) => current === null ? current : { ...current, mail_loading_enabled: settings.enabled, auto_import: settings })
      setNotice(t('maintenance.debug.googleGmailAutoImportSaved'))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setBusyId(null)
    }
  }

  async function handleGoogleCalendarAutoSyncSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusyId('calendar-auto-sync')
    setError(null)
    setNotice(null)
    try {
      const intervalMinutes = Math.max(5, Math.min(24 * 60, Number.parseInt(calendarAutoSyncInterval, 10) || 60))
      const monthCount = Math.max(1, Math.min(12, Number.parseInt(calendarAutoSyncMonthCount, 10) || 3))
      const settings = await updateGoogleCalendarAutoSyncSettings({
        enabled: calendarAutoSyncEnabled,
        interval_minutes: intervalMinutes,
        month_count: monthCount,
      })
      setGoogleStatus((current) => current === null ? current : { ...current, calendar_auto_sync: settings })
      setNotice(t('maintenance.debug.googleCalendarAutoSyncSaved'))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setBusyId(null)
    }
  }

  async function handleGoogleSpeedTest() {
    setBusyId('google-speed-test')
    setError(null)
    setNotice(null)
    try {
      setGoogleSpeedTest(await runGoogleSpeedTest())
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setBusyId(null)
    }
  }

  async function handleLlmModelAssignment(functionType: string, profileId: string) {
    setBusyId(`llm-${functionType}`)
    setError(null)
    try {
      setLlmModelConfig(await updateLlmModelAssignment(functionType, profileId))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setBusyId(null)
    }
  }

  async function handleLlmInstructionSave(functionType: string, clear = false) {
    const busyKey = `llm-instruction-`
    setBusyId(busyKey)
    setError(null)
    setNotice(null)
    try {
      const instructionText = clear ? "" : (llmInstructionDrafts[functionType] ?? "")
      const updated = await updateLlmFunctionInstruction(
        functionType, instructionText, instructionText.trim() !== "",
      )
      setLlmPersonalization((current) => current === null ? current : {
        functions: current.functions.map((item) =>
          item.function_type === functionType ? updated : item
        ),
      })
      setLlmInstructionDrafts((current) => ({ ...current, [functionType]: updated.instruction_text }))
      setNotice(t("settings.llmInstructionSaved"))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setBusyId(null)
    }
  }

  async function refreshLlmBlockedMails() {
    setLlmBlockFilters(await listLlmBlockFilters())
    setLlmBlockedMails(await listLlmBlockedMails())
  }

  async function handleApplyLlmBlockFilter(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusyId('llm-block-filter')
    setError(null)
    setNotice(null)
    try {
      const result = await applyMailLlmBlockFilter(
        llmBlockQuery,
        llmBlockReason.trim() === '' ? null : llmBlockReason,
      )
      setLlmBlockFilters((currentFilters) =>
        currentFilters === null ? [result.filter] : [result.filter, ...currentFilters],
      )
      setNotice(
        t('maintenance.debug.llmBlockApplied', {
          matched: result.matched,
          changed: result.changed,
        }),
      )
      await refreshLlmBlockedMails()
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setBusyId(null)
    }
  }

  async function handleToggleLlmBlockFilter(blockFilter: LlmBlockFilter) {
    setBusyId(`llm-block-filter-${blockFilter.id}`)
    setError(null)
    try {
      const updatedFilter = await updateLlmBlockFilter(
        blockFilter.id,
        !blockFilter.is_enabled,
      )
      setLlmBlockFilters((currentFilters) =>
        currentFilters === null
          ? [updatedFilter]
          : currentFilters.map((currentFilter) =>
              currentFilter.id === updatedFilter.id ? updatedFilter : currentFilter,
            ),
      )
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setBusyId(null)
    }
  }

  async function handleLlmCostSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusyId('llm-cost-settings')
    setError(null)
    try {
      const trimmedBudget = llmMonthlyBudget.trim()
      const monthlyBudget = trimmedBudget === '' ? null : Math.max(0, Number.parseFloat(trimmedBudget))
      const history = await updateLlmCostSettings(monthlyBudget)
      setLlmCostHistory(history)
      setLlmMonthlyBudget(history.monthly_budget === null ? '' : String(history.monthly_budget))
      setNotice(t('settings.saved'))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setBusyId(null)
    }
  }

  function handleLanguageChange(event: ChangeEvent<HTMLSelectElement>) {
    const value = event.target.value
    setUiLanguage(value === 'ja' ? 'ja' : 'en')
  }

  function handleLanguageSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    writeUiLanguage(uiLanguage)
    setNotice(t('settings.language.saved'))
    window.setTimeout(() => window.location.reload(), 120)
  }

  return (
    <main className="app-shell">
      <div className="maintenance-shell settings-shell">
        <header className="maintenance-header">
          <div>
            <p>{t('app.name')}</p>
            <h1>{t('settings.heading')}</h1>
          </div>
          <TopNav
            ariaLabelKey="settings.navigation"
            items={[
              { href: '/', labelKey: 'top.heading' },
              { href: '/maintenance', labelKey: 'nav.maintenance' },
              { href: '/logs', labelKey: 'nav.logs' },
              { href: '/profile', labelKey: 'nav.profile' },
            ]}
          />
        </header>

        {error !== null && <p className="maintenance-error" role="alert">{error}</p>}
        {notice !== null && <div className="mail-feedback"><p>{notice}</p></div>}

        <div className="maintenance-workspace">
          <div aria-label={t('settings.views')} className="maintenance-tabs" role="tablist">
            {settingsTabs.map((tab) => (
              <button
                aria-controls={`settings-${tab.key}-panel`}
                aria-selected={activeTab === tab.key}
                id={`settings-${tab.key}-tab`}
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                role="tab"
                type="button"
              >
                {t(tab.labelKey)}
              </button>
            ))}
          </div>

          <div className="maintenance-panel-surface">
            {activeTab === 'google' && (
              <section aria-labelledby="settings-google-tab" className="maintenance-panel maintenance-section" id="settings-google-panel" role="tabpanel">
                <div className="section-heading">
                  <h2>{t('settings.google.heading')}</h2>
                  <button className={`ui-button ui-button--compact button-loading-dot${busyId === 'google-refresh' ? ' is-loading' : ''}`} disabled={busyId !== null} onClick={refreshGoogleStatus} type="button">
                    {t('mail.refresh')}
                  </button>
                </div>
                {googleStatus === null ? (
                  <p>{t('maintenance.debug.loading')}</p>
                ) : (
                  <div className="settings-card-grid settings-google-grid">
                    <section className="mail-panel settings-google-connection">
                      <h3>{t('maintenance.debug.googleGmail')}</h3>
                      <dl className="settings-status-list">
                        <div><dt>{t('common.status')}</dt><dd>{googleStatus.connected ? t('maintenance.debug.googleGmailConnected') : googleStatus.configured ? t('maintenance.debug.googleGmailReady') : t('maintenance.debug.googleGmailNotConfigured')}</dd></div>
                        <div><dt>{t('maintenance.debug.googleGmailConnectedAt')}</dt><dd>{googleStatus.connected_at ?? t('common.none')}</dd></div>
                        <div><dt>{t('maintenance.debug.googleGmailScopes')}</dt><dd className="settings-scope-list">{googleStatus.scopes.join(', ')}</dd></div>
                      </dl>
                      <div className="settings-actions">
                        <button className={`button-loading-dot${busyId === 'google-connect' ? ' is-loading' : ''}`} disabled={busyId !== null || !googleStatus.configured} onClick={handleGoogleGmailConnect} type="button">{t('maintenance.debug.googleGmailConnect')}</button>
                        <button className={`button-loading-dot${busyId === 'google-disconnect' ? ' is-loading' : ''}`} disabled={busyId !== null || !googleStatus.connected} onClick={handleGoogleGmailDisconnect} type="button">{t('maintenance.debug.googleGmailDisconnect')}</button>
                      </div>
                    </section>

                    <section className="mail-panel settings-google-speed">
                      <div className="section-heading">
                        <div>
                          <h3>{t('maintenance.debug.googleSpeedTest')}</h3>
                          <p>{t('maintenance.debug.googleSpeedTestNote')}</p>
                        </div>
                        <button
                          className={`ui-button ui-button--compact button-loading-dot${busyId === 'google-speed-test' ? ' is-loading' : ''}`}
                          disabled={busyId !== null}
                          onClick={handleGoogleSpeedTest}
                          type="button"
                        >
                          {t('maintenance.debug.runGoogleSpeedTest')}
                        </button>
                      </div>
                      {googleSpeedTest === null ? (
                        <p className="maintenance-debug-muted">
                          {t('maintenance.debug.googleSpeedTestEmpty')}
                        </p>
                      ) : (
                        <>
                          <dl className="settings-status-list">
                            <div><dt>{t('maintenance.debug.googleSpeedTestStarted')}</dt><dd>{googleSpeedTest.started_at}</dd></div>
                            <div><dt>{t('maintenance.debug.googleSpeedTestTotal')}</dt><dd>{googleSpeedTest.total_ms} ms</dd></div>
                          </dl>
                          <div className="maintenance-table-wrap">
                            <table>
                              <thead>
                                <tr>
                                  <th scope="col">{t('maintenance.debug.step')}</th>
                                  <th scope="col">{t('common.status')}</th>
                                  <th scope="col">{t('maintenance.debug.duration')}</th>
                                  <th scope="col">{t('maintenance.debug.detail')}</th>
                                </tr>
                              </thead>
                              <tbody>
                                {googleSpeedTest.steps.map((step) => (
                                  <tr key={step.name}>
                                    <td>{step.name}</td>
                                    <td><span data-status={step.status}>{step.status}</span></td>
                                    <td>{step.duration_ms} ms</td>
                                    <td>{step.detail ?? t('common.none')}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </>
                      )}
                    </section>

                    <section className="mail-panel">
                      <h3>{t('maintenance.debug.googleGmailAutoImport')}</h3>
                      <form className="settings-form settings-google-form" onSubmit={handleGoogleGmailAutoImportSettings}>
                        <label className="checkbox-label"><input checked={gmailAutoImportEnabled} onChange={(event) => setGmailAutoImportEnabled(event.target.checked)} type="checkbox" /><span>{t('common.enabled')}</span></label>
                        <label><span>{t('maintenance.debug.googleGmailAutoImportInterval')}</span><input min={1} onChange={(event) => setGmailAutoImportInterval(event.target.value)} type="number" value={gmailAutoImportInterval} /></label>
                        <label><span>{t('maintenance.debug.googleGmailAutoImportMaxMessages')}</span><input max={100} min={1} onChange={(event) => setGmailAutoImportMaxMessages(event.target.value)} type="number" value={gmailAutoImportMaxMessages} /></label>
                        <button className={`button-loading-dot${busyId === 'gmail-auto-import' ? ' is-loading' : ''}`} disabled={busyId !== null} type="submit">{t('common.save')}</button>
                      </form>
                      <dl className="settings-status-list">
                        <div><dt>{t('maintenance.debug.googleGmailAutoImportLastRun')}</dt><dd>{googleStatus.auto_import.last_run_at ?? t('common.none')}</dd></div>
                        <div><dt>{t('maintenance.debug.googleGmailAutoImportLastImported')}</dt><dd>{googleStatus.auto_import.last_imported_count}</dd></div>
                        <div><dt>{t('maintenance.debug.googleGmailAutoImportLastError')}</dt><dd>{googleStatus.auto_import.last_error ?? t('common.none')}</dd></div>
                      </dl>
                    </section>

                    <section className="mail-panel">
                      <h3>{t('maintenance.debug.googleCalendarAutoSync')}</h3>
                      <form className="settings-form settings-google-form settings-calendar-form" onSubmit={handleGoogleCalendarAutoSyncSettings}>
                        <label className="checkbox-label"><input checked={calendarAutoSyncEnabled} onChange={(event) => setCalendarAutoSyncEnabled(event.target.checked)} type="checkbox" /><span>{t('common.enabled')}</span></label>
                        <label><span>{t('maintenance.debug.googleCalendarAutoSyncInterval')}</span><input min={5} onChange={(event) => setCalendarAutoSyncInterval(event.target.value)} type="number" value={calendarAutoSyncInterval} /></label>
                        <label><span>{t('maintenance.debug.googleCalendarAutoSyncMonthCount')}</span><input max={12} min={1} onChange={(event) => setCalendarAutoSyncMonthCount(event.target.value)} type="number" value={calendarAutoSyncMonthCount} /></label>
                        <button className={`button-loading-dot${busyId === 'calendar-auto-sync' ? ' is-loading' : ''}`} disabled={busyId !== null} type="submit">{t('common.save')}</button>
                      </form>
                      <dl className="settings-status-list">
                        <div><dt>{t('maintenance.debug.googleCalendarAutoSyncLastRun')}</dt><dd>{googleStatus.calendar_auto_sync.last_run_at ?? t('common.none')}</dd></div>
                        <div><dt>{t('maintenance.debug.googleCalendarAutoSyncLastSuccess')}</dt><dd>{googleStatus.calendar_auto_sync.last_success_at ?? t('common.none')}</dd></div>
                        <div><dt>{t('maintenance.debug.googleCalendarAutoSyncLastError')}</dt><dd>{googleStatus.calendar_auto_sync.last_error ?? t('common.none')}</dd></div>
                      </dl>
                    </section>
                  </div>
                )}
              </section>
            )}

            {activeTab === 'llm' && (
              <section aria-labelledby="settings-llm-tab" className="maintenance-panel maintenance-section" id="settings-llm-panel" role="tabpanel">
                <div className="section-heading"><h2>{t('maintenance.debug.llmModels')}</h2></div>
                <div className="maintenance-table-wrap">
                  <table>
                    <thead><tr><th>{t('maintenance.debug.llmFunction')}</th><th>{t('maintenance.debug.llmProfile')}</th><th>{t('maintenance.debug.llmModel')}</th><th>{t('maintenance.debug.llmApiKeyEnv')}</th></tr></thead>
                    <tbody>
                      {llmModelConfig === null && <tr><td colSpan={4}>{t('maintenance.debug.loading')}</td></tr>}
                      {llmModelConfig?.functions.map((functionConfig) => {
                        const selectedProfile = llmModelConfig.profiles.find((profile) => profile.id === functionConfig.profile_id) ?? null
                        return (
                          <tr key={functionConfig.function_type}>
                            <td><strong>{functionConfig.label}</strong><br /><small>{functionConfig.function_type}</small></td>
                            <td>
                              <select disabled={busyId !== null} onChange={(event) => handleLlmModelAssignment(functionConfig.function_type, event.target.value)} value={functionConfig.profile_id}>
                                <option value="mock">mock</option>
                                {llmModelConfig.profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.id}</option>)}
                              </select>
                            </td>
                            <td>{selectedProfile === null ? t('common.none') : `${selectedProfile.provider} / ${selectedProfile.model}`}</td>
                            <td>{selectedProfile?.api_key_env ?? selectedProfile?.endpoint_env ?? t('common.none')}</td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>

                <section className="maintenance-section" aria-labelledby="settings-llm-instructions-heading">
                  <div className="section-heading">
                    <div>
                      <h2 id="settings-llm-instructions-heading">{t("settings.llmInstructionsTitle")}</h2>
                      <p>{t("settings.llmInstructionsDescription")}</p>
                    </div>
                  </div>
                  <div className="settings-card-grid settings-llm-instruction-list">
                    {llmPersonalization === null && <p>{t("maintenance.debug.loading")}</p>}
                    {llmPersonalization?.functions.map((item) => (
                      <article className="mail-panel" key={item.function_type}>
                        <div className="section-heading">
                          <div><h3>{item.label}</h3><small>{item.function_type}</small></div>
                          {!item.is_available && (
                            <span className="status-chip">{t("settings.llmInstructionUnavailable")}</span>
                          )}
                          {item.source === "legacy_mail_standard_prompt" && (
                            <span className="status-chip">{t("settings.llmInstructionLegacy")}</span>
                          )}
                        </div>
                        <div className="settings-llm-instruction-editor">
                          <label className="settings-form settings-llm-instruction-form">
                          <span>{t("settings.llmInstructionLabel")}</span>
                          <textarea
                            ref={fitTextareaToContent}
                            onInput={(event) => fitTextareaToContent(event.currentTarget)}
                            onChange={(event) => setLlmInstructionDrafts((current) => ({
                              ...current, [item.function_type]: event.target.value,
                            }))}
                            disabled={!item.is_available}
                            placeholder={t("settings.llmInstructionPlaceholder")}
                            rows={1}
                            value={llmInstructionDrafts[item.function_type] ?? ""}
                          />
                        </label>
                        <div className="settings-actions">
                          <button
                            className={`button-loading-dot${busyId === `llm-instruction-${item.function_type}` ? " is-loading" : ""}`}
                            disabled={busyId !== null || !item.is_available}
                            onClick={() => handleLlmInstructionSave(item.function_type)}
                            type="button"
                          >{t("common.save")}</button>
                          <button
                            className="secondary-button"
                            disabled={busyId !== null || !item.is_available || (llmInstructionDrafts[item.function_type] ?? "").trim() === ""}
                            onClick={() => handleLlmInstructionSave(item.function_type, true)}
                            type="button"
                          >{t("common.clear")}</button>
                        </div>
                        </div>
                      </article>
                    ))}
                  </div>
                </section>

                <section
                  aria-labelledby="settings-llm-block-heading"
                  className="maintenance-section settings-llm-block-section"
                >
                  <div className="section-heading">
                    <h2 id="settings-llm-block-heading">
                      {t('maintenance.debug.llmBlock')}
                    </h2>
                    <button
                      className={`ui-button ui-button--compact button-loading-dot${busyId === 'llm-block-refresh' ? ' is-loading' : ''}`}
                      disabled={busyId !== null}
                      onClick={() => {
                        setBusyId('llm-block-refresh')
                        setError(null)
                        refreshLlmBlockedMails()
                          .catch((requestError) => setError(describeError(requestError)))
                          .finally(() => setBusyId(null))
                      }}
                      type="button"
                    >
                      {t('mail.refresh')}
                    </button>
                  </div>

                  <form className="settings-form settings-google-form" onSubmit={handleApplyLlmBlockFilter}>
                    <label>
                      <span>{t('maintenance.debug.llmBlockQuery')}</span>
                      <input
                        onChange={(event) => setLlmBlockQuery(event.target.value)}
                        required
                        value={llmBlockQuery}
                      />
                    </label>
                    <label>
                      <span>{t('maintenance.debug.llmBlockReason')}</span>
                      <input
                        onChange={(event) => setLlmBlockReason(event.target.value)}
                        value={llmBlockReason}
                      />
                    </label>
                    <button
                      className={`button-loading-dot${busyId === 'llm-block-filter' ? ' is-loading' : ''}`}
                      disabled={busyId !== null}
                      type="submit"
                    >
                      {t('maintenance.debug.applyLlmBlock')}
                    </button>
                  </form>

                  <div className="maintenance-table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th scope="col">{t('common.id')}</th>
                          <th scope="col">{t('maintenance.debug.llmBlockQuery')}</th>
                          <th scope="col">{t('maintenance.debug.reason')}</th>
                          <th scope="col">{t('common.status')}</th>
                          <th scope="col">{t('common.action')}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {llmBlockFilters === null && (
                          <tr>
                            <td colSpan={5}>{t('maintenance.debug.loading')}</td>
                          </tr>
                        )}
                        {llmBlockFilters?.map((blockFilter) => (
                          <tr key={blockFilter.id}>
                            <td>{blockFilter.id}</td>
                            <td>{blockFilter.query_text}</td>
                            <td>{blockFilter.reason}</td>
                            <td>
                              <span data-status={blockFilter.is_enabled ? 'enabled' : 'disabled'}>
                                {blockFilter.is_enabled
                                  ? t('common.enabled')
                                  : t('common.disabled')}
                              </span>
                            </td>
                            <td>
                              <button
                                className={`button-loading-dot${busyId === `llm-block-filter-${blockFilter.id}` ? ' is-loading' : ''}`}
                                disabled={busyId !== null}
                                onClick={() => handleToggleLlmBlockFilter(blockFilter)}
                                type="button"
                              >
                                {blockFilter.is_enabled
                                  ? t('common.disable')
                                  : t('common.enable')}
                              </button>
                            </td>
                          </tr>
                        ))}
                        {llmBlockFilters?.length === 0 && (
                          <tr>
                            <td colSpan={5}>{t('maintenance.debug.noLlmBlockFilters')}</td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>

                  <div className="maintenance-table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th scope="col">{t('common.id')}</th>
                          <th scope="col">{t('mail.from')}</th>
                          <th scope="col">{t('mail.subject')}</th>
                          <th scope="col">{t('maintenance.debug.reason')}</th>
                          <th scope="col">{t('maintenance.debug.blockedAt')}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {llmBlockedMails === null && (
                          <tr>
                            <td colSpan={5}>{t('maintenance.debug.loading')}</td>
                          </tr>
                        )}
                        {llmBlockedMails?.map((mail) => (
                          <tr key={mail.id}>
                            <td>{mail.id}</td>
                            <td>{mail.from_address}</td>
                            <td>{mail.subject ?? t('mail.noSubject')}</td>
                            <td>{mail.llm_block_reason ?? t('common.none')}</td>
                            <td>{mail.llm_blocked_at ?? t('common.none')}</td>
                          </tr>
                        ))}
                        {llmBlockedMails?.length === 0 && (
                          <tr>
                            <td colSpan={5}>{t('maintenance.debug.empty')}</td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </section>
              </section>
            )}

            {activeTab === 'language' && (
              <section aria-labelledby="settings-language-tab" className="maintenance-panel maintenance-section" id="settings-language-panel" role="tabpanel">
                <div className="section-heading">
                  <div>
                    <h2>{t('settings.language.heading')}</h2>
                    <p>{t('settings.language.description')}</p>
                  </div>
                </div>
                <form className="settings-form settings-google-form" onSubmit={handleLanguageSettings}>
                  <label>
                    <span>{t('settings.language.label')}</span>
                    <select onChange={handleLanguageChange} value={uiLanguage}>
                      <option value="en">{t('settings.language.english')}</option>
                      <option value="ja">{t('settings.language.japanese')}</option>
                    </select>
                  </label>
                  <button disabled={busyId !== null} type="submit">{t('common.save')}</button>
                </form>
              </section>
            )}

            {activeTab === 'budget' && (
              <section aria-labelledby="settings-budget-tab" className="maintenance-panel maintenance-section" id="settings-budget-panel" role="tabpanel">
                <div className="section-heading"><h2>{t('settings.budget.heading')}</h2></div>
                {llmCostHistory === null ? <p>{t('maintenance.debug.loading')}</p> : (
                  <>
                    <div className="llm-cost-summary-grid">
                      <div><span>{t('maintenance.llmCost.remaining')}</span><strong>{formatMoney(llmCostHistory.month_remaining, llmCostHistory.currency)}</strong></div>
                      <div><span>{t('maintenance.llmCost.monthUsed')}</span><strong>{formatMoney(llmCostHistory.month_used, llmCostHistory.currency)}</strong></div>
                      <div><span>{t('maintenance.llmCost.todayUsed')}</span><strong>{formatMoney(llmCostHistory.today_used, llmCostHistory.currency)}</strong></div>
                      <div><span>{t('maintenance.llmCost.totalUsed')}</span><strong>{formatMoney(llmCostHistory.total_used, llmCostHistory.currency)}</strong></div>
                    </div>
                    <form className="llm-cost-budget-form" onSubmit={handleLlmCostSettings}>
                      <label><span>{t('maintenance.llmCost.monthlyBudget')}</span><input min={0} onChange={(event) => setLlmMonthlyBudget(event.target.value)} placeholder={t('maintenance.llmCost.noBudget')} step="0.01" type="number" value={llmMonthlyBudget} /></label>
                      <button className={`button-loading-dot${busyId === 'llm-cost-settings' ? ' is-loading' : ''}`} disabled={busyId !== null} type="submit">{t('common.save')}</button>
                    </form>
                  </>
                )}
              </section>
            )}
          </div>
        </div>
      </div>
    </main>
  )
}

export default SettingsView
