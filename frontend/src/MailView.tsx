import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import {
  getMailDetail,
  ingestMockMail,
  listMailPage,
  markMailRead,
  markMailUnread,
  processMail,
  runNextJob,
  unprocessMail,
  updateMailImportance,
} from './phase4Api'
import type { MailDetail, MailListFilters, MailListItem } from './phase4Api'
import { t } from './i18n'

type MailTab = 'unprocessed' | 'processed' | 'skip'
type MailScope = 'day' | 'all_unprocessed'
type SearchSort = 'newest' | 'importance'

const MAIL_TABS: Array<{ key: MailTab; labelKey: string }> = [
  { key: 'unprocessed', labelKey: 'mail.tab.unprocessed' },
  { key: 'processed', labelKey: 'mail.tab.processed' },
  { key: 'skip', labelKey: 'mail.tab.skip' },
]

function mailTabLabel(tab: MailTab) {
  if (tab === 'processed') {
    return t('mail.tab.processed')
  }
  if (tab === 'skip') {
    return t('mail.tab.skip')
  }
  return t('mail.tab.unprocessed')
}

function describeError(error: unknown) {
  return error instanceof Error ? error.message : t('mail.requestFailed')
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

function jstDateToday() {
  return jstInputNow().slice(0, 10)
}

function uniqueSuffix() {
  return Date.now().toString(36)
}

function startOfDate(date: string) {
  return `${date}T00:00:00+09:00`
}

function endOfDate(date: string) {
  return `${date}T23:59:59+09:00`
}

function formatTime(value: string) {
  return value.slice(11, 16)
}

function priorityLabel(mail: MailListItem) {
  return mail.effective_importance
}

function compareVisibleMails(sort: SearchSort) {
  return (left: MailListItem, right: MailListItem) => {
    if (sort === 'importance') {
      const rank = (left.importance_rank ?? 99) - (right.importance_rank ?? 99)
      if (rank !== 0) {
        return rank
      }
    }
    return right.received_at.localeCompare(left.received_at) || left.id.localeCompare(right.id)
  }
}

function groupMailsByDate(mails: MailListItem[]) {
  return mails.reduce<Array<{ date: string; items: MailListItem[] }>>((groups, mail) => {
    const date = mail.received_date ?? mail.received_at.slice(0, 10)
    const lastGroup = groups[groups.length - 1]
    if (lastGroup?.date === date) {
      lastGroup.items.push(mail)
    } else {
      groups.push({ date, items: [mail] })
    }
    return groups
  }, [])
}

function MailView() {
  const [mails, setMails] = useState<MailListItem[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [selectedMailId, setSelectedMailId] = useState<string | null>(null)
  const [lockedMail, setLockedMail] = useState<MailListItem | null>(null)
  const [detail, setDetail] = useState<MailDetail | null>(null)
  const [activeTab, setActiveTab] = useState<MailTab>('unprocessed')
  const [scope, setScope] = useState<MailScope>('day')
  const [selectedDate, setSelectedDate] = useState(jstDateToday())
  const [searchText, setSearchText] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [searchSort, setSearchSort] = useState<SearchSort>('newest')
  const [pageSize, setPageSize] = useState(25)
  const [subject, setSubject] = useState('Review mock mail')
  const [fromAddress, setFromAddress] = useState('review.mock.sender@example.com')
  const [bodyText, setBodyText] = useState('This is a mock mail for review.')
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isBusy, setIsBusy] = useState(false)

  const isSearchMode = searchQuery.trim() !== ''
  const visibleMails = useMemo(
    () => [...mails].sort(compareVisibleMails(isSearchMode ? searchSort : 'importance')),
    [isSearchMode, mails, searchSort],
  )
  const groupedMails = useMemo(() => groupMailsByDate(visibleMails), [visibleMails])

  function listFilters(cursor?: string): MailListFilters {
    const filters: MailListFilters = {
      limit: pageSize,
      cursor,
      tab: activeTab,
    }
    if (isSearchMode) {
      filters.q = searchQuery.trim()
      filters.tab = 'all'
    } else if (scope === 'day') {
      filters.date_from = startOfDate(selectedDate)
      filters.date_to = endOfDate(selectedDate)
    } else {
      filters.tab = 'unprocessed'
    }
    return filters
  }

  async function refreshMails(options: { keepDetail?: boolean } = {}) {
    const page = await listMailPage(listFilters())
    setMails(page.items)
    setNextCursor(page.next_cursor)
    if (!options.keepDetail) {
      setDetail(null)
      setLockedMail(null)
      setSelectedMailId(null)
    } else if (selectedMailId !== null) {
      const selectedStillExists = page.items.some((item) => item.id === selectedMailId)
      if (!selectedStillExists) {
        setDetail(null)
        setLockedMail(null)
        setSelectedMailId(null)
      }
    }
  }

  useEffect(() => {
    let isMounted = true
    listMailPage(listFilters())
      .then((page) => {
        if (isMounted) {
          setMails(page.items)
          setNextCursor(page.next_cursor)
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
  }, [activeTab, scope, selectedDate, searchQuery, pageSize])

  async function handleMockIngest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setNotice(null)
    setIsBusy(true)
    const suffix = uniqueSuffix()

    try {
      const result = await ingestMockMail({
        gmail_message_id: `mock_${suffix}`,
        gmail_thread_id: `mock_thread_${suffix}`,
        message_id_header: `<mock-${suffix}@caseclosed.local>`,
        subject,
        from_address: fromAddress,
        received_at: jstInputNow(),
        body_text: bodyText,
      })
      await refreshMails()
      setNotice(
        result.pending
          ? t('mail.mock.pending', { email: result.pending_address ?? fromAddress })
          : t('mail.mock.ingested'),
      )
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsBusy(false)
    }
  }

  async function handleSelectMail(mail: MailListItem) {
    setError(null)
    setNotice(null)
    setSelectedMailId(mail.id)
    if (mail.pending_reason !== null) {
      setLockedMail(mail)
      setDetail(null)
      return
    }

    setIsBusy(true)
    try {
      const nextDetail =
        mail.read_status === 'unread'
          ? await markMailRead(mail.id)
          : await getMailDetail(mail.id)
      setLockedMail(null)
      setDetail(nextDetail)
      setMails((currentMails) =>
        currentMails.map((currentMail) =>
          currentMail.id === mail.id
            ? { ...currentMail, read_status: nextDetail.user_state.read_status, read_at: nextDetail.user_state.read_at }
            : currentMail,
        ),
      )
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsBusy(false)
    }
  }

  async function handleRunNextJob() {
    setError(null)
    setNotice(null)
    setIsBusy(true)
    try {
      const result = await runNextJob()
      await refreshMails({ keepDetail: true })
      setNotice(
        result.job_id === null
          ? t('mail.job.none')
          : t('mail.job.ran', { jobId: result.job_id }),
      )
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsBusy(false)
    }
  }

  async function handleLoadMore() {
    if (nextCursor === null) {
      return
    }
    setError(null)
    setNotice(null)
    setIsBusy(true)
    try {
      const page = await listMailPage(listFilters(nextCursor))
      setMails((currentMails) => [...currentMails, ...page.items])
      setNextCursor(page.next_cursor)
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsBusy(false)
    }
  }

  async function mutateDetail(action: () => Promise<MailDetail>) {
    setError(null)
    setNotice(null)
    setIsBusy(true)
    try {
      const nextDetail = await action()
      setDetail(nextDetail)
      setLockedMail(null)
      setSelectedMailId(nextDetail.message.id)
      await refreshMails({ keepDetail: true })
      setNotice(t('mail.updated'))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsBusy(false)
    }
  }

  function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSearchQuery(searchText)
  }

  function clearSearch() {
    setSearchText('')
    setSearchQuery('')
  }

  function handleTabClick(nextTab: MailTab) {
    setActiveTab(nextTab)
    setScope('day')
    setSearchText('')
    setSearchQuery('')
  }

  return (
    <main className="app-shell">
      <div className="mail-shell">
        <header className="maintenance-header">
          <div>
            <p>{t('app.name')}</p>
            <h1>{t('mail.heading')}</h1>
          </div>
          <a href="/">{t('top.heading')}</a>
        </header>

        {(error !== null || notice !== null) && (
          <div className="mail-feedback">
            {error !== null && <p role="alert">{error}</p>}
            {notice !== null && <p>{notice}</p>}
          </div>
        )}

        <section aria-labelledby="mail-search-heading" className="mail-panel mail-search-panel">
          <div className="section-heading">
            <h2 id="mail-search-heading">{t('mail.search.heading')}</h2>
            <div className="mail-actions">
              <button disabled={isBusy} onClick={handleRunNextJob} type="button">
                {t('mail.job.runNext')}
              </button>
            </div>
          </div>
          <form className="mail-search-form" onSubmit={handleSearch}>
            <input
              aria-label={t('mail.search.label')}
              onChange={(event) => setSearchText(event.target.value)}
              placeholder={t('mail.search.placeholder')}
              value={searchText}
            />
            <select
              aria-label={t('mail.search.sort')}
              onChange={(event) => setSearchSort(event.target.value as SearchSort)}
              value={searchSort}
            >
              <option value="newest">{t('mail.sort.newest')}</option>
              <option value="importance">{t('mail.sort.importance')}</option>
            </select>
            <select
              aria-label={t('mail.pageSize')}
              onChange={(event) => setPageSize(Number(event.target.value))}
              value={pageSize}
            >
              <option value={10}>10</option>
              <option value={25}>25</option>
              <option value={50}>50</option>
            </select>
            <button disabled={isBusy} type="submit">
              {t('mail.search.submit')}
            </button>
            <button disabled={isBusy || !isSearchMode} onClick={clearSearch} type="button">
              {t('mail.search.clear')}
            </button>
          </form>
        </section>

        <section aria-labelledby="mock-mail-heading" className="mail-panel mail-dev-panel">
          <details>
            <summary id="mock-mail-heading">{t('mail.mock.heading')}</summary>
            <form className="mail-mock-form" onSubmit={handleMockIngest}>
              <label>
                <span>{t('mail.subject')}</span>
                <input
                  onChange={(event) => setSubject(event.target.value)}
                  required
                  value={subject}
                />
              </label>
              <label>
                <span>{t('mail.from')}</span>
                <input
                  onChange={(event) => setFromAddress(event.target.value)}
                  required
                  type="email"
                  value={fromAddress}
                />
              </label>
              <label>
                <span>{t('mail.body')}</span>
                <textarea
                  onChange={(event) => setBodyText(event.target.value)}
                  value={bodyText}
                />
              </label>
              <button disabled={isBusy} type="submit">
                {t('mail.mock.ingest')}
              </button>
            </form>
          </details>
        </section>

        {!isSearchMode && (
          <nav aria-label={t('mail.tabs.label')} className="mail-tabs">
            <div>
              {MAIL_TABS.map((tab) => (
                <button
                  aria-selected={activeTab === tab.key}
                  key={tab.key}
                  onClick={() => handleTabClick(tab.key)}
                  role="tab"
                  type="button"
                >
                  {mailTabLabel(tab.key)}
                </button>
              ))}
            </div>
            <button
              aria-pressed={scope === 'all_unprocessed'}
              onClick={() => {
                setActiveTab('unprocessed')
                setScope(scope === 'all_unprocessed' ? 'day' : 'all_unprocessed')
              }}
              type="button"
            >
              {t('mail.scope.allUnprocessed')}
            </button>
          </nav>
        )}

        <section aria-labelledby="mail-list-heading" className="mail-grid">
          <div className="mail-panel mail-list-panel">
            <div className="section-heading">
              <div>
                <h2 id="mail-list-heading">
                  {isSearchMode ? t('mail.search.results') : t('mail.list.heading')}
                </h2>
                <p>
                  {isSearchMode
                    ? t('mail.search.resultNote')
                    : scope === 'all_unprocessed'
                      ? t('mail.scope.allUnprocessed')
                      : selectedDate}
                </p>
              </div>
              {!isSearchMode && scope === 'day' && (
                <input
                  aria-label={t('mail.date')}
                  onChange={(event) => setSelectedDate(event.target.value)}
                  type="date"
                  value={selectedDate}
                />
              )}
              <button disabled={isBusy} onClick={() => refreshMails()} type="button">
                {t('mail.refresh')}
              </button>
            </div>

            {visibleMails.length === 0 ? (
              <p className="mail-empty">{t('mail.empty')}</p>
            ) : (
              <div className="mail-date-groups">
                {groupedMails.map((group) => (
                  <section className="mail-date-group" key={group.date}>
                    <h3>{group.date}</h3>
                    <div className="mail-list" role="list">
                      {group.items.map((mail) => (
                        <button
                          aria-pressed={selectedMailId === mail.id}
                          className={`mail-list-item mail-priority-${mail.effective_importance} mail-read-${mail.read_status ?? 'unread'}`}
                          key={mail.id}
                          onClick={() => handleSelectMail(mail)}
                          type="button"
                        >
                          <span className="mail-list-time">{formatTime(mail.received_at)}</span>
                          <strong>{mail.subject ?? t('mail.noSubject')}</strong>
                          <span>{mail.from_name ?? mail.from_address}</span>
                          <span>
                            {priorityLabel(mail)} | {mail.processed_status}
                            {mail.pending_reason !== null ? ` | ${t('mail.locked')}` : ''}
                          </span>
                        </button>
                      ))}
                    </div>
                  </section>
                ))}
                {nextCursor !== null && (
                  <button
                    className="mail-load-more"
                    disabled={isBusy}
                    onClick={handleLoadMore}
                    type="button"
                  >
                    {t('mail.loadMore')}
                  </button>
                )}
              </div>
            )}
          </div>

          <div className="mail-panel">
            <div className="section-heading">
              <h2>{t('mail.detail.heading')}</h2>
            </div>

            {lockedMail !== null ? (
              <article className="mail-detail mail-pending-lock">
                <header>
                  <p>{lockedMail.from_address}</p>
                  <h3>{lockedMail.subject ?? t('mail.noSubject')}</h3>
                  <span>{lockedMail.pending_reason}</span>
                </header>
                <p>{t('mail.pending.locked')}</p>
              </article>
            ) : detail === null ? (
              <p className="mail-empty">{t('mail.detail.empty')}</p>
            ) : (
              <article className="mail-detail">
                <header>
                  <p>{detail.message.from_address}</p>
                  <h3>{detail.message.subject ?? t('mail.noSubject')}</h3>
                  <span>
                    {detail.auto_state.effective_importance} |{' '}
                    {detail.user_state.processed_status} | {detail.user_state.read_status}
                  </span>
                </header>

                <dl>
                  <div>
                    <dt>{t('mail.replyTo')}</dt>
                    <dd>{detail.message.reply_to_address ?? t('common.none')}</dd>
                  </div>
                  <div>
                    <dt>{t('mail.llmRun')}</dt>
                    <dd>{detail.auto_state.llm_run_id ?? t('common.none')}</dd>
                  </div>
                  <div>
                    <dt>{t('mail.pendingReason')}</dt>
                    <dd>{detail.auto_state.pending_reason ?? t('common.none')}</dd>
                  </div>
                </dl>

                <pre>{detail.message.body_text ?? t('mail.noBody')}</pre>

                <div className="mail-actions">
                  {['High', 'Middle', 'Low', 'Skip'].map((importance) => (
                    <button
                      disabled={isBusy || detail.auto_state.pending_reason !== null}
                      key={importance}
                      onClick={() =>
                        mutateDetail(() =>
                          updateMailImportance(detail.message.id, importance),
                        )
                      }
                      type="button"
                    >
                      {importance}
                    </button>
                  ))}
                  {detail.user_state.processed_status === 'processed' ? (
                    <button
                      disabled={isBusy}
                      onClick={() => mutateDetail(() => unprocessMail(detail.message.id))}
                      type="button"
                    >
                      {t('mail.unprocess')}
                    </button>
                  ) : (
                    <button
                      disabled={isBusy}
                      onClick={() => mutateDetail(() => processMail(detail.message.id))}
                      type="button"
                    >
                      {t('mail.process')}
                    </button>
                  )}
                  {detail.user_state.read_status === 'read' ? (
                    <button
                      disabled={isBusy}
                      onClick={() => mutateDetail(() => markMailUnread(detail.message.id))}
                      type="button"
                    >
                      {t('mail.markUnread')}
                    </button>
                  ) : (
                    <button
                      disabled={isBusy}
                      onClick={() => mutateDetail(() => markMailRead(detail.message.id))}
                      type="button"
                    >
                      {t('mail.markRead')}
                    </button>
                  )}
                </div>
              </article>
            )}
          </div>
        </section>
      </div>
    </main>
  )
}

export default MailView
