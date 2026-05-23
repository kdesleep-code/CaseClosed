import { Fragment, useEffect, useState } from 'react'
import { t } from './i18n'
import type { MessageKey } from './i18n'
import {
  listExternalOperations,
  listJobs,
  readMaintenanceStatus,
  resolveExternalOperation,
  retryJob,
} from './phase2Api'
import type { ExternalOperation, Job, MaintenanceStatus } from './phase2Api'

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

type MaintenanceTab = 'usage' | 'jobs'
type UsageMetric = (typeof usageMetrics)[number]
type UsageHistoryRange = (typeof usageHistoryRanges)[number]

function updateById<T extends { id: string }>(items: T[], updated: T) {
  return items.map((item) => (item.id === updated.id ? updated : item))
}

function describeError(error: unknown) {
  return error instanceof Error ? error.message : t('maintenance.requestFailed')
}

function countRequiredActions(jobs: Job[], operations: ExternalOperation[]) {
  return (
    jobs.filter((job) => job.status === 'failed').length +
    operations.filter((operation) => operation.status === 'unknown').length
  )
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

function MaintenanceView() {
  const [status, setStatus] = useState<MaintenanceStatus | null>(null)
  const [jobs, setJobs] = useState<Job[]>([])
  const [operations, setOperations] = useState<ExternalOperation[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<MaintenanceTab>('usage')
  const [activeUsageMetric, setActiveUsageMetric] =
    useState<UsageMetric>(usageMetrics[0])
  const [activeUsageHistoryRange, setActiveUsageHistoryRange] =
    useState<UsageHistoryRange>(usageHistoryRanges[0])
  const requiredActionCount = countRequiredActions(jobs, operations)
  const requiredActionLabel = requiredActionCount > 9 ? '9+' : requiredActionCount

  useEffect(() => {
    let isMounted = true

    Promise.all([readMaintenanceStatus(), listJobs(), listExternalOperations()])
      .then(([nextStatus, nextJobs, nextOperations]) => {
        if (!isMounted) {
          return
        }
        setStatus(nextStatus)
        setJobs(nextJobs)
        setOperations(nextOperations)
      })
      .catch((requestError) => {
        if (isMounted) {
          setError(describeError(requestError))
        }
      })

    return () => {
      isMounted = false
    }
  }, [])

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

  return (
    <main className="app-shell">
      <div className="maintenance-shell">
        <header className="maintenance-header">
          <div>
            <p>{t('app.name')}</p>
            <h1>{t('maintenance.heading')}</h1>
          </div>
          <a href="/">{t('top.heading')}</a>
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
                        {jobs.map((job) => (
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
                        {jobs.length === 0 && (
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
              </div>
            )}
          </div>
        </div>
      </div>
    </main>
  )
}

export default MaintenanceView
