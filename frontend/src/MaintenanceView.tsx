import { Fragment, useEffect, useState } from 'react'
import {
  listExternalOperations,
  listJobs,
  readMaintenanceStatus,
  resolveExternalOperation,
  retryJob,
} from './phase2Api'
import type { ExternalOperation, Job, MaintenanceStatus } from './phase2Api'

const usageMetrics = [
  { key: 'database', label: 'Database', value: 'Not available' },
  { key: 'storage', label: 'Storage', value: 'Not available' },
  { key: 'llm-cost', label: 'LLM cost', value: 'Not available' },
  { key: 'metric-4', label: 'Metric 4', value: 'Not available' },
  { key: 'metric-5', label: 'Metric 5', value: 'Not available' },
  { key: 'metric-6', label: 'Metric 6', value: 'Not available' },
  { key: 'running-jobs', label: 'Running jobs', statusKey: 'running_jobs' },
  {
    key: 'pending-write-requests',
    label: 'Pending write requests',
    statusKey: 'pending_write_requests',
  },
  {
    key: 'external-unknown',
    label: 'External unknown',
    statusKey: 'external_unknown_count',
  },
] as const

const usageHistoryRanges = [
  {
    key: '24h',
    label: '24h',
    axisLabels: ['24h ago', '18h', '12h', '6h', 'Now'],
  },
  {
    key: '7d',
    label: '7d',
    axisLabels: ['7d ago', '5d', '3d', '1d', 'Now'],
  },
  {
    key: '30d',
    label: '30d',
    axisLabels: ['30d ago', '21d', '14d', '7d', 'Now'],
  },
] as const

type MaintenanceTab = 'usage' | 'jobs'
type UsageMetric = (typeof usageMetrics)[number]
type UsageHistoryRange = (typeof usageHistoryRanges)[number]

function updateById<T extends { id: string }>(items: T[], updated: T) {
  return items.map((item) => (item.id === updated.id ? updated : item))
}

function describeError(error: unknown) {
  return error instanceof Error ? error.message : 'Maintenance request failed.'
}

function countRequiredActions(jobs: Job[], operations: ExternalOperation[]) {
  return (
    jobs.filter((job) => job.status === 'failed').length +
    operations.filter((operation) => operation.status === 'unknown').length
  )
}

function usageMetricValue(
  metric: UsageMetric,
  status: MaintenanceStatus | null,
) {
  return 'statusKey' in metric ? status?.[metric.statusKey] ?? '-' : metric.value
}

function jobStatusDetail(job: Job) {
  const reason = [job.error_type, job.error_message].filter(Boolean).join(' - ')
  if (job.status === 'failed') {
    return reason === ''
      ? 'ジョブの実行に失敗しました。詳細な失敗理由は記録されていません。'
      : `ジョブの実行に失敗しました。理由: ${reason}`
  }

  if (job.status === 'pending') {
    return 'ジョブは Worker による実行待ちです。'
  }
  if (job.status === 'running') {
    return 'ジョブを Worker が実行中です。'
  }
  if (job.status === 'succeeded') {
    return 'ジョブは正常に完了しました。'
  }
  if (job.status === 'stale') {
    return '実行中の heartbeat が途切れたため、ジョブの状態確認が必要です。'
  }

  return `ジョブは ${job.status} 状態です。`
}

function externalOperationStatusDetail(operation: ExternalOperation) {
  if (operation.status === 'unknown') {
    return operation.unknown_reason === null
      ? '外部操作の成否を自動では確定できませんでした。外部サービス側を手動で確認してください。'
      : `外部操作の成否を自動では確定できませんでした。理由: ${operation.unknown_reason}`
  }

  if (operation.status === 'pending') {
    return '外部操作は実行待ちです。'
  }
  if (operation.status === 'running') {
    return '外部サービスへの操作を実行中です。'
  }
  if (operation.status === 'succeeded') {
    return '外部操作は成功として記録されています。'
  }
  if (operation.status === 'failed') {
    return '外部操作は失敗として記録されています。'
  }
  if (operation.status === 'canceled') {
    return '外部操作はキャンセル扱いです。'
  }

  return `外部操作は ${operation.status} 状態です。`
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

    Promise.all([
      readMaintenanceStatus(),
      listJobs(),
      listExternalOperations(),
    ])
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
            <p>CaseClosed</p>
            <h1>Maintenance</h1>
          </div>
          <a href="/">Top</a>
        </header>

        {error !== null && <p className="maintenance-error" role="alert">{error}</p>}

        <div className="maintenance-workspace">
          <div aria-label="Maintenance views" className="maintenance-tabs" role="tablist">
            <button
              aria-controls="maintenance-usage-panel"
              aria-selected={activeTab === 'usage'}
              id="maintenance-usage-tab"
              onClick={() => setActiveTab('usage')}
              role="tab"
              type="button"
            >
              Usage
            </button>
            <button
              aria-controls="maintenance-jobs-panel"
              aria-selected={activeTab === 'jobs'}
              id="maintenance-jobs-tab"
              onClick={() => setActiveTab('jobs')}
              role="tab"
              type="button"
            >
              <span>Needs Action</span>
              <span
                aria-label={`${requiredActionCount} actions required`}
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
                  <h2 id="usage-heading">Usage</h2>
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
                      <p>{metric.label}</p>
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
                      {activeUsageMetric.label} history
                    </h3>
                    <div
                      aria-label="History range"
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
                    <div aria-label="History value scale" className="usage-history-y-axis">
                      <span>High</span>
                      <span>Mid</span>
                      <span>Low</span>
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
                      {activeUsageHistoryRange.axisLabels.map((label) => (
                        <span key={label}>{label}</span>
                      ))}
                    </div>
                  </div>
                  <p>No history yet.</p>
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
            <section aria-labelledby="jobs-heading" className="maintenance-section">
          <div className="section-heading">
            <h2 id="jobs-heading">Jobs</h2>
            <p>{status?.job_accepting === false ? 'Paused' : 'Accepting'}</p>
          </div>

          <div className="maintenance-table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">ID</th>
                  <th scope="col">Type</th>
                  <th scope="col">Status</th>
                  <th scope="col">Retry</th>
                  <th scope="col">Action</th>
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
                      <td>{job.retry_count}/{job.max_retries}</td>
                      <td>
                        {job.status === 'failed' ? (
                          <button
                            aria-label={`Retry ${job.id}`}
                            disabled={busyId === job.id}
                            onClick={() => handleRetry(job)}
                            title="この failed job を pending に戻し、Worker が再実行できる状態にします。"
                            type="button"
                          >
                            Retry
                          </button>
                        ) : (
                          <span className="quiet-cell">-</span>
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
                    <td colSpan={5}>No jobs.</td>
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
            <h2 id="external-operations-heading">External Operations</h2>
          </div>

          <div className="maintenance-table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">ID</th>
                  <th scope="col">Type</th>
                  <th scope="col">Service</th>
                  <th scope="col">Status</th>
                  <th scope="col">Resolution</th>
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
                              aria-label={`Mark ${operation.id} succeeded`}
                              disabled={busyId === operation.id}
                              onClick={() => handleResolve(operation, 'mark_succeeded')}
                              title="外部サービス側で成功済みと確認した結果を記録します。この操作は再実行しません。"
                              type="button"
                            >
                              Succeeded
                            </button>
                            <button
                              aria-label={`Mark ${operation.id} failed`}
                              disabled={busyId === operation.id}
                              onClick={() => handleResolve(operation, 'mark_failed')}
                              title="手動確認で失敗と判断した結果を記録します。"
                              type="button"
                            >
                              Failed
                            </button>
                            <button
                              aria-label={`Cancel ${operation.id}`}
                              disabled={busyId === operation.id}
                              onClick={() => handleResolve(operation, 'mark_canceled')}
                              title="手動確認後、この外部操作をキャンセル扱いにします。"
                              type="button"
                            >
                              Cancel
                            </button>
                          </div>
                        ) : (
                          <span className="quiet-cell">-</span>
                        )}
                      </td>
                    </tr>
                    <tr className="maintenance-detail-row">
                      <td colSpan={5}>{externalOperationStatusDetail(operation)}</td>
                    </tr>
                  </Fragment>
                ))}
                {operations.length === 0 && (
                  <tr>
                    <td colSpan={5}>No external operations.</td>
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
