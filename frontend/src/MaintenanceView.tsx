import { Fragment, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { t } from './i18n'
import type { MessageKey } from './i18n'
import { AppLink } from './navigation'
import {
  listExternalOperations,
  listJobs,
  listPendingMails,
  readMaintenanceStatus,
  resolveExternalOperation,
  retryJob,
} from './phase2Api'
import type {
  ExternalOperation,
  Job,
  MaintenanceStatus,
  PendingMail,
} from './phase2Api'
import {
  applyMailLlmBlockFilter,
  createGoogleGmailConnectUrl,
  disconnectGoogleGmail,
  getGoogleGmailStatus,
  getLlmModelConfig,
  importLatestUnloadedGoogleGmail,
  listLlmBlockFilters,
  listLlmBlockedMails,
  listMailSendRequests,
  updateLlmBlockFilter,
  updateLlmModelAssignment,
} from './phase4Api'
import type {
  GoogleGmailStatus,
  LlmBlockFilter,
  LlmBlockedMail,
  LlmModelConfig,
  MailSendRequest,
} from './phase4Api'

const usageMetrics = [
  { key: 'database', labelKey: 'maintenance.metric.database' },
  { key: 'storage', labelKey: 'maintenance.metric.storage' },
  { key: 'llm-cost', labelKey: 'maintenance.metric.llmCost' },
  { key: 'metric-4', labelKey: 'maintenance.metric.metric4' },
  { key: 'metric-5', labelKey: 'maintenance.metric.metric5' },
  { key: 'metric-6', labelKey: 'maintenance.metric.metric6' },
  {
    key: 'running-jobs',
    labelKey: 'maintenance.metric.runningJobs',
    statusKey: 'running_jobs',
  },
  {
    key: 'pending-write-requests',
    labelKey: 'maintenance.metric.pendingWriteRequests',
    statusKey: 'pending_write_requests',
  },
  {
    key: 'external-unknown',
    labelKey: 'maintenance.metric.externalUnknown',
    statusKey: 'external_unknown_count',
  },
] satisfies Array<{
  key: string
  labelKey: MessageKey
  statusKey?: keyof MaintenanceStatus
}>

const usageHistoryRanges = [
  {
    key: '24h',
    label: '24h',
    axisLabelKeys: [
      'maintenance.history.24hAgo',
      'maintenance.history.18h',
      'maintenance.history.12h',
      'maintenance.history.6h',
      'maintenance.history.now',
    ],
  },
  {
    key: '7d',
    label: '7d',
    axisLabelKeys: [
      'maintenance.history.7dAgo',
      'maintenance.history.5d',
      'maintenance.history.3d',
      'maintenance.history.1d',
      'maintenance.history.now',
    ],
  },
  {
    key: '30d',
    label: '30d',
    axisLabelKeys: [
      'maintenance.history.30dAgo',
      'maintenance.history.21d',
      'maintenance.history.14d',
      'maintenance.history.7d',
      'maintenance.history.now',
    ],
  },
] satisfies Array<{
  key: string
  label: string
  axisLabelKeys: MessageKey[]
}>

type MaintenanceTab = 'usage' | 'jobs' | 'debug'
type UsageMetric = (typeof usageMetrics)[number]
type UsageHistoryRange = (typeof usageHistoryRanges)[number]

export type MaintenanceInitialData = {
  status: MaintenanceStatus
  jobs: Job[]
  operations: ExternalOperation[]
  pendingMails: PendingMail[]
}

function updateById<T extends { id: string }>(items: T[], updated: T) {
  return items.map((item) => (item.id === updated.id ? updated : item))
}

function describeError(error: unknown) {
  return error instanceof Error ? error.message : t('maintenance.requestFailed')
}

function countRequiredActions(
  jobs: Job[],
  operations: ExternalOperation[],
) {
  return (
    jobs.filter(jobNeedsAction).length +
    operations.filter((operation) => operation.status === 'unknown').length
  )
}

function jobNeedsAction(job: Job) {
  return job.status === 'failed' || job.status === 'stale'
}

function usageMetricValue(metric: UsageMetric, status: MaintenanceStatus | null) {
  return metric.statusKey === undefined
    ? t('maintenance.notAvailable')
    : status?.[metric.statusKey] ?? t('common.none')
}

function jobStatusDetail(job: Job) {
  const reason = [job.error_type, job.error_message].filter(Boolean).join(' - ')
  if (job.status === 'failed') {
    return reason === ''
      ? 'The job failed. No detailed failure reason was recorded.'
      : `The job failed. Reason: ${reason}`
  }

  if (job.status === 'pending') {
    return 'The job is waiting for a worker.'
  }
  if (job.status === 'running') {
    return 'A worker is running this job.'
  }
  if (job.status === 'succeeded') {
    return 'The job completed successfully.'
  }
  if (job.status === 'stale') {
    return 'The running heartbeat is stale, so this job needs manual confirmation.'
  }

  return `The job is in ${job.status} status.`
}

function externalOperationStatusDetail(operation: ExternalOperation) {
  if (operation.status === 'unknown') {
    return operation.unknown_reason === null
      ? 'The external operation result could not be confirmed automatically. Please check the external service manually.'
      : `The external operation result could not be confirmed automatically. Reason: ${operation.unknown_reason}`
  }

  if (operation.status === 'pending') {
    return 'The external operation is waiting to run.'
  }
  if (operation.status === 'running') {
    return 'The external service operation is running.'
  }
  if (operation.status === 'succeeded') {
    return 'The external operation is recorded as succeeded.'
  }
  if (operation.status === 'failed') {
    return 'The external operation is recorded as failed.'
  }
  if (operation.status === 'canceled') {
    return 'The external operation is recorded as canceled.'
  }

  return `The external operation is in ${operation.status} status.`
}

function initialMaintenanceTab(): MaintenanceTab {
  return new URLSearchParams(window.location.search).has('google_gmail')
    ? 'debug'
    : 'usage'
}

function initialDebugNotice() {
  const status = new URLSearchParams(window.location.search).get('google_gmail')
  if (status === 'connected') {
    return t('maintenance.debug.googleGmailConnectedNotice')
  }
  if (status === 'error') {
    return t('maintenance.debug.googleGmailErrorNotice')
  }
  return null
}

function MaintenanceView({ initialData }: { initialData?: MaintenanceInitialData }) {
  const [status, setStatus] = useState<MaintenanceStatus | null>(
    initialData?.status ?? null,
  )
  const [jobs, setJobs] = useState<Job[]>(initialData?.jobs ?? [])
  const [operations, setOperations] = useState<ExternalOperation[]>(
    initialData?.operations ?? [],
  )
  const [pendingMails, setPendingMails] = useState<PendingMail[]>(
    initialData?.pendingMails ?? [],
  )
  const [sendRequests, setSendRequests] = useState<MailSendRequest[] | null>(null)
  const [llmModelConfig, setLlmModelConfig] = useState<LlmModelConfig | null>(null)
  const [googleGmailStatus, setGoogleGmailStatus] =
    useState<GoogleGmailStatus | null>(null)
  const [llmBlockFilters, setLlmBlockFilters] = useState<LlmBlockFilter[] | null>(null)
  const [llmBlockedMails, setLlmBlockedMails] = useState<LlmBlockedMail[] | null>(null)
  const [debugNotice, setDebugNotice] = useState<string | null>(initialDebugNotice)
  const [llmBlockQuery, setLlmBlockQuery] = useState('password')
  const [llmBlockReason, setLlmBlockReason] = useState('May contain password.')
  const [isDebugBusy, setIsDebugBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<MaintenanceTab>(initialMaintenanceTab)
  const [activeUsageMetric, setActiveUsageMetric] =
    useState<UsageMetric>(usageMetrics[0])
  const [activeUsageHistoryRange, setActiveUsageHistoryRange] =
    useState<UsageHistoryRange>(usageHistoryRanges[0])
  const actionJobs = jobs.filter(jobNeedsAction)
  const requiredActionCount = countRequiredActions(jobs, operations)
  const requiredActionLabel = requiredActionCount > 9 ? '9+' : requiredActionCount

  useEffect(() => {
    if (initialData !== undefined) {
      return
    }
    let isMounted = true

    Promise.all([
      readMaintenanceStatus(),
      listJobs(),
      listExternalOperations(),
      listPendingMails(),
    ])
      .then(([nextStatus, nextJobs, nextOperations, nextPendingMails]) => {
        if (!isMounted) {
          return
        }
        setStatus(nextStatus)
        setJobs(nextJobs)
        setOperations(nextOperations)
        setPendingMails(nextPendingMails)
      })
      .catch((requestError) => {
        if (isMounted) {
          setError(describeError(requestError))
        }
      })

    return () => {
      isMounted = false
    }
  }, [initialData])

  useEffect(() => {
    if (activeTab !== 'debug' || sendRequests !== null) {
      return
    }

    let isMounted = true
    listMailSendRequests()
      .then((nextSendRequests) => {
        if (isMounted) {
          setSendRequests(nextSendRequests)
        }
      })
      .catch((requestError) => {
        if (isMounted) {
          setError(describeError(requestError))
          setSendRequests([])
        }
      })

    return () => {
      isMounted = false
    }
  }, [activeTab, sendRequests])

  useEffect(() => {
    if (
      activeTab !== 'debug' ||
      (llmBlockedMails !== null && llmBlockFilters !== null && llmModelConfig !== null)
    ) {
      return
    }

    let isMounted = true
    Promise.all([getLlmModelConfig(), listLlmBlockFilters(), listLlmBlockedMails()])
      .then(([nextModelConfig, nextFilters, nextMails]) => {
        if (isMounted) {
          setLlmModelConfig(nextModelConfig)
          setLlmBlockFilters(nextFilters)
          setLlmBlockedMails(nextMails)
        }
      })
      .catch((requestError) => {
        if (isMounted) {
          setError(describeError(requestError))
          setLlmModelConfig({ profiles: [], functions: [] })
          setLlmBlockFilters([])
          setLlmBlockedMails([])
        }
      })

    return () => {
      isMounted = false
    }
  }, [activeTab, llmBlockedMails, llmBlockFilters, llmModelConfig])

  useEffect(() => {
    if (activeTab !== 'debug' || googleGmailStatus !== null) {
      return
    }

    let isMounted = true
    getGoogleGmailStatus()
      .then((nextStatus) => {
        if (isMounted) {
          setGoogleGmailStatus(nextStatus)
        }
      })
      .catch((requestError) => {
        if (isMounted) {
          setError(describeError(requestError))
        }
      })

    return () => {
      isMounted = false
    }
  }, [activeTab, googleGmailStatus])

  async function handleRetry(job: Job) {
    setBusyId(job.id)
    setError(null)
    try {
      setJobs(updateById(jobs, await retryJob(job.id)))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setBusyId(null)
    }
  }

  async function handleResolve(
    operation: ExternalOperation,
    resolution: 'mark_succeeded' | 'mark_failed' | 'mark_canceled',
  ) {
    setBusyId(operation.id)
    setError(null)
    try {
      setOperations(
        updateById(
          operations,
          await resolveExternalOperation(operation.id, resolution),
        ),
      )
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setBusyId(null)
    }
  }

  async function refreshSendRequests() {
    setSendRequests(await listMailSendRequests())
  }

  async function refreshLlmBlockedMails() {
    setLlmModelConfig(await getLlmModelConfig())
    setLlmBlockFilters(await listLlmBlockFilters())
    setLlmBlockedMails(await listLlmBlockedMails())
  }

  async function refreshGoogleGmailStatus() {
    setGoogleGmailStatus(await getGoogleGmailStatus())
  }

  async function handleGoogleGmailConnect() {
    setError(null)
    setDebugNotice(null)
    setIsDebugBusy(true)
    try {
      const result = await createGoogleGmailConnectUrl()
      window.location.href = result.authorization_url
    } catch (requestError) {
      setError(describeError(requestError))
      setIsDebugBusy(false)
    }
  }

  async function handleGoogleGmailDisconnect() {
    setError(null)
    setDebugNotice(null)
    setIsDebugBusy(true)
    try {
      setGoogleGmailStatus(await disconnectGoogleGmail())
      setDebugNotice(t('maintenance.debug.googleGmailDisconnected'))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsDebugBusy(false)
    }
  }

  async function handleGoogleGmailImportLatest() {
    setError(null)
    setDebugNotice(null)
    setIsDebugBusy(true)
    try {
      const result = await importLatestUnloadedGoogleGmail()
      if (!result.imported || result.mail === null) {
        setDebugNotice(t('maintenance.debug.googleGmailImportNone'))
        return
      }
      setDebugNotice(
        t('maintenance.debug.googleGmailImported', {
          subject: result.subject ?? result.mail.gmail_message_id,
          pending: result.mail.pending ? 'yes' : 'no',
          jobId: result.mail.queued_job_id ?? '-',
        }),
      )
      await Promise.all([
        refreshGoogleGmailStatus(),
        refreshLlmBlockedMails(),
        readMaintenanceStatus().then(setStatus),
        listJobs().then(setJobs),
        listPendingMails().then(setPendingMails),
      ])
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsDebugBusy(false)
    }
  }

  async function handleApplyLlmBlockFilter(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setDebugNotice(null)
    setIsDebugBusy(true)
    try {
      const result = await applyMailLlmBlockFilter(
        llmBlockQuery,
        llmBlockReason.trim() === '' ? null : llmBlockReason,
      )
      setLlmBlockFilters((currentFilters) =>
        currentFilters === null ? [result.filter] : [result.filter, ...currentFilters],
      )
      setDebugNotice(
        t('maintenance.debug.llmBlockApplied', {
          matched: result.matched,
          changed: result.changed,
        }),
      )
      await refreshLlmBlockedMails()
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsDebugBusy(false)
    }
  }

  async function handleToggleLlmBlockFilter(blockFilter: LlmBlockFilter) {
    setError(null)
    setIsDebugBusy(true)
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
      setIsDebugBusy(false)
    }
  }

  async function handleLlmModelAssignment(functionType: string, profileId: string) {
    setError(null)
    setIsDebugBusy(true)
    try {
      setLlmModelConfig(await updateLlmModelAssignment(functionType, profileId))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsDebugBusy(false)
    }
  }

  return (
    <main className="app-shell">
      <div className="maintenance-shell">
        <header className="maintenance-header">
          <div>
            <p>{t('app.name')}</p>
            <h1>{t('maintenance.heading')}</h1>
          </div>
          <AppLink href="/">{t('top.heading')}</AppLink>
        </header>

        {error !== null && (
          <p className="maintenance-error" role="alert">
            {error}
          </p>
        )}

        <div className="maintenance-workspace">
          <div
            aria-label={t('maintenance.views')}
            className="maintenance-tabs"
            role="tablist"
          >
            <button
              aria-controls="maintenance-usage-panel"
              aria-selected={activeTab === 'usage'}
              id="maintenance-usage-tab"
              onClick={() => setActiveTab('usage')}
              role="tab"
              type="button"
            >
              {t('maintenance.usage')}
            </button>
            <button
              aria-controls="maintenance-jobs-panel"
              aria-selected={activeTab === 'jobs'}
              id="maintenance-jobs-tab"
              onClick={() => setActiveTab('jobs')}
              role="tab"
              type="button"
            >
              <span>{t('maintenance.needsAction')}</span>
              <span
                aria-label={t('maintenance.actionsRequired', {
                  count: requiredActionCount,
                })}
                className="maintenance-action-count"
              >
                {requiredActionLabel}
              </span>
            </button>
            <button
              aria-controls="maintenance-debug-panel"
              aria-selected={activeTab === 'debug'}
              id="maintenance-debug-tab"
              onClick={() => setActiveTab('debug')}
              role="tab"
              type="button"
            >
              {t('maintenance.debug')}
            </button>
          </div>

          <div className="maintenance-panel-surface">
            {activeTab === 'usage' && (
              <section
                aria-labelledby="maintenance-usage-tab usage-heading"
                className="maintenance-panel maintenance-section"
                id="maintenance-usage-panel"
                role="tabpanel"
              >
                <div className="section-heading">
                  <h2 id="usage-heading">{t('maintenance.usage')}</h2>
                </div>

                <div className="usage-grid">
                  {usageMetrics.map((metric) => (
                    <button
                      aria-pressed={activeUsageMetric.key === metric.key}
                      className="usage-metric"
                      key={metric.key}
                      onClick={() => setActiveUsageMetric(metric)}
                      type="button"
                    >
                      <p>{t(metric.labelKey)}</p>
                      <strong>{usageMetricValue(metric, status)}</strong>
                    </button>
                  ))}
                </div>

                <section
                  aria-labelledby="usage-history-heading"
                  className="usage-history"
                >
                  <div className="section-heading">
                    <h3 id="usage-history-heading">
                      {t('maintenance.history.heading', {
                        metric: t(activeUsageMetric.labelKey),
                      })}
                    </h3>
                    <div
                      aria-label={t('maintenance.history.range')}
                      className="usage-history-ranges"
                      role="group"
                    >
                      {usageHistoryRanges.map((range) => (
                        <button
                          aria-pressed={activeUsageHistoryRange.key === range.key}
                          key={range.key}
                          onClick={() => setActiveUsageHistoryRange(range)}
                          type="button"
                        >
                          {range.label}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="usage-history-chart">
                    <div
                      aria-label={t('maintenance.history.scale')}
                      className="usage-history-y-axis"
                    >
                      <span>{t('maintenance.history.high')}</span>
                      <span>{t('maintenance.history.mid')}</span>
                      <span>{t('maintenance.history.low')}</span>
                      <span>0</span>
                    </div>
                    <div aria-hidden="true" className="usage-history-plot">
                      <span />
                      <span />
                      <span />
                      <span />
                    </div>
                    <span aria-hidden="true" className="usage-history-axis-gutter" />
                    <div className="usage-history-axis">
                      {activeUsageHistoryRange.axisLabelKeys.map((labelKey) => (
                        <span key={labelKey}>{t(labelKey)}</span>
                      ))}
                    </div>
                  </div>
                  <p>{t('maintenance.history.noHistory')}</p>
                </section>
              </section>
            )}

            {activeTab === 'jobs' && (
              <div
                aria-labelledby="maintenance-jobs-tab"
                className="maintenance-panel"
                id="maintenance-jobs-panel"
                role="tabpanel"
              >
                <section
                  aria-labelledby="jobs-heading"
                  className="maintenance-section"
                >
                  <div className="section-heading">
                    <h2 id="jobs-heading">{t('maintenance.jobs.heading')}</h2>
                    <p>
                      {status?.job_accepting === false
                        ? t('maintenance.jobs.paused')
                        : t('maintenance.jobs.accepting')}
                    </p>
                  </div>

                  <div className="maintenance-table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th scope="col">{t('common.id')}</th>
                          <th scope="col">{t('common.type')}</th>
                          <th scope="col">{t('common.status')}</th>
                          <th scope="col">{t('common.retry')}</th>
                          <th scope="col">{t('common.action')}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {actionJobs.map((job) => (
                          <Fragment key={job.id}>
                            <tr>
                              <td>{job.id}</td>
                              <td>{job.job_type}</td>
                              <td>
                                <span data-status={job.status}>{job.status}</span>
                              </td>
                              <td>
                                {job.retry_count}/{job.max_retries}
                              </td>
                              <td>
                                {job.status === 'failed' ? (
                                  <button
                                    aria-label={t('maintenance.jobs.retryFor', {
                                      id: job.id,
                                    })}
                                    disabled={busyId === job.id}
                                    onClick={() => handleRetry(job)}
                                    title={t('maintenance.jobs.retryTitle')}
                                    type="button"
                                  >
                                    {t('maintenance.jobs.retry')}
                                  </button>
                                ) : (
                                  <span className="quiet-cell">
                                    {t('common.none')}
                                  </span>
                                )}
                              </td>
                            </tr>
                            <tr className="maintenance-detail-row">
                              <td colSpan={5}>{jobStatusDetail(job)}</td>
                            </tr>
                          </Fragment>
                        ))}
                        {actionJobs.length === 0 && (
                          <tr>
                            <td colSpan={5}>{t('maintenance.jobs.empty')}</td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </section>

                <section
                  aria-labelledby="external-operations-heading"
                  className="maintenance-section"
                >
                  <div className="section-heading">
                    <h2 id="external-operations-heading">
                      {t('maintenance.external.heading')}
                    </h2>
                  </div>

                  <div className="maintenance-table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th scope="col">{t('common.id')}</th>
                          <th scope="col">{t('common.type')}</th>
                          <th scope="col">{t('common.service')}</th>
                          <th scope="col">{t('common.status')}</th>
                          <th scope="col">{t('common.resolution')}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {operations.map((operation) => (
                          <Fragment key={operation.id}>
                            <tr>
                              <td>{operation.id}</td>
                              <td>{operation.operation_type}</td>
                              <td>{operation.external_service}</td>
                              <td>
                                <span data-status={operation.status}>
                                  {operation.status}
                                </span>
                              </td>
                              <td>
                                {operation.status === 'unknown' ? (
                                  <div className="resolution-actions">
                                    <button
                                      aria-label={t(
                                        'maintenance.external.markSucceeded',
                                        { id: operation.id },
                                      )}
                                      disabled={busyId === operation.id}
                                      onClick={() =>
                                        handleResolve(operation, 'mark_succeeded')
                                      }
                                      title={t(
                                        'maintenance.external.succeededTitle',
                                      )}
                                      type="button"
                                    >
                                      {t('maintenance.external.succeeded')}
                                    </button>
                                    <button
                                      aria-label={t(
                                        'maintenance.external.markFailed',
                                        { id: operation.id },
                                      )}
                                      disabled={busyId === operation.id}
                                      onClick={() =>
                                        handleResolve(operation, 'mark_failed')
                                      }
                                      title={t('maintenance.external.failedTitle')}
                                      type="button"
                                    >
                                      {t('maintenance.external.failed')}
                                    </button>
                                    <button
                                      aria-label={t('maintenance.external.cancelFor', {
                                        id: operation.id,
                                      })}
                                      disabled={busyId === operation.id}
                                      onClick={() =>
                                        handleResolve(operation, 'mark_canceled')
                                      }
                                      title={t('maintenance.external.cancelTitle')}
                                      type="button"
                                    >
                                      {t('maintenance.external.cancel')}
                                    </button>
                                  </div>
                                ) : (
                                  <span className="quiet-cell">
                                    {t('common.none')}
                                  </span>
                                )}
                              </td>
                            </tr>
                            <tr className="maintenance-detail-row">
                              <td colSpan={5}>
                                {externalOperationStatusDetail(operation)}
                              </td>
                            </tr>
                          </Fragment>
                        ))}
                        {operations.length === 0 && (
                          <tr>
                            <td colSpan={5}>
                              {t('maintenance.external.empty')}
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </section>

                <section
                  aria-labelledby="pending-mails-heading"
                  className="maintenance-section"
                >
                  <div className="section-heading">
                    <h2 id="pending-mails-heading">
                      {t('maintenance.pendingMails.heading')}
                    </h2>
                    <p>{t('maintenance.pendingMails.note')}</p>
                  </div>

                  <div className="maintenance-table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th scope="col">{t('common.id')}</th>
                          <th scope="col">{t('mail.date')}</th>
                          <th scope="col">{t('mail.subject')}</th>
                          <th scope="col">{t('mail.from')}</th>
                          <th scope="col">{t('mail.pendingReason')}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {pendingMails.map((mail) => (
                          <Fragment key={mail.id}>
                            <tr>
                              <td>{mail.id}</td>
                              <td>{mail.received_at}</td>
                              <td>{mail.subject ?? t('mail.noSubject')}</td>
                              <td>{mail.from_address}</td>
                              <td>
                                <span data-status="pending">
                                  {mail.pending_reason ?? t('common.none')}
                                </span>
                              </td>
                            </tr>
                            <tr className="maintenance-detail-row">
                              <td colSpan={5}>
                                {t('maintenance.pendingMails.detail')}
                              </td>
                            </tr>
                          </Fragment>
                        ))}
                        {pendingMails.length === 0 && (
                          <tr>
                            <td colSpan={5}>
                              {t('maintenance.pendingMails.empty')}
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </section>
              </div>
            )}

            {activeTab === 'debug' && (
              <section
                aria-labelledby="maintenance-debug-tab debug-heading"
                className="maintenance-panel maintenance-section"
                id="maintenance-debug-panel"
                role="tabpanel"
              >
                <div className="section-heading">
                  <h2 id="debug-heading">{t('maintenance.debug')}</h2>
                  <p>{t('maintenance.debug.note')}</p>
                </div>

                {debugNotice !== null && (
                  <div className="mail-feedback">
                    <p>{debugNotice}</p>
                  </div>
                )}

                <section
                  aria-labelledby="maintenance-debug-tools-heading"
                  className="mail-panel mail-dev-panel"
                >
                  <div className="section-heading">
                    <h3 id="maintenance-debug-tools-heading">
                      {t('mail.debug.heading')}
                    </h3>
                  </div>
                </section>

                <section
                  aria-labelledby="maintenance-google-gmail-heading"
                  className="maintenance-section"
                >
                  <div className="section-heading">
                    <h3 id="maintenance-google-gmail-heading">
                      {t('maintenance.debug.googleGmail')}
                    </h3>
                    <button
                      disabled={isDebugBusy}
                      onClick={() => {
                        void refreshGoogleGmailStatus()
                      }}
                      type="button"
                    >
                      {t('mail.refresh')}
                    </button>
                  </div>

                  <div className="google-gmail-panel">
                    {googleGmailStatus === null ? (
                      <p>{t('maintenance.debug.loading')}</p>
                    ) : (
                      <>
                        <dl>
                          <div>
                            <dt>{t('common.status')}</dt>
                            <dd>
                              <span
                                data-status={
                                  googleGmailStatus.connected
                                    ? 'succeeded'
                                    : googleGmailStatus.configured
                                      ? 'pending'
                                      : 'failed'
                                }
                              >
                                {googleGmailStatus.connected
                                  ? t('maintenance.debug.googleGmailConnected')
                                  : googleGmailStatus.configured
                                    ? t('maintenance.debug.googleGmailReady')
                                    : t('maintenance.debug.googleGmailNotConfigured')}
                              </span>
                            </dd>
                          </div>
                          <div>
                            <dt>{t('maintenance.debug.googleGmailMailLoad')}</dt>
                            <dd>{t('maintenance.debug.googleGmailMailLoadOff')}</dd>
                          </div>
                          <div>
                            <dt>{t('maintenance.debug.googleGmailConnectedAt')}</dt>
                            <dd>{googleGmailStatus.connected_at ?? t('common.none')}</dd>
                          </div>
                          <div>
                            <dt>{t('maintenance.debug.googleGmailScopes')}</dt>
                            <dd>{googleGmailStatus.scopes.join(', ')}</dd>
                          </div>
                          <div>
                            <dt>{t('maintenance.debug.googleGmailRedirectUri')}</dt>
                            <dd>{googleGmailStatus.redirect_uri}</dd>
                          </div>
                        </dl>
                        {googleGmailStatus.last_error !== null && (
                          <p role="alert">{googleGmailStatus.last_error}</p>
                        )}
                        <div className="mail-actions mail-debug-actions">
                          <button
                            disabled={isDebugBusy || !googleGmailStatus.configured}
                            onClick={handleGoogleGmailConnect}
                            type="button"
                          >
                            {t('maintenance.debug.googleGmailConnect')}
                          </button>
                          <button
                            disabled={isDebugBusy || !googleGmailStatus.connected}
                            onClick={handleGoogleGmailDisconnect}
                            type="button"
                          >
                            {t('maintenance.debug.googleGmailDisconnect')}
                          </button>
                          <button
                            disabled={isDebugBusy || !googleGmailStatus.connected}
                            onClick={handleGoogleGmailImportLatest}
                            type="button"
                          >
                            {t('maintenance.debug.googleGmailImportLatest')}
                          </button>
                        </div>
                      </>
                    )}
                  </div>
                </section>

                <section
                  aria-labelledby="maintenance-llm-model-heading"
                  className="maintenance-section"
                >
                  <div className="section-heading">
                    <h3 id="maintenance-llm-model-heading">
                      {t('maintenance.debug.llmModels')}
                    </h3>
                    <button
                      disabled={isDebugBusy}
                      onClick={() => {
                        void getLlmModelConfig().then(setLlmModelConfig)
                      }}
                      type="button"
                    >
                      {t('mail.refresh')}
                    </button>
                  </div>

                  <div className="maintenance-table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th scope="col">{t('maintenance.debug.llmFunction')}</th>
                          <th scope="col">{t('maintenance.debug.llmProfile')}</th>
                          <th scope="col">{t('maintenance.debug.llmModel')}</th>
                          <th scope="col">{t('maintenance.debug.llmApiKeyEnv')}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {llmModelConfig === null && (
                          <tr>
                            <td colSpan={4}>{t('maintenance.debug.loading')}</td>
                          </tr>
                        )}
                        {llmModelConfig?.functions.map((functionConfig) => {
                          const selectedProfile =
                            llmModelConfig.profiles.find(
                              (profile) => profile.id === functionConfig.profile_id,
                            ) ?? null
                          return (
                            <tr key={functionConfig.function_type}>
                              <td>{functionConfig.function_type}</td>
                              <td>
                                <select
                                  aria-label={t('maintenance.debug.llmProfileFor', {
                                    functionType: functionConfig.function_type,
                                  })}
                                  disabled={isDebugBusy}
                                  onChange={(event) =>
                                    handleLlmModelAssignment(
                                      functionConfig.function_type,
                                      event.target.value,
                                    )
                                  }
                                  value={functionConfig.profile_id}
                                >
                                  <option value="mock">mock</option>
                                  {llmModelConfig.profiles.map((profile) => (
                                    <option key={profile.id} value={profile.id}>
                                      {profile.id}
                                    </option>
                                  ))}
                                </select>
                              </td>
                              <td>
                                {selectedProfile === null
                                  ? t('common.none')
                                  : `${selectedProfile.provider} / ${selectedProfile.model}`}
                              </td>
                              <td>
                                {selectedProfile?.api_key_env ??
                                  selectedProfile?.endpoint_env ??
                                  t('common.none')}
                              </td>
                            </tr>
                          )
                        })}
                        {llmModelConfig?.functions.length === 0 && (
                          <tr>
                            <td colSpan={4}>{t('maintenance.debug.empty')}</td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </section>

                <section
                  aria-labelledby="maintenance-llm-block-heading"
                  className="maintenance-section"
                >
                  <div className="section-heading">
                    <h3 id="maintenance-llm-block-heading">
                      {t('maintenance.debug.llmBlock')}
                    </h3>
                    <button
                      disabled={isDebugBusy}
                      onClick={() => {
                        void refreshLlmBlockedMails()
                      }}
                      type="button"
                    >
                      {t('mail.refresh')}
                    </button>
                  </div>

                  <form className="mail-mock-form" onSubmit={handleApplyLlmBlockFilter}>
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
                    <button disabled={isDebugBusy} type="submit">
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
                                disabled={isDebugBusy}
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

                <section
                  aria-labelledby="maintenance-send-requests-heading"
                  className="maintenance-section"
                >
                  <div className="section-heading">
                    <h3 id="maintenance-send-requests-heading">
                      {t('maintenance.debug.sendRequests')}
                    </h3>
                    <button
                      disabled={isDebugBusy}
                      onClick={() => {
                        void refreshSendRequests()
                      }}
                      type="button"
                    >
                      {t('mail.refresh')}
                    </button>
                  </div>

                <div className="maintenance-table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th scope="col">{t('common.id')}</th>
                        <th scope="col">{t('common.status')}</th>
                        <th scope="col">{t('maintenance.debug.to')}</th>
                        <th scope="col">{t('mail.subject')}</th>
                        <th scope="col">{t('maintenance.debug.attachments')}</th>
                        <th scope="col">{t('maintenance.debug.createdAt')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sendRequests === null && (
                        <tr>
                          <td colSpan={6}>{t('maintenance.debug.loading')}</td>
                        </tr>
                      )}
                      {sendRequests?.map((sendRequest) => (
                        <Fragment key={sendRequest.id}>
                          <tr>
                            <td>{sendRequest.id}</td>
                            <td>
                              <span data-status={sendRequest.status}>
                                {sendRequest.status}
                              </span>
                            </td>
                            <td>{sendRequest.to_addresses.join(', ')}</td>
                            <td>{sendRequest.subject ?? t('mail.noSubject')}</td>
                            <td>
                              {sendRequest.attachment_names.length === 0
                                ? t('common.none')
                                : sendRequest.attachment_names.join(', ')}
                            </td>
                            <td>{sendRequest.created_at}</td>
                          </tr>
                          <tr className="maintenance-detail-row">
                            <td colSpan={6}>
                              {t('maintenance.debug.sendRequestDetail', {
                                cc:
                                  sendRequest.cc_addresses.length === 0
                                    ? t('common.none')
                                    : sendRequest.cc_addresses.join(', '),
                                bcc:
                                  sendRequest.bcc_addresses.length === 0
                                    ? t('common.none')
                                    : sendRequest.bcc_addresses.join(', '),
                                replyTo:
                                  sendRequest.reply_to_message_id ?? t('common.none'),
                              })}
                            </td>
                          </tr>
                        </Fragment>
                      ))}
                      {sendRequests?.length === 0 && (
                        <tr>
                          <td colSpan={6}>{t('maintenance.debug.empty')}</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
                </section>
              </section>
            )}
          </div>
        </div>
      </div>
    </main>
  )
}

export default MaintenanceView
