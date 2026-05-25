import { useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import {
  listMailDates,
  listMailPage,
} from './phase4Api'
import type { MailDateSummary, MailListFilters, MailListItem } from './phase4Api'
import { t } from './i18n'
import type { MessageKey } from './i18n'
import { AppLink, navigateTo } from './navigation'
import defaultContactAvatarUrl from './assets/default-contact-avatar.svg'
import defaultMailingListAvatarUrl from './assets/default-mailing-list-avatar.svg'
import unknownContactAvatarUrl from './assets/default-unknown-contact-avatar.svg'
import llmBlockedIconUrl from './assets/llm-blocked.svg'

export type MailTab = 'unprocessed' | 'processed' | 'skip'
type SearchSort = 'newest' | 'importance'

export type MailInitialData = {
  mails: MailListItem[]
  mailDates: MailDateSummary[]
  nextCursor: string | null
  activeTab: MailTab
  selectedDate: string
  calendarMonth: string
  viewMode?: 'normal' | 'action-needed'
}

const MAIL_TABS: Array<{ key: MailTab; labelKey: string }> = [
  { key: 'unprocessed', labelKey: 'mail.tab.unprocessed' },
  { key: 'processed', labelKey: 'mail.tab.processed' },
  { key: 'skip', labelKey: 'mail.tab.skip' },
]

const IMPORTANCE_LEGEND = [
  { key: 'high', labelKey: 'mail.importance.high' },
  { key: 'middle', labelKey: 'mail.importance.middle' },
  { key: 'low', labelKey: 'mail.importance.low' },
  { key: 'skip', labelKey: 'mail.importance.skip' },
  { key: 'unclassified', labelKey: 'mail.importance.unclassified' },
] satisfies Array<{ key: string; labelKey: MessageKey }>

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

function dateParts(date: string) {
  const [year, month, day] = date.split('-').map(Number)
  return { year, month, day }
}

function formatCalendarDate(year: number, month: number, day: number) {
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

function addMonths(date: string, amount: number) {
  const { year, month } = dateParts(date)
  const nextDate = new Date(Date.UTC(year, month - 1 + amount, 1))
  return formatCalendarDate(nextDate.getUTCFullYear(), nextDate.getUTCMonth() + 1, 1)
}

function calendarDays(date: string) {
  const { year, month } = dateParts(date)
  const firstDay = new Date(Date.UTC(year, month - 1, 1))
  const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate()
  return [
    ...Array.from({ length: firstDay.getUTCDay() }, () => null),
    ...Array.from({ length: daysInMonth }, (_, index) =>
      formatCalendarDate(year, month, index + 1),
    ),
  ]
}

function monthLabel(date: string) {
  return date.slice(0, 7)
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

function senderDisplayName(mail: MailListItem) {
  return mail.sender_contact?.display_name ?? mail.from_name ?? mail.from_address
}

function senderAvatarUrl(mail: MailListItem) {
  if (mail.sender_contact === null || mail.sender_contact === undefined) {
    return unknownContactAvatarUrl
  }
  return (
    mail.sender_contact.avatar_url ??
    (mail.sender_contact.kind === 'mailing_list'
      ? defaultMailingListAvatarUrl
      : defaultContactAvatarUrl)
  )
}

function mailSummary(mail: MailListItem) {
  if (!['high', 'middle'].includes(mail.effective_importance)) {
    return null
  }
  const summary = mail.summary?.trim()
  if (summary === undefined || summary === '') {
    return null
  }
  return summary.length > 96 ? `${summary.slice(0, 95)}...` : summary
}

function mailPriorityClass(importance: string) {
  if (importance === 'pending') {
    return 'mail-priority-bug'
  }
  return `mail-priority-${importance}`
}

function llmBlockedTitle(mail: MailListItem) {
  return mail.llm_block_reason == null || mail.llm_block_reason.trim() === ''
    ? t('mail.llmBlockedTitle')
    : t('mail.llmBlockedWithReason', { reason: mail.llm_block_reason })
}

function groupLabelForMail(mail: MailListItem, sort: SearchSort) {
  if (sort === 'importance') {
    return mail.effective_importance
  }
  return mail.received_date ?? mail.received_at.slice(0, 10)
}

function shouldShowMailGroupLabel(
  mail: MailListItem,
  index: number,
  mailsToRender: MailListItem[],
  sort: SearchSort,
) {
  if (index === 0) {
    return true
  }
  return (
    groupLabelForMail(mail, sort) !== groupLabelForMail(mailsToRender[index - 1], sort)
  )
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

function isMailTab(value: string | null): value is MailTab {
  return value === 'unprocessed' || value === 'processed' || value === 'skip'
}

function initialQueryParams() {
  const params = new URLSearchParams(window.location.search)
  const tab = params.get('tab')
  const date = params.get('date')
  return {
    activeTab: isMailTab(tab) ? tab : 'unprocessed',
    selectedDate: date !== null && /^\d{4}-\d{2}-\d{2}$/.test(date) ? date : jstDateToday(),
  }
}

function MailView({ initialData }: { initialData?: MailInitialData }) {
  const didUseInitialData = useRef(initialData !== undefined)
  const didUsePreparedData = useRef(false)
  const queryParams = useMemo(() => initialQueryParams(), [])
  const [mails, setMails] = useState<MailListItem[]>(initialData?.mails ?? [])
  const [mailDates, setMailDates] = useState<MailDateSummary[]>(
    initialData?.mailDates ?? [],
  )
  const [nextCursor, setNextCursor] = useState<string | null>(
    initialData?.nextCursor ?? null,
  )
  const [activeTab, setActiveTab] = useState<MailTab>(
    initialData?.activeTab ?? queryParams.activeTab,
  )
  const [selectedDate, setSelectedDate] = useState(
    initialData?.selectedDate ?? queryParams.selectedDate,
  )
  const [calendarMonth, setCalendarMonth] = useState(
    initialData?.calendarMonth ?? queryParams.selectedDate,
  )
  const [searchText, setSearchText] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [listSort, setListSort] = useState<SearchSort>('importance')
  const [pageSize, setPageSize] = useState(25)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isBusy, setIsBusy] = useState(false)

  const isSearchMode = searchQuery.trim() !== ''
  const isActionNeededMode = initialData?.viewMode === 'action-needed'
  const isSearchLikeMode = isSearchMode || isActionNeededMode
  const visibleMails = useMemo(
    () => [...mails].sort(compareVisibleMails(listSort)),
    [mails, listSort],
  )
  const hasClassifyingMail = mails.some(
    (mail) => mail.effective_importance === 'unclassified',
  )
  const mailDateCounts = useMemo(
    () => new Map(mailDates.map((item) => [item.date, item.count])),
    [mailDates],
  )
  const sortedMailDates = useMemo(
    () => mailDates.map((item) => item.date).sort(),
    [mailDates],
  )
  const previousMailDate =
    [...sortedMailDates].reverse().find((date) => date < selectedDate) ?? null
  const nextMailDate = sortedMailDates.find((date) => date > selectedDate) ?? null
  const selectedMonthDays = calendarDays(calendarMonth)

  function listFilters(cursor?: string): MailListFilters {
    const filters: MailListFilters = {
      limit: pageSize,
      cursor,
      tab: activeTab,
    }
    if (isActionNeededMode) {
      filters.tab = 'unprocessed'
      filters.importance_any = 'high,middle'
    } else if (isSearchMode) {
      filters.q = searchQuery.trim()
      filters.tab = 'all'
    } else {
      filters.date_from = startOfDate(selectedDate)
      filters.date_to = endOfDate(selectedDate)
    }
    return filters
  }

  function dayListFilters(tab: MailTab, date: string): MailListFilters {
    return {
      limit: pageSize,
      tab,
      date_from: startOfDate(date),
      date_to: endOfDate(date),
    }
  }

  async function refreshMails() {
    const page = await listMailPage(listFilters())
    setMails(page.items)
    setNextCursor(page.next_cursor)
  }

  async function transitionMailList(nextTab: MailTab, nextDate: string) {
    setError(null)
    setNotice(null)
    setIsBusy(true)
    try {
      const [page, dates] = await Promise.all([
        listMailPage(dayListFilters(nextTab, nextDate)),
        listMailDates(nextTab),
      ])
      didUsePreparedData.current = true
      setActiveTab(nextTab)
      setSelectedDate(nextDate)
      setCalendarMonth(nextDate)
      setSearchText('')
      setSearchQuery('')
      setMails(page.items)
      setNextCursor(page.next_cursor)
      setMailDates(dates)
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsBusy(false)
    }
  }

  useEffect(() => {
    if (didUseInitialData.current) {
      didUseInitialData.current = false
      return
    }
    if (didUsePreparedData.current) {
      didUsePreparedData.current = false
      return
    }
    let isMounted = true
    Promise.allSettled([listMailPage(listFilters()), listMailDates(activeTab)])
      .then(([pageResult, datesResult]) => {
        if (isMounted) {
          if (pageResult.status === 'fulfilled') {
            setMails(pageResult.value.items)
            setNextCursor(pageResult.value.next_cursor)
          } else {
            setError(describeError(pageResult.reason))
          }
          if (datesResult.status === 'fulfilled') {
            setMailDates(datesResult.value)
          }
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
  }, [activeTab, selectedDate, searchQuery, pageSize])

  useEffect(() => {
    if (!hasClassifyingMail) {
      return
    }

    let isMounted = true
    const timerId = window.setInterval(() => {
      if (document.visibilityState !== 'visible') {
        return
      }
      listMailPage(listFilters())
        .then((page) => {
          if (!isMounted) {
            return
          }
          setMails(page.items)
          setNextCursor(page.next_cursor)
        })
        .catch(() => {
          // Keep the currently visible list if a background refresh fails.
        })
    }, 5000)

    return () => {
      isMounted = false
      window.clearInterval(timerId)
    }
  }, [activeTab, hasClassifyingMail, isActionNeededMode, pageSize, searchQuery, selectedDate])

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

  function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSearchQuery(searchText)
  }

  function clearSearch() {
    setSearchText('')
    setSearchQuery('')
  }

  function handleTabClick(nextTab: MailTab) {
    if (isBusy || nextTab === activeTab) {
      return
    }
    void transitionMailList(nextTab, selectedDate)
  }

  function jumpToMailDate(date: string | null) {
    if (date === null) {
      return
    }
    void transitionMailList(activeTab, date)
  }

  function jumpToToday() {
    const today = jstDateToday()
    void transitionMailList(activeTab, today)
  }

  return (
    <main className="app-shell">
      <div className="mail-shell">
        {!isSearchLikeMode && (
          <div className="mail-floating-day-nav" aria-label={t('mail.dayNavigation')}>
            <button
              aria-label={t('mail.previousDay')}
              disabled={isBusy || previousMailDate === null}
              onClick={() => jumpToMailDate(previousMailDate)}
              type="button"
            >
              {'<'}
            </button>
            <button
              aria-label={t('mail.nextDay')}
              disabled={isBusy || nextMailDate === null}
              onClick={() => jumpToMailDate(nextMailDate)}
              type="button"
            >
              {'>'}
            </button>
          </div>
        )}

        <header className="maintenance-header">
          <div>
            <p>{t('app.name')}</p>
            <h1>{t('mail.heading')}</h1>
          </div>
          <nav aria-label={t('mail.navigation')} className="maintenance-nav">
            <AppLink href="/">{t('top.heading')}</AppLink>
          </nav>
        </header>

        {(error !== null || notice !== null) && (
          <div className="mail-feedback">
            {error !== null && <p role="alert">{error}</p>}
            {notice !== null && <p>{notice}</p>}
          </div>
        )}

        <div className="mail-main-layout">
          <div className="mail-main-column">
            <section aria-labelledby="mail-list-heading" className="mail-list-workspace">
              {!isSearchLikeMode && (
                <nav aria-label={t('mail.tabs.label')} className="mail-tabs">
                  <div>
                    {MAIL_TABS.map((tab) => (
                      <button
                        aria-selected={activeTab === tab.key}
                        aria-disabled={isBusy}
                        key={tab.key}
                        onClick={() => handleTabClick(tab.key)}
                        role="tab"
                        type="button"
                      >
                        {mailTabLabel(tab.key)}
                      </button>
                    ))}
                  </div>
                  <div className="mail-tab-gadgets">
                    <div
                      aria-label={t('mail.importanceLegend.label')}
                      className="mail-importance-legend"
                    >
                      {IMPORTANCE_LEGEND.map((item) => (
                        <span
                          className={`mail-legend-item mail-priority-${item.key}`}
                          key={item.key}
                        >
                          {t(item.labelKey)}
                        </span>
                      ))}
                    </div>
                    <div className="mail-tab-actions">
                      <AppLink className="mail-compose-gadget" href="/mail/compose">
                        {t('work.composeMail')}
                      </AppLink>
                      <AppLink className="mail-compose-gadget" href="/mail/action-needed">
                        {t('mail.actionNeeded')}
                      </AppLink>
                    </div>
                  </div>
                </nav>
              )}
              <div className="mail-panel mail-list-panel">
                <div className="section-heading">
                  {isSearchLikeMode ? (
                    <div>
                      <h2 id="mail-list-heading">
                        {isActionNeededMode
                          ? t('mail.actionNeeded.heading')
                          : t('mail.search.results')}
                      </h2>
                      <p>
                        {isActionNeededMode
                          ? t('mail.actionNeeded.resultNote')
                          : t('mail.search.resultNote')}
                      </p>
                    </div>
                  ) : (
                    <h2 id="mail-list-heading">{selectedDate}</h2>
                  )}
                  <button disabled={isBusy} onClick={() => refreshMails()} type="button">
                    {t('mail.refresh')}
                  </button>
                </div>

                {visibleMails.length === 0 ? (
                  <p className="mail-empty">{t('mail.empty')}</p>
                ) : (
                  <div className="mail-date-groups">
                    <div className="mail-list" role="list">
                      {visibleMails.map((mail, index) => (
                        <div className="mail-list-entry" key={mail.id}>
                          {isSearchLikeMode &&
                            shouldShowMailGroupLabel(
                              mail,
                              index,
                              visibleMails,
                              listSort,
                            ) && (
                              <div className="mail-list-group-label">
                                <span>{groupLabelForMail(mail, listSort)}</span>
                              </div>
                            )}
                          <article
                            className={`mail-list-item ${mailPriorityClass(mail.effective_importance)} mail-read-${mail.read_status ?? 'unread'} ${
                              mail.effective_importance === 'unclassified'
                                ? 'mail-list-item-confirming'
                                : ''
                            }`}
                            onClick={() => navigateTo(`/mail/${encodeURIComponent(mail.id)}`)}
                            onKeyDown={(event) => {
                              if (event.key === 'Enter' || event.key === ' ') {
                                event.preventDefault()
                                navigateTo(`/mail/${encodeURIComponent(mail.id)}`)
                              }
                            }}
                            role="link"
                            tabIndex={0}
                          >
                            <div className="mail-list-sender-media">
                              <span className="mail-list-time">{formatTime(mail.received_at)}</span>
                              <img
                                alt={t('mail.senderAvatarAlt', {
                                  name: senderDisplayName(mail),
                                })}
                                src={senderAvatarUrl(mail)}
                              />
                            </div>
                            <div className="mail-list-main">
                              <strong>
                                <span>{mail.subject ?? t('mail.noSubject')}</span>
                              </strong>
                              <span>{senderDisplayName(mail)}</span>
                            </div>
                            <p className="mail-list-summary">
                              {mailSummary(mail) ?? ''}
                            </p>
                            <div className="mail-list-cases">
                              {mail.llm_blocked === true && (
                                <span
                                  aria-label={llmBlockedTitle(mail)}
                                  className="mail-llm-blocked-badge"
                                  title={llmBlockedTitle(mail)}
                                >
                                  <img alt="" src={llmBlockedIconUrl} />
                                  <span className="visually-hidden">{t('mail.llmBlocked')}</span>
                                </span>
                              )}
                              {(mail.case_links ?? []).length > 0 ? (
                                mail.case_links?.map((caseLink) => (
                                  <span key={caseLink.id}>{caseLink.title}</span>
                                ))
                              ) : (
                                <span>{t('mail.noCase')}</span>
                              )}
                            </div>
                          </article>
                        </div>
                      ))}
                    </div>
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
            </section>
          </div>

          <aside className="mail-side-column">
            {!isSearchLikeMode && (
              <section aria-label={t('mail.calendar.label')} className="mail-panel mail-calendar-panel">
              <button className="mail-calendar-today" onClick={jumpToToday} type="button">
                {t('mail.today')}
              </button>
              <div className="mail-calendar-heading">
                <button
                  aria-label={t('mail.previousMonth')}
                  disabled={isBusy}
                  onClick={() => setCalendarMonth((currentMonth) => addMonths(currentMonth, -1))}
                  type="button"
                >
                  {'<'}
                </button>
                <strong>{monthLabel(calendarMonth)}</strong>
                <button
                  aria-label={t('mail.nextMonth')}
                  disabled={isBusy}
                  onClick={() => setCalendarMonth((currentMonth) => addMonths(currentMonth, 1))}
                  type="button"
                >
                  {'>'}
                </button>
              </div>
              <div aria-label={t('mail.calendar.label')} className="mail-calendar-grid">
                {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map((weekday) => (
                  <span className="mail-calendar-weekday" key={weekday}>
                    {weekday}
                  </span>
                ))}
                {selectedMonthDays.map((date, index) => {
                  if (date === null) {
                    return (
                      <span
                        aria-hidden="true"
                        className="mail-calendar-empty"
                        key={`empty-${index}`}
                      />
                    )
                  }
                  const count = mailDateCounts.get(date) ?? 0
                  const hasMail = count > 0
                  return (
                    <button
                      aria-current={date === selectedDate ? 'date' : undefined}
                      aria-label={hasMail ? t('mail.calendar.openDate', { date, count }) : date}
                      className={hasMail ? 'mail-calendar-day' : 'mail-calendar-day mail-calendar-day-empty'}
                      disabled={!hasMail || isBusy}
                      key={date}
                      onClick={() => jumpToMailDate(date)}
                      type="button"
                    >
                      {Number(date.slice(8, 10))}
                    </button>
                  )
                })}
              </div>
              </section>
            )}

            <section aria-labelledby="mail-sort-heading" className="mail-panel mail-sort-panel">
              <div className="section-heading">
                <h2 id="mail-sort-heading">{t('mail.sort.heading')}</h2>
              </div>
              <div aria-label={t('mail.sort.label')} className="mail-sort-control">
                <button
                  aria-pressed={listSort === 'importance'}
                  onClick={() => setListSort('importance')}
                  type="button"
                >
                  {t('mail.sort.importance')}
                </button>
                <button
                  aria-pressed={listSort === 'newest'}
                  onClick={() => setListSort('newest')}
                  type="button"
                >
                  {t('mail.sort.newest')}
                </button>
              </div>
            </section>

            <section aria-labelledby="mail-search-heading" className="mail-panel mail-search-panel">
              <div className="section-heading">
                <h2 id="mail-search-heading">{t('mail.search.heading')}</h2>
              </div>
              <form className="mail-search-form" onSubmit={handleSearch}>
                <input
                  aria-label={t('mail.search.label')}
                  onChange={(event) => setSearchText(event.target.value)}
                  placeholder={t('mail.search.placeholder')}
                  value={searchText}
                />
                <select
                  aria-label={t('mail.pageSize')}
                  onChange={(event) => setPageSize(Number(event.target.value))}
                  value={pageSize}
                >
                  <option value={10}>10</option>
                  <option value={25}>25</option>
                  <option value={50}>50</option>
                </select>
                <div className="mail-search-actions">
                  <button disabled={isBusy} type="submit">
                    {t('mail.search.submit')}
                  </button>
                  <button disabled={isBusy || !isSearchMode} onClick={clearSearch} type="button">
                    {t('mail.search.clear')}
                  </button>
                </div>
              </form>
            </section>
          </aside>
        </div>
      </div>
    </main>
  )
}

export default MailView
