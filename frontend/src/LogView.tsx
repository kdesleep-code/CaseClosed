import { useEffect, useMemo, useState } from 'react'
import { t } from './i18n'
import type { LogEntry, LogPage } from './logsApi'
import { listLogs, logsExportUrl } from './logsApi'
import { TopNav } from './navigation'

const allLogTypes = [
  'audit',
  'system',
  'auth',
  'job',
  'write',
  'external',
  'storage',
  'llm',
  'mail_send',
]

function initialLogTypesFromUrl() {
  const params = new URLSearchParams(window.location.search)
  const types = params
    .get('types')
    ?.split(',')
    .map((type) => type.trim())
    .filter((type) => allLogTypes.includes(type))
  if (types === undefined || types.length === 0) {
    return allLogTypes
  }
  return Array.from(new Set(types))
}

function describeError(error: unknown) {
  return error instanceof Error ? error.message : t('app.requestFailed')
}

function formatMetadata(value: unknown) {
  if (value === null || value === undefined) {
    return t('common.none')
  }
  if (typeof value === 'string') {
    return value
  }
  return JSON.stringify(value, null, 2)
}

function defaultDateFrom() {
  const date = new Date()
  date.setDate(date.getDate() - 7)
  return date.toISOString().slice(0, 10)
}

function endOfDate(date: string) {
  return date === '' ? '' : `${date}T23:59:59+09:00`
}

function startOfDate(date: string) {
  return date === '' ? '' : `${date}T00:00:00+09:00`
}

function LogDetail({ entry }: { entry: LogEntry }) {
  const [isOpen, setIsOpen] = useState(false)
  const hasDetail = entry.detail !== null || entry.metadata !== null
  if (!hasDetail) {
    return null
  }
  return (
    <div className="log-detail">
      <button onClick={() => setIsOpen(!isOpen)} type="button">
        {isOpen ? t('logs.hideDetail') : t('logs.showDetail')}
      </button>
      {isOpen && (
        <pre>
          {[entry.detail, formatMetadata(entry.metadata)]
            .filter((value) => value !== null && value !== '')
            .join('\n\n')}
        </pre>
      )}
    </div>
  )
}

function LogRow({ entry }: { entry: LogEntry }) {
  return (
    <tr>
      <td>{entry.occurred_at}</td>
      <td>
        <span className="log-type-pill">{entry.source_type}</span>
      </td>
      <td>
        <span data-status={entry.level}>{entry.level}</span>
      </td>
      <td>
        <strong>{entry.category}</strong>
        {entry.status !== null && <small>{entry.status}</small>}
      </td>
      <td>
        {entry.summary}
        <LogDetail entry={entry} />
      </td>
      <td>
        {entry.target_type ?? t('common.none')}
        {entry.target_id !== null && <small>{entry.target_id}</small>}
      </td>
    </tr>
  )
}

function LogView() {
  const [pageData, setPageData] = useState<LogPage | null>(null)
  const [selectedTypes, setSelectedTypes] = useState<string[]>(initialLogTypesFromUrl)
  const [query, setQuery] = useState('')
  const [dateFrom, setDateFrom] = useState(defaultDateFrom)
  const [dateTo, setDateTo] = useState('')
  const [page, setPage] = useState(1)
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  const activeFilters = useMemo(
    () => ({
      page,
      types: selectedTypes.length === allLogTypes.length ? [] : selectedTypes,
      query,
      dateFrom: startOfDate(dateFrom),
      dateTo: endOfDate(dateTo),
    }),
    [dateFrom, dateTo, page, query, selectedTypes],
  )

  useEffect(() => {
    let isMounted = true
    setIsLoading(true)
    setError(null)
    listLogs(activeFilters)
      .then((nextPage) => {
        if (isMounted) {
          setPageData(nextPage)
        }
      })
      .catch((requestError) => {
        if (isMounted) {
          setError(describeError(requestError))
          setPageData(null)
        }
      })
      .finally(() => {
        if (isMounted) {
          setIsLoading(false)
        }
      })

    return () => {
      isMounted = false
    }
  }, [activeFilters])

  function toggleType(type: string) {
    setPage(1)
    setSelectedTypes((current) => {
      if (current.includes(type)) {
        const next = current.filter((item) => item !== type)
        return next.length === 0 ? current : next
      }
      return [...current, type]
    })
  }

  function resetFilters() {
    setSelectedTypes(allLogTypes)
    setQuery('')
    setDateFrom(defaultDateFrom())
    setDateTo('')
    setPage(1)
  }

  const totalPages = pageData?.total_pages ?? 1
  const canMovePrevious = page > 1
  const canMoveNext = page < totalPages

  return (
    <main className="app-shell">
      <div className="contacts-shell log-shell">
        <header className="contacts-header">
          <div>
            <p>{t('app.name')}</p>
            <h1>{t('logs.heading')}</h1>
          </div>
          <TopNav
            ariaLabelKey="nav.logs"
            items={[
              { href: '/', labelKey: 'top.heading' },
              { href: '/logs', labelKey: 'nav.logs' },
              { href: '/maintenance', labelKey: 'nav.maintenance' },
              { href: '/settings', labelKey: 'nav.settings' },
            ]}
          />
        </header>

        {error !== null && <p className="maintenance-error">{error}</p>}

        <section className="contact-panel contact-tools-panel log-filter-panel">
          <div className="section-heading">
            <h2>{t('logs.filters')}</h2>
            <div className="log-actions">
              <a href={logsExportUrl(activeFilters)}>{t('logs.exportCsv')}</a>
              <button onClick={resetFilters} type="button">
                {t('logs.reset')}
              </button>
            </div>
          </div>

          <div className="log-filter-grid">
            <label>
              <span>{t('logs.search')}</span>
              <input
                onChange={(event) => {
                  setPage(1)
                  setQuery(event.target.value)
                }}
                placeholder={t('logs.searchPlaceholder')}
                value={query}
              />
            </label>
            <label>
              <span>{t('logs.dateFrom')}</span>
              <input
                onChange={(event) => {
                  setPage(1)
                  setDateFrom(event.target.value)
                }}
                type="date"
                value={dateFrom}
              />
            </label>
            <label>
              <span>{t('logs.dateTo')}</span>
              <input
                onChange={(event) => {
                  setPage(1)
                  setDateTo(event.target.value)
                }}
                type="date"
                value={dateTo}
              />
            </label>
          </div>

          <div className="log-type-list" aria-label={t('logs.types')}>
            {allLogTypes.map((type) => {
              const count = pageData?.types.find((item) => item.type === type)?.count ?? 0
              return (
                <label key={type}>
                  <input
                    checked={selectedTypes.includes(type)}
                    onChange={() => toggleType(type)}
                    type="checkbox"
                  />
                  <span>{type}</span>
                  <small>{count}</small>
                </label>
              )
            })}
          </div>
        </section>

        <section aria-labelledby="logs-results-heading" className="contact-list-workspace log-results-workspace">
          <div className="contact-list-panel-surface log-results-surface">
            <section className="contact-panel contact-list-panel log-results-panel">
              <div className="section-heading">
                <h2 id="logs-results-heading">{t('logs.results')}</h2>
                <p>
                  {pageData === null
                    ? t('common.loading')
                    : t('logs.pageStatus', {
                        page: String(pageData.page),
                        totalPages: String(pageData.total_pages),
                        total: String(pageData.total),
                      })}
                </p>
              </div>

              <div className="log-pager">
                <button
                  disabled={!canMovePrevious || isLoading}
                  onClick={() => setPage(page - 1)}
                  type="button"
                >
                  {t('logs.previous')}
                </button>
                <button
                  disabled={!canMoveNext || isLoading}
                  onClick={() => setPage(page + 1)}
                  type="button"
                >
                  {t('logs.next')}
                </button>
              </div>

              <div className="maintenance-table-wrap log-table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th scope="col">{t('logs.occurredAt')}</th>
                      <th scope="col">{t('logs.type')}</th>
                      <th scope="col">{t('logs.level')}</th>
                      <th scope="col">{t('logs.category')}</th>
                      <th scope="col">{t('logs.summary')}</th>
                      <th scope="col">{t('logs.target')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pageData === null && (
                      <tr>
                        <td colSpan={6}>{t('common.loading')}</td>
                      </tr>
                    )}
                    {pageData?.items.map((entry) => (
                      <LogRow entry={entry} key={`${entry.source_type}:${entry.id}`} />
                    ))}
                    {pageData?.items.length === 0 && (
                      <tr>
                        <td colSpan={6}>{t('logs.empty')}</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </section>
          </div>
        </section>
      </div>
    </main>
  )
}

export default LogView
