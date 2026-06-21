import { useEffect, useMemo, useState } from 'react'
import type { FollowUp, FollowUpStatus } from './followUpsApi'
import {
  dismissFollowUp,
  listFollowUps,
  resolveFollowUp,
  snoozeFollowUp,
} from './followUpsApi'
import { t } from './i18n'
import { AppLink, TopNav } from './navigation'

type FollowUpTab = FollowUpStatus | 'all'

const tabs: FollowUpTab[] = ['active', 'resolved', 'dismissed', 'all']
const tabLabelKeys = {
  active: 'followUps.tab.active',
  resolved: 'followUps.tab.resolved',
  dismissed: 'followUps.tab.dismissed',
  all: 'followUps.tab.all',
} as const

const statusLabelKeys = {
  active: 'followUps.status.active',
  resolved: 'followUps.status.resolved',
  dismissed: 'followUps.status.dismissed',
} as const

function describeError(error: unknown) {
  return error instanceof Error ? error.message : t('app.requestFailed')
}

function initialTabFromUrl(): FollowUpTab {
  const tab = new URLSearchParams(window.location.search).get('status')
  return tabs.includes(tab as FollowUpTab) ? (tab as FollowUpTab) : 'active'
}

function formatDateTime(value: string | null) {
  if (value === null || value === '') return t('common.none')
  return value.replace('T', ' ').replace(/\.\d+.*$/, '')
}

function addDaysToDate(date: string, days: number) {
  const base = date === '' ? new Date() : new Date(`${date}T00:00:00+09:00`)
  base.setDate(base.getDate() + days)
  return base.toISOString().slice(0, 10)
}

function todayJstDate() {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Tokyo',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
    .formatToParts(new Date())
    .reduce<Record<string, string>>((dateParts, part) => {
      dateParts[part.type] = part.value
      return dateParts
    }, {})
  return `${parts.year}-${parts.month}-${parts.day}`
}

function FollowUpCard({
  item,
  onChange,
}: {
  item: FollowUp
  onChange: (item: FollowUp) => void
}) {
  const [isBusy, setIsBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [snoozeDate, setSnoozeDate] = useState(item.due_on)

  async function runAction(action: () => Promise<FollowUp>) {
    setIsBusy(true)
    setError(null)
    try {
      onChange(await action())
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsBusy(false)
    }
  }

  async function handleDismiss() {
    await runAction(() => dismissFollowUp(item.id))
  }

  const subject = item.message?.subject?.trim() || t('mail.noSubject')
  const fromLabel =
    item.message === null
      ? t('common.none')
      : item.message.from_name?.trim() || item.message.from_address

  return (
    <article className="follow-up-card" data-status={item.status}>
      <div className="follow-up-card-main">
        <div className="follow-up-date">
          <span>{t('followUps.dueOn')}</span>
          <strong>{item.due_on}</strong>
        </div>
        <div className="follow-up-body">
          <div className="follow-up-title-row">
            {item.message !== null ? (
              <AppLink href={`/mail/${encodeURIComponent(item.message.id)}`}>{subject}</AppLink>
            ) : (
              <strong>{subject}</strong>
            )}
            <span className="follow-up-status">{t(statusLabelKeys[item.status])}</span>
          </div>
          <p>{item.reason}</p>
          <div className="follow-up-meta">
            <span>{fromLabel}</span>
            <span>{formatDateTime(item.message?.received_at ?? null)}</span>
            {item.case_id !== null && (
              <AppLink href={`/cases/${encodeURIComponent(item.case_id)}`}>
                {item.case_name ?? item.case_id}
              </AppLink>
            )}
          </div>
          <div className="follow-up-sample">
            <span>{t('followUps.matchedPhrase')}</span>
            <strong>{item.matched_phrase}</strong>
            {item.message?.snippet !== null && item.message?.snippet !== undefined && (
              <small>{item.message.snippet}</small>
            )}
          </div>
          {item.status === 'dismissed' && item.dismissed_reason !== null && (
            <p className="follow-up-note">
              {t('followUps.dismissedReason')}: {item.dismissed_reason}
            </p>
          )}
          {item.status === 'resolved' && (
            <p className="follow-up-note">
              {t('followUps.resolvedBy')}:{' '}
              {item.resolved_by_message_id !== null ? (
                <AppLink href={`/mail/${encodeURIComponent(item.resolved_by_message_id)}`}>
                  {item.resolved_by_subject ?? item.resolved_by_message_id}
                </AppLink>
              ) : (
                t('common.none')
              )}
            </p>
          )}
          {error !== null && <p className="mail-feedback" role="alert">{error}</p>}
        </div>
      </div>
      {item.status === 'active' && (
        <div className="follow-up-actions">
          <label>
            <span>{t('followUps.snoozeUntil')}</span>
            <input
              onChange={(event) => setSnoozeDate(event.target.value)}
              type="date"
              value={snoozeDate}
            />
          </label>
          <button
            disabled={isBusy || snoozeDate === ''}
            onClick={() => runAction(() => snoozeFollowUp(item.id, snoozeDate))}
            type="button"
          >
            {t('followUps.snooze')}
          </button>
          <button
            disabled={isBusy}
            onClick={() => runAction(() => snoozeFollowUp(item.id, addDaysToDate(item.due_on, 7)))}
            type="button"
          >
            {t('followUps.plus7')}
          </button>
          <button disabled={isBusy} onClick={() => runAction(() => resolveFollowUp(item.id))} type="button">
            {t('followUps.resolve')}
          </button>
          <button disabled={isBusy} onClick={handleDismiss} type="button">
            {t('followUps.dismiss')}
          </button>
        </div>
      )}
    </article>
  )
}

function FollowUpView() {
  const [tab, setTab] = useState<FollowUpTab>(initialTabFromUrl)
  const [items, setItems] = useState<FollowUp[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    params.set('status', tab)
    window.history.replaceState({}, '', `/follow-ups?${params.toString()}`)
  }, [tab])

  useEffect(() => {
    let isMounted = true
    setIsLoading(true)
    setError(null)
    listFollowUps({ status: tab })
      .then((nextItems) => {
        if (isMounted) setItems(nextItems)
      })
      .catch((requestError) => {
        if (isMounted) setError(describeError(requestError))
      })
      .finally(() => {
        if (isMounted) setIsLoading(false)
      })
    return () => {
      isMounted = false
    }
  }, [tab])

  const activeDueCount = useMemo(
    () => items.filter((item) => item.status === 'active' && item.due_on <= todayJstDate()).length,
    [items],
  )

  function updateItem(nextItem: FollowUp) {
    setItems((currentItems) =>
      tab === 'all' || nextItem.status === tab
        ? currentItems.map((item) => (item.id === nextItem.id ? nextItem : item))
        : currentItems.filter((item) => item.id !== nextItem.id),
    )
  }

  return (
    <main className="app-shell">
      <section className="maintenance-shell follow-up-shell">
        <div className="storage-header">
          <div>
            <p>{t('app.name')}</p>
            <h1>{t('followUps.heading')}</h1>
          </div>
          <TopNav
            ariaLabelKey="followUps.navigation"
            items={[
              { href: '/', labelKey: 'top.heading' },
              { href: '/mail', labelKey: 'nav.mail' },
              { href: '/cases', labelKey: 'nav.cases' },
              { href: '/tasks', labelKey: 'nav.tasks' },
              { href: '/calendar', labelKey: 'nav.calendar' },
              { href: '/contacts', labelKey: 'nav.contacts' },
              { href: '/maintenance', labelKey: 'nav.maintenance' },
            ]}
          />
        </div>

        <section className="maintenance-panel-surface follow-up-summary-panel">
          <div>
            <h2>{t('followUps.summary')}</h2>
            <p>{t('followUps.summaryBody')}</p>
          </div>
          <strong>{t('followUps.dueCount', { count: String(activeDueCount) })}</strong>
        </section>

        <section className="maintenance-panel-surface follow-up-list-panel">
          <div className="follow-up-tabs" role="tablist">
            {tabs.map((nextTab) => (
              <button
                aria-selected={tab === nextTab}
                key={nextTab}
                onClick={() => setTab(nextTab)}
                role="tab"
                type="button"
              >
                {t(tabLabelKeys[nextTab])}
              </button>
            ))}
          </div>

          {isLoading && <p>{t('common.loading')}</p>}
          {error !== null && <p className="mail-feedback" role="alert">{error}</p>}
          {!isLoading && error === null && items.length === 0 && (
            <p className="follow-up-empty">{t('followUps.empty')}</p>
          )}
          <div className="follow-up-list">
            {items.map((item) => (
              <FollowUpCard item={item} key={item.id} onChange={updateItem} />
            ))}
          </div>
        </section>
      </section>
    </main>
  )
}

export default FollowUpView
