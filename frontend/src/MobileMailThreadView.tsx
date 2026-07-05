import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { t } from './i18n'
import { AppLink } from './navigation'
import { getMailDetail, processMail, updateMailImportance } from './phase4Api'
import type { MailDetail, MailThreadMessage } from './phase4Api'
import './MobileTopView.css'
import './MobileMailDayView.css'
import './MobileMailThreadView.css'

type MobileMailThreadViewProps = {
  messageId: string
}

const importanceOptions = ['high', 'middle', 'low', 'skip'] as const

function formatDateTime(value: string) {
  return value.replace('T', ' ').replace('+09:00', ' JST')
}

function formatDateLabel(value: string) {
  const [date] = value.split('T')
  const [year, month, day] = date.split('-')
  return `${year}年${Number(month)}月${Number(day)}日`
}

function receivedDate(value: string) {
  return value.slice(0, 10)
}

function isSentMessage(message: MailThreadMessage) {
  return (
    message.effective_importance === 'sent' ||
    (message.gmail_labels ?? []).some((label) => label.toLowerCase() === 'sent')
  )
}

function senderDisplayName(message: MailThreadMessage) {
  return message.sender_contact?.display_name ?? message.from_name ?? message.from_address
}

function mailBody(message: MailThreadMessage) {
  return message.body_text ?? message.snippet ?? ''
}

function displayImportance(value: string) {
  const labels: Record<string, string> = {
    pending: t('mail.importance.bug'),
    pinned: 'Pinned',
    high: t('mail.importance.high'),
    middle: t('mail.importance.middle'),
    low: t('mail.importance.low'),
    skip: t('mail.importance.skip'),
    unclassified: t('mail.importance.unclassified'),
    sent: t('mail.importance.sent'),
  }
  return labels[value] ?? value
}

const urlPattern = /(https?:\/\/[^\s<>"']+|www\.[^\s<>"']+)/gi
const trailingUrlPunctuationPattern = /[.,;:!?、。．，）)\]}」』】]+$/

function urlHref(url: string) {
  return url.toLowerCase().startsWith('www.') ? `https://${url}` : url
}

function linkifiedNodes(text: string): ReactNode[] {
  const nodes: ReactNode[] = []
  const matcher = new RegExp(urlPattern)
  let lastIndex = 0
  for (const match of text.matchAll(matcher)) {
    const rawUrl = match[0]
    const matchIndex = match.index ?? 0
    const trailing = rawUrl.match(trailingUrlPunctuationPattern)?.[0] ?? ''
    const matchedUrl = rawUrl.slice(0, rawUrl.length - trailing.length)
    if (matchIndex > lastIndex) nodes.push(text.slice(lastIndex, matchIndex))
    nodes.push(
      <a href={urlHref(matchedUrl)} key={`${matchIndex}-${matchedUrl}`} rel="noreferrer" target="_blank">
        {matchedUrl.length > 34 ? `${matchedUrl.slice(0, 33)}...` : matchedUrl}
      </a>,
    )
    if (trailing !== '') nodes.push(trailing)
    lastIndex = matchIndex + rawUrl.length
  }
  if (lastIndex < text.length) nodes.push(text.slice(lastIndex))
  return nodes.length > 0 ? nodes : [text]
}

function LinkifiedText({ text }: { text: string }) {
  return <>{linkifiedNodes(text)}</>
}


type SplitBody = {
  mainText: string
  quotedText: string | null
}

function looksLikeQuotedReplyIntro(line: string) {
  const trimmed = line.trim()
  const japaneseGmailReplyIntro =
    /\d{4}年\d{1,2}月\d{1,2}日(?:\([^)]+\))?\s+\d{1,2}:\d{2}\s+[^<\n]+<[^<>@\s]+@[^<>@\s]+>:/
  const slashDateGmailReplyIntro =
    /\d{4}\/\d{1,2}\/\d{1,2}(?:\([^)]+\))?\s+\d{1,2}:\d{2}\s+[^<\n]+<[^<>@\s]+@[^<>@\s]+>:/
  return /^On .+ wrote:$/i.test(trimmed) || japaneseGmailReplyIntro.test(trimmed) || slashDateGmailReplyIntro.test(trimmed)
}

function looksLikeOriginalMessageDivider(line: string) {
  const trimmed = line.trim()
  return /^[-_]{2,}\s*Original Message\s*[-_]{2,}$/i.test(trimmed)
    || /^[-_]{2,}\s*Forwarded message\s*[-_]{2,}$/i.test(trimmed)
    || /^差出人\s*:\s*.+<[^<>@\s]+@[^<>@\s]+>$/i.test(trimmed)
    || /^From\s*:\s*.+<[^<>@\s]+@[^<>@\s]+>$/i.test(trimmed)
    || /^送信日時\s*:\s*.+$/i.test(trimmed)
    || /^Sent\s*:\s*.+$/i.test(trimmed)
}

function splitQuotedReply(text: string): SplitBody {
  const lines = text.split('\n')
  const quoteStartIndex = lines.findIndex((line) => {
    const trimmed = line.trimStart()
    return trimmed.startsWith('>') || looksLikeOriginalMessageDivider(line) || looksLikeQuotedReplyIntro(line)
  })
  if (quoteStartIndex <= 0) return { mainText: text, quotedText: null }
  const mainText = lines.slice(0, quoteStartIndex).join('\n').trimEnd()
  const quotedText = lines.slice(quoteStartIndex).join('\n').trim()
  if (mainText === '' || quotedText === '') return { mainText: text, quotedText: null }
  return { mainText, quotedText }
}

function BodyPre({ text, className = '' }: { text: string; className?: string }) {
  return (
    <pre className={`mobile-mail-detail-body ${className}`.trim()}>
      <LinkifiedText text={text} />
    </pre>
  )
}

function MobileMailBody({ message }: { message: MailThreadMessage }) {
  const body = mailBody(message).trim()
  if (body === '') {
    return <p className="mobile-mail-detail-empty">{t('mail.thread.noBody')}</p>
  }
  const splitBody = splitQuotedReply(body)
  if (splitBody.quotedText === null) return <BodyPre text={body} />
  return (
    <>
      <BodyPre text={splitBody.mainText} />
      <details className="mobile-mail-detail-quoted">
        <summary>{t('mobile.mail.replySource')}</summary>
        <BodyPre className="is-quoted" text={splitBody.quotedText} />
      </details>
    </>
  )
}

export default function MobileMailThreadView({ messageId }: MobileMailThreadViewProps) {
  const [detail, setDetail] = useState<MailDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busyAction, setBusyAction] = useState<string | null>(null)
  const [feedback, setFeedback] = useState<string | null>(null)

  useEffect(() => {
    let isMounted = true
    setError(null)
    getMailDetail(messageId)
      .then((nextDetail) => {
        if (isMounted) setDetail(nextDetail)
      })
      .catch((requestError) => {
        if (isMounted) setError(requestError instanceof Error ? requestError.message : t('mobile.mail.detailLoadFailed'))
      })
    return () => {
      isMounted = false
    }
  }, [messageId])

  const threadMessages = useMemo(
    () => [...(detail?.thread_messages ?? [])].sort((left, right) => right.received_at.localeCompare(left.received_at)),
    [detail],
  )
  const backDate = detail?.message.received_date ?? detail?.message.received_at.slice(0, 10) ?? ''

  async function completeMessage(message: MailThreadMessage) {
    setBusyAction(`${message.id}-complete`)
    setError(null)
    setFeedback(null)
    try {
      const nextDetail = await processMail(message.id)
      setDetail(nextDetail)
      setFeedback(t('mobile.mail.completeDone'))
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('mobile.mail.completeFailed'))
    } finally {
      setBusyAction(null)
    }
  }

  async function changeImportance(message: MailThreadMessage, importance: (typeof importanceOptions)[number]) {
    setBusyAction(`${message.id}-${importance}`)
    setError(null)
    setFeedback(null)
    try {
      const nextDetail = await updateMailImportance(message.id, importance)
      setDetail(nextDetail)
      setFeedback(t('mobile.mail.importanceDone'))
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('mobile.mail.importanceFailed'))
    } finally {
      setBusyAction(null)
    }
  }

  return (
    <main className="mobile-shell mobile-mail-detail-shell">
      <header className="mobile-topbar mobile-mail-topbar">
        <div>
          <p>{t('mail.heading')}</p>
          <h1>{detail?.message.subject ?? t('mail.detail.heading')}</h1>
        </div>
        <AppLink className="mobile-topbar-link" href={backDate === '' ? '/m/mail' : `/m/mail?date=${backDate}`}>
          {t('common.backToList')}
        </AppLink>
      </header>

      {error !== null && <p className="mobile-alert" role="alert">{error}</p>}
      {feedback !== null && <p className="mobile-alert mobile-alert-success">{feedback}</p>}
      {detail === null && error === null ? <p className="mobile-loading">{t('common.loading')}</p> : null}

      {detail !== null ? (
        <>
          <section className="mobile-panel mobile-mail-thread-summary-panel">
            <h2>{t('mail.thread.summary')}</h2>
            {detail.summary === null ? (
              <p>{t('mobile.mail.threadSummaryEmpty')}</p>
            ) : (
              <p><LinkifiedText text={detail.summary.summary_text} /></p>
            )}
          </section>
          <section className="mobile-mail-thread-list" aria-label={t('mail.thread.messages')}>
          {threadMessages.map((message, index) => {
            const isSent = isSentMessage(message)
            const showDateDivider = index === 0 || receivedDate(message.received_at) !== receivedDate(threadMessages[index - 1].received_at)
            const isProcessed = message.processed_status === 'processed'
            const messageSummary = detail.summary?.items?.find((summary) => summary.message_id === message.id)
            const hasActiveSummaryJob = detail.summary_jobs?.[message.id] !== undefined
            return (
              <div className="mobile-mail-thread-entry" key={message.id}>
                {showDateDivider ? (
                  <div className="mobile-mail-thread-date">
                    <span>{formatDateLabel(message.received_at)}</span>
                  </div>
                ) : null}
                <article className={`mobile-mail-detail-message ${isSent ? 'is-sent' : 'is-received'}`}>
                  <header>
                    <div>
                      <span>{formatDateTime(message.received_at)}</span>
                      <h2>{message.subject ?? t('mail.noSubject')}</h2>
                      <p>{isSent ? t('mobile.mail.sentMail') : senderDisplayName(message)}</p>
                    </div>
                    <strong className={`mobile-mail-detail-importance importance-${message.effective_importance}`}>
                      {displayImportance(message.effective_importance)}
                    </strong>
                  </header>

                  {!isSent ? (
                    <div className="mobile-mail-detail-actions" aria-label={t('mail.thread.navLabel')}>
                      <button
                        className="mobile-mail-complete-button button-loading-dot"
                        disabled={busyAction !== null || isProcessed}
                        onClick={() => void completeMessage(message)}
                        type="button"
                      >
                        {isProcessed ? t('pomodoro.completed') : t('mail.thread.action.done')}
                      </button>
                      <div className="mobile-mail-importance-buttons" aria-label={t('mail.importanceLegend.label')}>
                        {importanceOptions.map((importance) => (
                          <button
                            aria-pressed={message.effective_importance === importance}
                            disabled={busyAction !== null}
                            key={importance}
                            onClick={() => void changeImportance(message, importance)}
                            type="button"
                          >
                            {displayImportance(importance)}
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : null}

                  {(message.attachments ?? []).length > 0 ? (
                    <div className="mobile-mail-detail-attachments">
                      {(message.attachments ?? []).map((attachment) => (
                        <a href={attachment.download_url} key={attachment.id} rel="noreferrer" target="_blank">
                          {attachment.filename}
                        </a>
                      ))}
                    </div>
                  ) : null}

                  {messageSummary !== undefined ? (
                    <section className="mobile-mail-message-summary">
                      <h3>{t('mail.thread.mailSummary')}</h3>
                      <p><LinkifiedText text={messageSummary.summary_text} /></p>
                    </section>
                  ) : null}

                  {hasActiveSummaryJob ? (
                    <section className="mobile-mail-message-summary is-progress">
                      <h3>{t('mail.thread.mailSummary')}</h3>
                      <p>{t('mobile.mail.summaryGenerating')}</p>
                    </section>
                  ) : null}

                  {messageSummary === undefined ? (
                    <MobileMailBody message={message} />
                  ) : (
                    <details className="mobile-mail-detail-original">
                      <summary>{t('mail.thread.originalBody')}</summary>
                      <MobileMailBody message={message} />
                    </details>
                  )}
                </article>
              </div>
            )
          })}
          </section>
        </>
      ) : null}
    </main>
  )
}
