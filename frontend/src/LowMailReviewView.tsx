import { useEffect, useState } from 'react'
import { logout } from './authApi'
import { readUiLanguage, t } from './i18n'
import { navigateTo } from './navigation'
import {
  getLowMailReviewDetail,
  listTodayLowMailReview,
  promoteReviewMailToMiddle,
} from './phase4Api'
import type { LowMailReviewItem } from './phase4Api'

function senderLabel(mail: LowMailReviewItem) {
  return mail.sender_contact?.display_name || mail.from_name || mail.from_address
}

function receivedTime(value: string) {
  return value.slice(11, 16)
}

function mailBody(mail: LowMailReviewItem) {
  return mail.body_text?.trim() || mail.snippet?.trim() || t('mail.review.noBody')
}

function mailPreview(mail: LowMailReviewItem) {
  return mail.summary?.trim() || mail.snippet?.trim() || t('mail.review.noBody')
}

function dateLabel(date: string) {
  if (date === '') return ''
  return new Intl.DateTimeFormat(readUiLanguage() === 'ja' ? 'ja-JP' : 'en-US', {
    dateStyle: 'full',
    timeZone: 'Asia/Tokyo',
  }).format(new Date(`${date}T12:00:00+09:00`))
}

async function handleLogout() {
  try {
    await logout()
  } finally {
    window.location.assign('/')
  }
}

function ReviewHeader({
  date,
  detail = false,
}: {
  date: string
  detail?: boolean
}) {
  return (
    <header className="low-mail-review-header">
      <div>
        <p>{t('app.name')}</p>
        <h1>{detail ? t('mail.review.detailHeading') : t('mail.review.heading')}</h1>
        <span>{dateLabel(date)}</span>
      </div>
      <div className="low-mail-review-header-actions">
        {detail && (
          <button onClick={() => navigateTo('/mail/review')} type="button">
            {t('common.backToList')}
          </button>
        )}
        <button onClick={() => void handleLogout()} type="button">
          {t('mail.review.logout')}
        </button>
      </div>
    </header>
  )
}

export default function LowMailReviewView() {
  const [date, setDate] = useState('')
  const [items, setItems] = useState<LowMailReviewItem[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let canceled = false
    void listTodayLowMailReview()
      .then((page) => {
        if (canceled) return
        setDate(page.date)
        setItems(page.items)
      })
      .catch((requestError) => {
        if (!canceled) {
          setError(requestError instanceof Error ? requestError.message : t('mail.review.loadFailed'))
        }
      })
      .finally(() => {
        if (!canceled) setIsLoading(false)
      })
    return () => {
      canceled = true
    }
  }, [])

  return (
    <main className="low-mail-review-shell">
      <ReviewHeader date={date} />
      {error !== null && <p className="low-mail-review-error" role="alert">{error}</p>}
      {isLoading ? (
        <p className="low-mail-review-state">{t('common.loading')}</p>
      ) : items.length === 0 ? (
        <section className="low-mail-review-empty">
          <h2>{t('mail.review.emptyHeading')}</h2>
          <p>{t('mail.review.emptyBody')}</p>
        </section>
      ) : (
        <section aria-label={t('mail.review.listLabel')} className="low-mail-review-list">
          {items.map((mail) => (
            <button
              className="low-mail-review-list-item"
              key={mail.id}
              onClick={() => navigateTo(`/mail/review/${encodeURIComponent(mail.id)}`)}
              type="button"
            >
              <span className="low-mail-review-list-item-header">
                <span>
                  <strong>{senderLabel(mail)}</strong>
                  <small>{mail.from_address}</small>
                </span>
                <span className="low-mail-review-meta">
                  <span className={`low-mail-review-importance is-${mail.effective_importance}`}>
                    {mail.effective_importance === 'skip'
                      ? t('mail.importance.skip')
                      : t('mail.importance.low')}
                  </span>
                  <time dateTime={mail.received_at}>{receivedTime(mail.received_at)}</time>
                </span>
              </span>
              <strong className="low-mail-review-list-subject">
                {mail.subject || t('mobile.noTitle')}
              </strong>
              <span className="low-mail-review-preview">{mailPreview(mail)}</span>
            </button>
          ))}
        </section>
      )}
    </main>
  )
}

export function LowMailReviewDetailView({ messageId }: { messageId: string }) {
  const [mail, setMail] = useState<LowMailReviewItem | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isBusy, setIsBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let canceled = false
    void getLowMailReviewDetail(messageId)
      .then((item) => {
        if (!canceled) setMail(item)
      })
      .catch((requestError) => {
        if (!canceled) {
          setError(requestError instanceof Error ? requestError.message : t('mail.review.loadFailed'))
        }
      })
      .finally(() => {
        if (!canceled) setIsLoading(false)
      })
    return () => {
      canceled = true
    }
  }, [messageId])

  async function promote() {
    if (mail === null) return
    setIsBusy(true)
    setError(null)
    try {
      await promoteReviewMailToMiddle(mail.id)
      navigateTo('/mail/review', true)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('mail.review.promoteFailed'))
      setIsBusy(false)
    }
  }

  return (
    <main className="low-mail-review-shell">
      <ReviewHeader date={mail?.received_at.slice(0, 10) ?? ''} detail />
      {error !== null && <p className="low-mail-review-error" role="alert">{error}</p>}
      {isLoading ? (
        <p className="low-mail-review-state">{t('common.loading')}</p>
      ) : mail !== null ? (
        <article className="low-mail-review-card low-mail-review-detail">
          <header>
            <div>
              <strong>{senderLabel(mail)}</strong>
              <span>{mail.from_address}</span>
            </div>
            <div className="low-mail-review-meta">
              <span className={`low-mail-review-importance is-${mail.effective_importance}`}>
                {mail.effective_importance === 'skip'
                  ? t('mail.importance.skip')
                  : t('mail.importance.low')}
              </span>
              <time dateTime={mail.received_at}>{receivedTime(mail.received_at)}</time>
            </div>
          </header>
          <h2>{mail.subject || t('mobile.noTitle')}</h2>
          <div className="low-mail-review-body">{mailBody(mail)}</div>
          <footer>
            <button disabled={isBusy} onClick={() => void promote()} type="button">
              {t('mail.review.promoteToMiddle')}
            </button>
          </footer>
        </article>
      ) : null}
    </main>
  )
}
