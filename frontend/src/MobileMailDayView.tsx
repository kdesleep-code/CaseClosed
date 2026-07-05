import { useEffect, useMemo, useRef, useState } from 'react'
import type { TouchEvent } from 'react'
import { t } from './i18n'
import { AppLink } from './navigation'
import needsActionClearTanukiUrl from './assets/needs-action-clear-tanuki.png'
import { listMailPage } from './phase4Api'
import type { MailListItem } from './phase4Api'
import './MobileTopView.css'
import './MobileMailDayView.css'

function jstDateToday() {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Tokyo',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
    .formatToParts(new Date())
    .reduce<Record<string, string>>((values, part) => {
      values[part.type] = part.value
      return values
    }, {})

  return `${parts.year}-${parts.month}-${parts.day}`
}

function validDateOrToday(value: string | null) {
  return value !== null && /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : jstDateToday()
}

function dateParts(date: string) {
  const [year, month, day] = date.split('-').map(Number)
  return { year, month, day }
}

function formatDate(year: number, month: number, day: number) {
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

function addDays(date: string, amount: number) {
  const { year, month, day } = dateParts(date)
  const nextDate = new Date(Date.UTC(year, month - 1, day + amount))
  return formatDate(nextDate.getUTCFullYear(), nextDate.getUTCMonth() + 1, nextDate.getUTCDate())
}

function startOfDate(date: string) {
  return `${date}T00:00:00+09:00`
}

function endOfDate(date: string) {
  return `${date}T23:59:59+09:00`
}

type MobileMailDayViewProps = {
  mode?: 'day' | 'action-needed'
}

function displayDate(date: string) {
  const [year, month, day] = date.split('-').map(Number)
  const value = new Date(Date.UTC(year, month - 1, day))
  return new Intl.DateTimeFormat('ja-JP', {
    timeZone: 'UTC',
    month: 'long',
    day: 'numeric',
    weekday: 'short',
  }).format(value)
}

function formatTime(value: string) {
  return value.length >= 16 ? value.slice(11, 16) : '--:--'
}

function senderDisplayName(mail: MailListItem) {
  return mail.sender_contact?.display_name ?? mail.from_name ?? mail.from_address
}

function shortSummary(mail: MailListItem) {
  const summary = mail.summary?.trim()
  if (summary === undefined || summary === '') return null
  return summary.length > 120 ? `${summary.slice(0, 119)}...` : summary
}

function isSkipMail(mail: MailListItem) {
  return mail.effective_importance === 'skip'
}

function isDoneMail(mail: MailListItem) {
  return mail.processed_status === 'processed' && !isSkipMail(mail)
}

function importanceRank(mail: MailListItem) {
  if (isDoneMail(mail)) return 200
  if (isSkipMail(mail)) return 100
  if (typeof mail.importance_rank === 'number') return mail.importance_rank
  const rank: Record<string, number> = {
    pending: -1,
    pinned: 0,
    high: 1,
    middle: 2,
    low: 3,
    unclassified: 4,
    sent: 5,
  }
  return rank[mail.effective_importance] ?? 50
}

function bucketKey(mail: MailListItem) {
  if (isDoneMail(mail)) return 'done'
  if (isSkipMail(mail)) return 'skip'
  return mail.effective_importance
}

function bucketLabel(key: string) {
  const labels: Record<string, string> = {
    pending: t('mail.importance.bug'),
    pinned: 'Pinned',
    high: t('mail.importance.high'),
    middle: t('mail.importance.middle'),
    low: t('mail.importance.low'),
    unclassified: t('mail.importance.unclassified'),
    sent: t('mail.importance.sent'),
    skip: t('mail.importance.skip'),
    done: t('mail.tab.processed'),
  }
  return labels[key] ?? key
}

function mailDateLabel(mail: MailListItem) {
  return mail.received_date ?? mail.received_at.slice(0, 10)
}

function sortActionNeededMails(mails: MailListItem[]) {
  return [...mails].sort(
    (left, right) =>
      right.received_at.localeCompare(left.received_at) ||
      importanceRank(left) - importanceRank(right) ||
      left.id.localeCompare(right.id),
  )
}

function sortMails(mails: MailListItem[]) {
  return [...mails].sort((left, right) => {
    const rankDiff = importanceRank(left) - importanceRank(right)
    if (rankDiff !== 0) return rankDiff
    return right.received_at.localeCompare(left.received_at) || left.id.localeCompare(right.id)
  })
}

function shouldShowImportanceGroup(mail: MailListItem, index: number, mails: MailListItem[]) {
  return index === 0 || bucketKey(mail) !== bucketKey(mails[index - 1])
}

function shouldShowDateGroup(mail: MailListItem, index: number, mails: MailListItem[]) {
  return index === 0 || mailDateLabel(mail) !== mailDateLabel(mails[index - 1])
}

async function listActionNeededMails() {
  const items: MailListItem[] = []
  let cursor: string | undefined
  for (let pageIndex = 0; pageIndex < 10; pageIndex += 1) {
    const page = await listMailPage({
      tab: 'all',
      needs_action: true,
      limit: 100,
      cursor,
    })
    items.push(...page.items)
    if (page.next_cursor === null) break
    cursor = page.next_cursor
  }
  return items
}

async function listAllDayMails(date: string) {
  const items: MailListItem[] = []
  let cursor: string | undefined
  for (let pageIndex = 0; pageIndex < 10; pageIndex += 1) {
    const page = await listMailPage({
      tab: 'all',
      date_from: startOfDate(date),
      date_to: endOfDate(date),
      limit: 100,
      cursor,
    })
    items.push(...page.items)
    if (page.next_cursor === null) break
    cursor = page.next_cursor
  }
  return items
}

export default function MobileMailDayView({ mode = 'day' }: MobileMailDayViewProps) {
  const today = useMemo(() => jstDateToday(), [])
  const isActionNeededMode = mode === 'action-needed'
  const [date, setDate] = useState(() => validDateOrToday(new URLSearchParams(window.location.search).get('date')))
  const [mails, setMails] = useState<MailListItem[]>([])
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const touchStartXRef = useRef<number | null>(null)
  const touchStartYRef = useRef<number | null>(null)

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (isActionNeededMode) return
    if (params.get('date') !== date) {
      params.set('date', date)
      window.history.replaceState({}, '', `/m/mail?${params.toString()}`)
    }
  }, [date, isActionNeededMode])

  useEffect(() => {
    let isMounted = true
    setIsLoading(true)
    setError(null)
    const request = isActionNeededMode ? listActionNeededMails() : listAllDayMails(date)
    request
      .then((items) => {
        if (isMounted) setMails(isActionNeededMode ? sortActionNeededMails(items) : sortMails(items))
      })
      .catch((requestError) => {
        if (isMounted) setError(requestError instanceof Error ? requestError.message : t('mobile.mail.loadFailed'))
      })
      .finally(() => {
        if (isMounted) setIsLoading(false)
      })
    return () => {
      isMounted = false
    }
  }, [date, isActionNeededMode])

  function moveDate(amount: number) {
    if (isActionNeededMode) return
    setDate((current) => addDays(current, amount))
  }

  function handleTouchStart(event: TouchEvent<HTMLElement>) {
    const touch = event.touches[0]
    touchStartXRef.current = touch.clientX
    touchStartYRef.current = touch.clientY
  }

  function handleTouchEnd(event: TouchEvent<HTMLElement>) {
    const startX = touchStartXRef.current
    const startY = touchStartYRef.current
    touchStartXRef.current = null
    touchStartYRef.current = null
    if (startX === null || startY === null) return
    const touch = event.changedTouches[0]
    const dx = touch.clientX - startX
    const dy = touch.clientY - startY
    if (Math.abs(dx) < 54 || Math.abs(dx) < Math.abs(dy) * 1.4) return
    moveDate(dx < 0 ? 1 : -1)
  }

  return (
    <main className="mobile-shell mobile-mail-shell" onTouchEnd={handleTouchEnd} onTouchStart={handleTouchStart}>
      <header className="mobile-topbar mobile-mail-topbar">
        <div>
          <p>{t('mail.heading')}</p>
          <h1>{isActionNeededMode ? t('mail.actionNeeded.heading') : displayDate(date)}</h1>
        </div>
        <AppLink className="mobile-topbar-link" href="/m?view=mobile">
          {t('top.heading')}
        </AppLink>
      </header>

      {!isActionNeededMode ? (
        <>
          <nav aria-label="Day navigation" className="mobile-day-switcher">
            <button type="button" onClick={() => moveDate(-1)}>{t('common.previousDay')}</button>
            <button type="button" onClick={() => setDate(today)}>{t('calendar.today')}</button>
            <button type="button" onClick={() => moveDate(1)}>{t('common.nextDay')}</button>
          </nav>

          <p className="mobile-swipe-hint">{t('mobile.swipeDayHint')}</p>
        </>
      ) : null}

      {error !== null && <p className="mobile-alert" role="alert">{error}</p>}
      {isLoading ? <p className="mobile-loading">{t('common.loading')}</p> : null}

      {!isLoading && error === null && mails.length === 0 ? (
        <section className={`mobile-panel${isActionNeededMode ? ' mobile-mail-action-empty' : ''}`}>
          {isActionNeededMode ? (
            <img alt={t('mail.actionNeeded.emptyAlt')} src={needsActionClearTanukiUrl} />
          ) : null}
          <p className="mobile-empty">{isActionNeededMode ? t('mobile.mail.actionNeededEmpty') : t('mobile.mail.emptyDay')}</p>
        </section>
      ) : null}

      {!isLoading && error === null && mails.length > 0 ? (
        <section className="mobile-mail-list" aria-label="Mail list">
          {mails.map((mail, index) => {
            const groupKey = bucketKey(mail)
            const summary = shortSummary(mail)
            return (
              <div className="mobile-mail-entry" key={mail.id}>
                {isActionNeededMode ? (
                  shouldShowDateGroup(mail, index, mails) ? (
                    <div className={`mobile-mail-group group-${groupKey}`}>
                      <span>{mailDateLabel(mail)}</span>
                    </div>
                  ) : null
                ) : shouldShowImportanceGroup(mail, index, mails) ? (
                  <div className={`mobile-mail-group group-${groupKey}`}>
                    <span>{bucketLabel(groupKey)}</span>
                  </div>
                ) : null}
                <AppLink
                  className={`mobile-mail-card group-${groupKey} read-${mail.read_status ?? 'unread'}`}
                  href={`/m/mail/${encodeURIComponent(mail.id)}?date=${mailDateLabel(mail)}`}
                >
                  <div className="mobile-mail-card-head">
                    <time>{formatTime(mail.received_at)}</time>
                    <span>{bucketLabel(groupKey)}</span>
                  </div>
                  <strong>{mail.subject ?? t('mail.noSubject')}</strong>
                  <p>{senderDisplayName(mail)}</p>
                  {summary !== null ? <p className="mobile-mail-summary">{summary}</p> : null}
                  <div className="mobile-mail-meta">
                    {mail.has_attachments === true || (mail.attachment_count ?? 0) > 0 ? <span>{t('mail.thread.attachments')}</span> : null}
                    {mail.llm_blocked === true ? <span>{t('mail.llmBlocked')}</span> : null}
                    {mail.processed_status === 'processed' ? <span>{t('mail.tab.processed')}</span> : null}
                  </div>
                </AppLink>
              </div>
            )
          })}
        </section>
      ) : null}

      <nav aria-label="Mobile navigation" className="mobile-nav-grid">
        <AppLink href="/m?view=mobile">{t('top.heading')}</AppLink>
        <AppLink href={`/m/calendar?date=${date}`}>{t('calendar.heading')}</AppLink>
        <AppLink href={isActionNeededMode ? '/mail/action-needed' : `/mail?date=${date}`}>PC {t('mail.heading')}</AppLink>
      </nav>
    </main>
  )
}
