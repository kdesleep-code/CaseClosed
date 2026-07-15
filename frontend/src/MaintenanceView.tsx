import { Fragment, useEffect, useState } from 'react'
import { t } from './i18n'
import type { MessageKey } from './i18n'
import { AppLink, TopNav } from './navigation'
import {
  previewableImageExtensions,
  previewableTextExtensions,
} from './storagePreview'
import {
  discardJob,
  listExternalOperations,
  listJobs,
  listPendingMails,
  readLlmCostHistory,
  readMaintenanceStatus,
  resolveExternalOperation,
  retryJob,
} from './phase2Api'
import { listStorageLocations } from './phase3Api'
import type {
  ExternalOperation,
  Job,
  LlmCostHistory,
  MaintenanceIntegrationHealth,
  MaintenanceStatus,
  MaintenanceSystemHealth,
  PendingMail,
} from './phase2Api'
import type { StorageLocation } from './phase3Api'

const usageMetrics = [
  { key: 'storage', labelKey: 'maintenance.metric.storage' },
  { key: 'llm-cost', labelKey: 'maintenance.metric.llmCost' },
  { key: 'llm-projected', labelKey: 'maintenance.metric.llmProjected' },
  { key: 'mail-total', labelKey: 'maintenance.metric.mailTotal' },
  { key: 'mail-received-7d', labelKey: 'maintenance.metric.mailReceived7d' },
  { key: 'mail-sent-7d', labelKey: 'maintenance.metric.mailSent7d' },
  { key: 'mail-average-30d', labelKey: 'maintenance.metric.mailAverage30d' },
  { key: 'mail-importance', labelKey: 'maintenance.metric.mailImportance' },
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

type MaintenanceTab = 'usage' | 'jobs' | 'storage' | 'debug'
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

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  const kib = bytes / 1024
  if (kib < 1024) return `${kib.toFixed(kib >= 10 ? 0 : 1)} KB`
  const mib = kib / 1024
  if (mib < 1024) return `${mib.toFixed(mib >= 10 ? 0 : 1)} MB`
  const gib = mib / 1024
  return `${gib.toFixed(gib >= 10 ? 0 : 1)} GB`
}

function StorageLocationCard({ location }: { location: StorageLocation }) {
  return (
    <article className="storage-location-card">
      <div>
        <h3>{location.label}</h3>
        <p>{location.root_path}</p>
      </div>
      <dl>
        <div>
          <dt>{t('common.type')}</dt>
          <dd>{location.kind}</dd>
        </div>
        <div>
          <dt>{t('common.status')}</dt>
          <dd>{location.status}</dd>
        </div>
        <div>
          <dt>{t('storage.objectCount')}</dt>
          <dd>{location.object_count}</dd>
        </div>
        <div>
          <dt>{t('storage.totalSize')}</dt>
          <dd>{formatBytes(location.active_byte_size)}</dd>
        </div>
      </dl>
    </article>
  )
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
  if (status === null) return t('maintenance.notAvailable')
  if (metric.key === 'storage') {
    return `${formatBytes(status.storage_active_bytes ?? 0)} / ${formatNumber(status.storage_active_objects ?? 0)} files`
  }
  if (metric.key === 'llm-cost') {
    const used = status.llm_cost_month_used
    const remaining = status.llm_cost_month_remaining
    if (used === undefined) {
      return t('maintenance.notAvailable')
    }
    if (remaining === null || remaining === undefined) {
      return formatMoney(used, 'usd')
    }
    return t('maintenance.llmCost.remainingShort', {
      remaining: formatMoney(remaining, 'usd'),
    })
  }
  if (metric.key === 'llm-projected') {
    return formatMoney(status.llm_cost_month_projected, 'usd')
  }
  if (metric.key === 'mail-total') {
    return formatNumber(status.mail_total)
  }
  if (metric.key === 'mail-received-7d') {
    return formatNumber(status.mail_received_7d)
  }
  if (metric.key === 'mail-sent-7d') {
    return formatNumber(status.mail_sent_7d)
  }
  if (metric.key === 'mail-average-30d') {
    return formatNumber(status.mail_daily_average_30d)
  }
  if (metric.key === 'mail-importance') {
    return `H ${formatNumber(status.mail_importance_high)} / M ${formatNumber(status.mail_importance_middle)} / L ${formatNumber(status.mail_importance_low)}`
  }
  return metric.statusKey === undefined
    ? t('maintenance.notAvailable')
    : status[metric.statusKey] ?? t('common.none')
}

function formatMoney(value: number | null | undefined, currency: string) {
  if (value === null || value === undefined) {
    return t('common.none')
  }
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: currency.toUpperCase(),
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  }).format(value)
}

function formatNumber(value: number | null | undefined) {
  if (value === null || value === undefined) {
    return t('common.none')
  }
  return new Intl.NumberFormat('en-US').format(value)
}

function formatHealthTime(value: string | null | undefined) {
  if (value === null || value === undefined) return t('common.none')
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function healthStatusLabel(status: string) {
  const key = `maintenance.health.status.${status}` as MessageKey
  return t(key)
}

function HealthBadge({ status }: { status: string }) {
  return (
    <span className="maintenance-health-badge" data-health={status}>
      {healthStatusLabel(status)}
    </span>
  )
}

function IntegrationHealthRow({
  label,
  integration,
}: {
  label: string
  integration: MaintenanceIntegrationHealth
}) {
  return (
    <tr>
      <th scope="row">{label}</th>
      <td><HealthBadge status={integration.status} /></td>
      <td>
        {integration.enabled
          ? t('maintenance.health.everyMinutes', {
              minutes: integration.interval_minutes,
            })
          : t('maintenance.health.status.disabled')}
      </td>
      <td>{formatHealthTime(integration.last_success_at)}</td>
      <td className={integration.last_error ? 'maintenance-health-error' : undefined}>
        {integration.last_error ?? t('common.none')}
      </td>
    </tr>
  )
}

function SystemHealthPanel({
  health,
  refreshing,
  onRefresh,
}: {
  health: MaintenanceSystemHealth
  refreshing: boolean
  onRefresh: () => void
}) {
  return (
    <section aria-labelledby="system-health-heading" className="maintenance-health">
      <div className="section-heading">
        <div>
          <div className="maintenance-health-title">
            <h3 id="system-health-heading">{t('maintenance.health.heading')}</h3>
            <HealthBadge status={health.status} />
          </div>
          <p>
            {t('maintenance.health.checkedAt', {
              time: formatHealthTime(health.checked_at),
            })}
          </p>
        </div>
        <button
          className={`button-loading-dot${refreshing ? ' is-loading' : ''}`}
          disabled={refreshing}
          onClick={onRefresh}
          type="button"
        >
          {t('maintenance.health.refresh')}
        </button>
      </div>

      <div className="maintenance-health-queue">
        {(['pending', 'scheduled', 'running', 'failed', 'stale'] as const).map((key) => (
          <div data-health={key === 'failed' || key === 'stale' ? 'attention' : 'neutral'} key={key}>
            <span>{t(`maintenance.health.queue.${key}` as MessageKey)}</span>
            <strong>{formatNumber(health.queue[key])}</strong>
          </div>
        ))}
      </div>

      <div className="maintenance-table-wrap maintenance-health-table">
        <table>
          <thead>
            <tr>
              <th scope="col">{t('maintenance.health.service')}</th>
              <th scope="col">{t('common.status')}</th>
              <th scope="col">{t('maintenance.health.schedule')}</th>
              <th scope="col">{t('maintenance.health.lastSuccess')}</th>
              <th scope="col">{t('maintenance.health.lastError')}</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row">{t('maintenance.health.worker')}</th>
              <td><HealthBadge status={health.worker.status} /></td>
              <td>
                {t('maintenance.health.workerCount', {
                  alive: health.worker.alive_workers,
                  configured: health.worker.configured_workers,
                })}
              </td>
              <td>{formatHealthTime(health.worker.last_job_activity_at)}</td>
              <td>{t('common.none')}</td>
            </tr>
            <IntegrationHealthRow
              integration={health.gmail_auto_import}
              label={t('maintenance.health.gmail')}
            />
            <IntegrationHealthRow
              integration={health.calendar_auto_sync}
              label={t('maintenance.health.calendar')}
            />
          </tbody>
        </table>
      </div>
    </section>
  )
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

function jobRelatedMailDetail(job: Job) {
  const mail = job.related_mail
  if (mail === null) {
    return null
  }
  const subject = mail.subject?.trim() || '(no subject)'
  const receivedAt = mail.received_at ?? 'unknown date'
  const fromAddress = mail.from_address ?? 'unknown sender'
  const label =
    mail.context_type === 'thread'
      ? 'Related thread'
      : mail.context_type === 'send_reply'
        ? 'Reply target'
        : mail.context_type === 'send_request'
          ? 'Send request'
          : 'Related mail'
  const text = `${label}: ${receivedAt} / ${fromAddress} / ${subject}`

  if (mail.mail_url === null) {
    return <span>{text}</span>
  }
  return <a href={mail.mail_url}>{text}</a>
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
  return 'usage'
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
  const [llmCostHistory, setLlmCostHistory] = useState<LlmCostHistory | null>(null)
  const [storageLocations, setStorageLocations] = useState<StorageLocation[] | null>(
    null,
  )
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [refreshingHealth, setRefreshingHealth] = useState(false)
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
    if (initialData !== undefined) return
    const intervalId = window.setInterval(() => {
      readMaintenanceStatus().then(setStatus).catch(() => undefined)
    }, 30_000)
    return () => window.clearInterval(intervalId)
  }, [initialData])

  async function handleHealthRefresh() {
    setRefreshingHealth(true)
    setError(null)
    try {
      setStatus(await readMaintenanceStatus())
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setRefreshingHealth(false)
    }
  }

  useEffect(() => {
    if (activeTab !== 'usage' || activeUsageMetric.key !== 'llm-cost') {
      return
    }
    let isMounted = true
    readLlmCostHistory()
      .then((history) => {
        if (!isMounted) {
          return
        }
        setLlmCostHistory(history)
      })
      .catch((requestError) => {
        if (isMounted) {
          setError(describeError(requestError))
        }
      })

    return () => {
      isMounted = false
    }
  }, [activeTab, activeUsageMetric.key])

  useEffect(() => {
    let isMounted = true
    if (activeTab !== 'storage' || storageLocations !== null) {
      return () => {
        isMounted = false
      }
    }
    listStorageLocations()
      .then((locations) => {
        if (isMounted) setStorageLocations(locations)
      })
      .catch((requestError) => {
        if (isMounted) setError(describeError(requestError))
      })
    return () => {
      isMounted = false
    }
  }, [activeTab, storageLocations])

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

  async function handleDiscard(job: Job) {
    setBusyId(`discard-${job.id}`)
    setError(null)
    try {
      const discardedJob = await discardJob(job.id)
      setJobs(jobs.filter((item) => item.id !== discardedJob.id))
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

  return (
    <main className="app-shell">
      <div className="maintenance-shell">
        <header className="maintenance-header">
          <div>
            <p>{t('app.name')}</p>
            <h1>{t('maintenance.heading')}</h1>
          </div>
          <TopNav
            ariaLabelKey="maintenance.navigation"
            items={[
              { href: '/', labelKey: 'top.heading' },
              { href: '/logs', labelKey: 'nav.logs' },
              { href: '/settings', labelKey: 'nav.settings' },
              { href: '/files', labelKey: 'nav.files' },
              { href: '/profile', labelKey: 'nav.profile' },
            ]}
          />
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
              aria-controls="maintenance-storage-panel"
              aria-selected={activeTab === 'storage'}
              id="maintenance-storage-tab"
              onClick={() => setActiveTab('storage')}
              role="tab"
              type="button"
            >
              {t('maintenance.storage')}
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

                {status?.system_health !== undefined && (
                  <SystemHealthPanel
                    health={status.system_health}
                    onRefresh={handleHealthRefresh}
                    refreshing={refreshingHealth}
                  />
                )}

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
                  {activeUsageMetric.key === 'llm-cost' ? (
                    <div className="llm-cost-history">
                      {llmCostHistory === null ? (
                        <p>{t('maintenance.debug.loading')}</p>
                      ) : (
                        <>
                          <div className="llm-cost-summary-grid">
                            <div>
                              <span>{t('maintenance.llmCost.remaining')}</span>
                              <strong>
                                {formatMoney(
                                  llmCostHistory.month_remaining,
                                  llmCostHistory.currency,
                                )}
                              </strong>
                            </div>
                            <div>
                              <span>{t('maintenance.llmCost.monthUsed')}</span>
                              <strong>
                                {formatMoney(
                                  llmCostHistory.month_used,
                                  llmCostHistory.currency,
                                )}
                              </strong>
                            </div>
                            <div>
                              <span>{t('maintenance.llmCost.todayUsed')}</span>
                              <strong>
                                {formatMoney(
                                  llmCostHistory.today_used,
                                  llmCostHistory.currency,
                                )}
                              </strong>
                            </div>
                            <div>
                              <span>{t('maintenance.llmCost.totalUsed')}</span>
                              <strong>
                                {formatMoney(
                                  llmCostHistory.total_used,
                                  llmCostHistory.currency,
                                )}
                              </strong>
                            </div>
                          </div>
                          <p>{t('maintenance.llmCost.sourceLocal')}</p>
                          <div className="maintenance-table-wrap llm-cost-table-wrap">
                            <table>
                              <thead>
                                <tr>
                                  <th scope="col">{t('maintenance.debug.llmFunction')}</th>
                                  <th scope="col">{t('maintenance.llmCost.runs')}</th>
                                  <th scope="col">
                                    {t('maintenance.llmCost.promptTokens')}
                                  </th>
                                  <th scope="col">
                                    {t('maintenance.llmCost.completionTokens')}
                                  </th>
                                  <th scope="col">
                                    {t('maintenance.llmCost.totalTokens')}
                                  </th>
                                  <th scope="col">{t('maintenance.llmCost.cost')}</th>
                                </tr>
                              </thead>
                              <tbody>
                                {llmCostHistory.by_function.map((item) => (
                                  <tr key={item.function_type}>
                                    <td>{item.function_type}</td>
                                    <td>{formatNumber(item.run_count)}</td>
                                    <td>{formatNumber(item.prompt_tokens)}</td>
                                    <td>{formatNumber(item.completion_tokens)}</td>
                                    <td>{formatNumber(item.total_tokens)}</td>
                                    <td>
                                      {formatMoney(
                                        item.estimated_cost,
                                        llmCostHistory.currency,
                                      )}
                                    </td>
                                  </tr>
                                ))}
                                {llmCostHistory.by_function.length === 0 && (
                                  <tr>
                                    <td colSpan={6}>
                                      {t('maintenance.history.noHistory')}
                                    </td>
                                  </tr>
                                )}
                              </tbody>
                            </table>
                          </div>
                        </>
                      )}
                    </div>
                  ) : activeUsageMetric.key === 'storage' ? (
                    <div className="storage-backup-panel">
                      <div className="section-heading">
                        <h3>{t('maintenance.storageBackup.heading')}</h3>
                        <p>{t('maintenance.storageBackup.locations')}</p>
                      </div>
                      <dl className="gmail-auto-import-status">
                        <div>
                          <dt>{t('maintenance.storageBackup.status')}</dt>
                          <dd>{status?.backup_status ?? t('common.none')}</dd>
                        </div>
                      </dl>
                      <button disabled type="button">
                        {t('maintenance.storageBackup.archive')}
                      </button>
                      <p>{t('maintenance.storageBackup.notImplemented')}</p>
                    </div>
                  ) : (
                    <>
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
                    </>
                  )}
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
                                {job.status === 'failed' || job.status === 'stale' ? (
                                  <div className="resolution-actions">
                                    {job.status === 'failed' && (
                                      <button
                                        aria-label={t('maintenance.jobs.retryFor', {
                                          id: job.id,
                                        })}
                                        className={`button-loading-dot${
                                          busyId === job.id ? ' is-loading' : ''
                                        }`}
                                        disabled={busyId !== null}
                                        onClick={() => handleRetry(job)}
                                        title={t('maintenance.jobs.retryTitle')}
                                        type="button"
                                      >
                                        {t('maintenance.jobs.retry')}
                                      </button>
                                    )}
                                    <button
                                      aria-label={t('maintenance.jobs.discardFor', {
                                        id: job.id,
                                      })}
                                      className={`button-loading-dot${
                                        busyId === `discard-${job.id}`
                                          ? ' is-loading'
                                          : ''
                                      }`}
                                      disabled={busyId !== null}
                                      onClick={() => handleDiscard(job)}
                                      title={t('maintenance.jobs.discardTitle')}
                                      type="button"
                                    >
                                      {t('maintenance.jobs.discard')}
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
                                <div>{jobStatusDetail(job)}</div>
                                {job.related_mail !== null && (
                                  <div className="maintenance-related-mail">
                                    {jobRelatedMailDetail(job)}
                                  </div>
                                )}
                              </td>
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
                    <div>
                      <h2 id="external-operations-heading">
                        {t('maintenance.external.heading')}
                      </h2>
                      <p>{t('maintenance.external.note')}</p>
                    </div>
                    <AppLink className="maintenance-inline-link" href="/logs?types=external">
                      {t('maintenance.external.viewLogs')}
                    </AppLink>
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
                                      className={`button-loading-dot${
                                        busyId === operation.id ? ' is-loading' : ''
                                      }`}
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
                                      className={`button-loading-dot${
                                        busyId === operation.id ? ' is-loading' : ''
                                      }`}
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
                                      className={`button-loading-dot${
                                        busyId === operation.id ? ' is-loading' : ''
                                      }`}
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

            {activeTab === 'storage' && (
              <section
                aria-labelledby="maintenance-storage-tab storage-heading"
                className="maintenance-panel maintenance-section"
                id="maintenance-storage-panel"
                role="tabpanel"
              >
                <div className="section-heading">
                  <h2 id="storage-heading">
                    {t('maintenance.storage.emptyHeading')}
                  </h2>
                  <p>{t('maintenance.storage.emptyBody')}</p>
                </div>
                <div className="storage-location-grid">
                  {storageLocations === null ? (
                    <p>{t('storage.loading')}</p>
                  ) : (
                    storageLocations.map((location) => (
                      <StorageLocationCard key={location.id} location={location} />
                    ))
                  )}
                  {storageLocations !== null && storageLocations.length === 0 && (
                    <p>{t('storage.noLocations')}</p>
                  )}
                </div>
              </section>
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

                <section
                  aria-labelledby="maintenance-debug-tools-heading"
                  className="mail-panel mail-dev-panel"
                >
                  <div className="section-heading">
                    <h3 id="maintenance-debug-tools-heading">
                      {t('mail.debug.heading')}
                    </h3>
                  </div>
                  <div className="maintenance-debug-preview-list">
                    <div>
                      <h4>{t('maintenance.debug.previewableExtensions')}</h4>
                      <p>{t('maintenance.debug.previewableExtensionsNote')}</p>
                    </div>
                    <div className="maintenance-extension-group">
                      <h5>{t('maintenance.debug.previewableImageExtensions')}</h5>
                      <div className="maintenance-extension-list">
                        {previewableImageExtensions.map((extension) => (
                          <span key={extension}>.{extension}</span>
                        ))}
                      </div>
                    </div>
                    <div className="maintenance-extension-group">
                      <h5>{t('maintenance.debug.previewableTextExtensions')}</h5>
                      <div className="maintenance-extension-list">
                        {previewableTextExtensions.map((extension) => (
                          <span key={extension}>.{extension}</span>
                        ))}
                      </div>
                    </div>
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
