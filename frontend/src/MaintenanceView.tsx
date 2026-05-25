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
  refreshPendingMail,
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
  ingestMockMail,
  listMailSendRequests,
  runNextJob,
} from './phase4Api'
import type { MailSendRequest } from './phase4Api'

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

function jstInputNow() {
  const now = new Date()
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Tokyo',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  })
    .formatToParts(now)
    .reduce<Record<string, string>>((values, part) => {
      values[part.type] = part.value
      return values
    }, {})
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:00+09:00`
}

function uniqueSuffix() {
  return Date.now().toString(36)
}

function countRequiredActions(
  jobs: Job[],
  operations: ExternalOperation[],
  pendingMails: PendingMail[],
) {
  return (
    jobs.filter(jobNeedsAction).length +
    operations.filter((operation) => operation.status === 'unknown').length +
    pendingMails.length
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
  const [debugSubject, setDebugSubject] = useState('Review mock mail')
  const [debugFromAddress, setDebugFromAddress] = useState(
    'review.mock.sender@example.com',
  )
  const [debugBodyText, setDebugBodyText] = useState(
    'This is a mock mail for review.',
  )
  const [debugNotice, setDebugNotice] = useState<string | null>(null)
  const [isDebugBusy, setIsDebugBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<MaintenanceTab>('usage')
  const [activeUsageMetric, setActiveUsageMetric] =
    useState<UsageMetric>(usageMetrics[0])
  const [activeUsageHistoryRange, setActiveUsageHistoryRange] =
    useState<UsageHistoryRange>(usageHistoryRanges[0])
  const actionJobs = jobs.filter(jobNeedsAction)
  const requiredActionCount = countRequiredActions(jobs, operations, pendingMails)
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

  async function handleRefreshPendingMail(mail: PendingMail) {
    setBusyId(mail.id)
    setError(null)
    try {
      await refreshPendingMail(mail.id)
      setPendingMails(await listPendingMails())
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setBusyId(null)
    }
  }

  async function refreshSendRequests() {
    setSendRequests(await listMailSendRequests())
  }

  async function handleDebugRunNextJob() {
    setError(null)
    setDebugNotice(null)
    setIsDebugBusy(true)
    try {
      const result = await runNextJob()
      setDebugNotice(
        result.job_id === null
          ? t('mail.job.none')
          : t('mail.job.ran', { jobId: result.job_id }),
      )
      await refreshSendRequests()
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsDebugBusy(false)
    }
  }

  async function handleDebugMockIngest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setDebugNotice(null)
    setIsDebugBusy(true)
    const suffix = uniqueSuffix()

    try {
      const result = await ingestMockMail({
        gmail_message_id: `mock_${suffix}`,
        gmail_thread_id: `mock_thread_${suffix}`,
        message_id_header: `<mock-${suffix}@caseclosed.local>`,
        subject: debugSubject,
        from_address: debugFromAddress,
        received_at: jstInputNow(),
        body_text: debugBodyText,
      })
      setDebugNotice(
        result.pending
          ? t('mail.mock.pending', {
              email: result.pending_address ?? debugFromAddress,
            })
          : t('mail.mock.ingested'),
      )
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
                          <th scope="col">{t('common.action')}</th>
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
                              <td>
                                <button
                                  aria-label={t(
                                    'maintenance.pendingMails.refreshFor',
                                    { id: mail.id },
                                  )}
                                  disabled={busyId === mail.id}
                                  onClick={() => handleRefreshPendingMail(mail)}
                                  title={t('maintenance.pendingMails.refreshTitle')}
                                  type="button"
                                >
                                  {t('maintenance.pendingMails.refresh')}
                                </button>
                              </td>
                            </tr>
                            <tr className="maintenance-detail-row">
                              <td colSpan={6}>
                                {t('maintenance.pendingMails.detail')}
                              </td>
                            </tr>
                          </Fragment>
                        ))}
                        {pendingMails.length === 0 && (
                          <tr>
                            <td colSpan={6}>
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
                  <div className="mail-actions mail-debug-actions">
                    <button
                      disabled={isDebugBusy}
                      onClick={handleDebugRunNextJob}
                      type="button"
                    >
                      {t('mail.job.runNext')}
                    </button>
                  </div>
                  <form className="mail-mock-form" onSubmit={handleDebugMockIngest}>
                    <label>
                      <span>{t('mail.subject')}</span>
                      <input
                        onChange={(event) => setDebugSubject(event.target.value)}
                        required
                        value={debugSubject}
                      />
                    </label>
                    <label>
                      <span>{t('mail.from')}</span>
                      <input
                        onChange={(event) => setDebugFromAddress(event.target.value)}
                        required
                        type="email"
                        value={debugFromAddress}
                      />
                    </label>
                    <label>
                      <span>{t('mail.body')}</span>
                      <textarea
                        onChange={(event) => setDebugBodyText(event.target.value)}
                        value={debugBodyText}
                      />
                    </label>
                    <button disabled={isDebugBusy} type="submit">
                      {t('mail.mock.ingest')}
                    </button>
                  </form>
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
