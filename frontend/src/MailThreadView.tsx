import { Fragment, useEffect, useRef, useState } from 'react'
import { t } from './i18n'
import type { MessageKey } from './i18n'
import { AppLink, navigateTo } from './navigation'
import defaultContactAvatarUrl from './assets/default-contact-avatar.svg'
import defaultMailingListAvatarUrl from './assets/default-mailing-list-avatar.svg'
import unknownContactAvatarUrl from './assets/default-unknown-contact-avatar.svg'
import {
  cancelMailSendRequest,
  getMailDetail,
  markMailRead,
  processMail,
  requestMailSummary,
  rescheduleMailRequest,
  sendMailRequestNow,
  unprocessMail,
  updateMailImportance,
} from './phase4Api'
import type { MailDetail, MailSendRequest, MailThreadMessage } from './phase4Api'
import type { MailRecipient } from './phase4Api'

type MailThreadViewProps = {
  messageId: string
}

function describeError(error: unknown) {
  return error instanceof Error ? error.message : t('mail.requestFailed')
}

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

function recipientsFor(addresses: string[], recipients?: MailRecipient[]) {
  if (recipients !== undefined) {
    return recipients
  }
  return addresses.map((emailAddress) => ({
    email_address: emailAddress,
    contact: null,
  }))
}

function senderRecipient(message: MailThreadMessage): MailRecipient {
  return {
    email_address: message.from_address,
    contact: message.from_contact ?? message.sender_contact ?? null,
  }
}

function isSentMessage(message: MailThreadMessage) {
  return (message.gmail_labels ?? []).some((label) => label.toLowerCase() === 'sent')
}

function mailBody(message: MailThreadMessage) {
  return message.body_text ?? message.snippet ?? ''
}

function composeReplyBody(message: MailThreadMessage) {
  const quotedBody = mailBody(message)
    .split('\n')
    .map((line) => `> ${line}`)
    .join('\n')
  return `On ${formatDateTime(message.received_at)}, ${message.from_address} wrote:\n${quotedBody}`
}

function composeFollowUpBody(message: MailThreadMessage) {
  const quotedBody = mailBody(message)
    .split('\n')
    .map((line) => `> ${line}`)
    .join('\n')
  return `On ${formatDateTime(message.received_at)}, I wrote:\n${quotedBody}`
}

function replyHrefFor(message: MailThreadMessage) {
  const params = new URLSearchParams({
    to: message.reply_to_address ?? message.from_address,
    subject: message.subject ?? '',
    auto_body: composeReplyBody(message),
    reply_to_message_id: message.id,
  })
  const ccRecipients = recipientsFor(message.cc_addresses, message.cc_recipients)
  const ccAddresses = ccRecipients.map((recipient) => recipient.email_address)
  if (ccAddresses.length > 0) {
    params.set('cc', ccAddresses.join(', '))
  }
  return `/mail/compose?${params.toString()}`
}

function composeAddressesHrefFor(
  message: MailThreadMessage,
  body: string,
  bodyMode: 'manual' | 'auto',
) {
  const params = new URLSearchParams({
    to: message.to_addresses.join(', '),
    subject: message.subject ?? '',
  })
  params.set(bodyMode === 'manual' ? 'manual_body' : 'auto_body', body)
  if (message.cc_addresses.length > 0) {
    params.set('cc', message.cc_addresses.join(', '))
  }
  if (message.bcc_addresses.length > 0) {
    params.set('bcc', message.bcc_addresses.join(', '))
  }
  return `/mail/compose?${params.toString()}`
}

function resendHrefFor(message: MailThreadMessage) {
  return composeAddressesHrefFor(message, mailBody(message), 'manual')
}

function followUpHrefFor(message: MailThreadMessage) {
  return composeAddressesHrefFor(message, composeFollowUpBody(message), 'auto')
}

function scheduledAtLocalValue(sendRequest: MailSendRequest) {
  return (sendRequest.scheduled_at ?? sendRequest.created_at).slice(0, 16)
}

function localDateTimeToJstIso(value: string) {
  return value.length === 16 ? `${value}:00+09:00` : value
}

function isBugImportance(importance: string) {
  return importance === 'pending'
}

const importanceLabelKeys = {
  high: 'mail.importance.high',
  middle: 'mail.importance.middle',
  low: 'mail.importance.low',
  skip: 'mail.importance.skip',
  unclassified: 'mail.importance.unclassified',
} satisfies Record<'high' | 'middle' | 'low' | 'skip' | 'unclassified', MessageKey>

const incomingActionKeys = [
  'mail.thread.action.done',
  'mail.thread.action.reply',
  'mail.thread.action.calendar',
  'mail.thread.action.task',
  'mail.thread.action.smart',
  'mail.thread.action.summary',
] satisfies MessageKey[]

const outgoingActionKeys = [
  'mail.thread.action.followUp',
  'mail.thread.action.resend',
  'mail.thread.action.calendar',
  'mail.thread.action.task',
  'mail.thread.action.smart',
] as const

type IncomingAction = {
  id: string
  label: string
  disabled: boolean
  title: string
  className?: string
  onClick: () => void
}

type ThreadEntry =
  | { kind: 'mail'; id: string; at: string; message: MailThreadMessage }
  | { kind: 'scheduled'; id: string; at: string; request: MailSendRequest }

function displayImportance(importance: string) {
  if (importance in importanceLabelKeys) {
    return t(importanceLabelKeys[importance as keyof typeof importanceLabelKeys])
  }
  if (isBugImportance(importance)) {
    return t('mail.importance.bug')
  }
  return importance
}

function llmBlockedTitle(message: { llm_block_reason?: string | null }) {
  return message.llm_block_reason == null || message.llm_block_reason.trim() === ''
    ? t('mail.llmBlockedTitle')
    : t('mail.llmBlockedWithReason', { reason: message.llm_block_reason })
}

function mailListTabFor(message: MailThreadMessage) {
  if (message.effective_importance === 'skip') {
    return 'skip'
  }
  return message.processed_status === 'processed' ? 'processed' : 'unprocessed'
}

function mailListHrefFor(message: MailThreadMessage) {
  const params = new URLSearchParams({
    tab: mailListTabFor(message),
    date: message.received_at.slice(0, 10),
  })
  return `/mail?${params.toString()}`
}

function delay(milliseconds: number) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds))
}

function contactAvatarUrl(contact: MailRecipient['contact']) {
  if (contact === null) {
    return unknownContactAvatarUrl
  }
  return (
    contact.avatar_url ??
    (contact.kind === 'mailing_list'
      ? defaultMailingListAvatarUrl
      : defaultContactAvatarUrl)
  )
}

function recipientLabel(recipient: MailRecipient) {
  return recipient.contact?.display_name ?? recipient.email_address
}

function recipientTags(recipient: MailRecipient) {
  if (recipient.contact === null) {
    return [t('mail.thread.unknownSender')]
  }
  if (recipient.contact.kind === 'mailing_list') {
    return [t('contacts.kind.mailingList')]
  }
  const tags = recipient.contact.tags ?? []
  return tags.length > 0 ? tags.slice(0, 2) : [t('contacts.kind.person')]
}

function SenderCard({ recipient }: { recipient: MailRecipient }) {
  const label = recipientLabel(recipient)
  const href =
    recipient.contact === null
      ? `/contacts?new_email=${encodeURIComponent(
          recipient.email_address,
        )}&display_name=${encodeURIComponent(label)}`
      : `/contacts?contact_id=${encodeURIComponent(recipient.contact.id)}`

  return (
    <button
      className="mail-thread-sender-card"
      onClick={() => navigateTo(href)}
      type="button"
    >
      <img
        alt={t(
          recipient.contact === null
            ? 'mail.unknownContactAvatarAlt'
            : 'mail.senderAvatarAlt',
          { name: label },
        )}
        src={contactAvatarUrl(recipient.contact)}
      />
      <strong>{label}</strong>
      <span>
        {recipientTags(recipient).map((tag) => (
          <small key={tag}>{tag}</small>
        ))}
      </span>
    </button>
  )
}

function RecipientList({ recipients }: { recipients: MailRecipient[] }) {
  if (recipients.length === 0) {
    return <span>{t('common.none')}</span>
  }

  return (
    <div className="mail-thread-recipient-list">
      {recipients.map((recipient) => {
        const label = recipientLabel(recipient)
        const avatarUrl = contactAvatarUrl(recipient.contact)
        const href =
          recipient.contact === null
            ? `/contacts?new_email=${encodeURIComponent(
                recipient.email_address,
              )}&display_name=${encodeURIComponent(label)}`
            : `/contacts?contact_id=${encodeURIComponent(recipient.contact.id)}`
        return (
          <button
            className="mail-thread-recipient"
            key={recipient.email_address}
            onClick={() => navigateTo(href)}
            type="button"
          >
            <img
              alt={t(
                recipient.contact === null
                  ? 'mail.unknownContactAvatarAlt'
                  : 'mail.senderAvatarAlt',
                { name: label },
              )}
              src={avatarUrl}
            />
            <span>
              <strong>{label}</strong>
              <small>{recipient.email_address}</small>
            </span>
          </button>
        )
      })}
    </div>
  )
}

function MailThreadView({ messageId }: MailThreadViewProps) {
  const [detail, setDetail] = useState<MailDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busyAction, setBusyAction] = useState<string | null>(null)
  const [importanceMenuId, setImportanceMenuId] = useState<string | null>(null)
  const targetRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    let isMounted = true
    getMailDetail(messageId)
      .then(async (nextDetail) => {
        if (
          nextDetail.thread_messages.every(
            (threadMessage) => threadMessage.read_status === 'read',
          )
        ) {
          return nextDetail
        }
        return markMailRead(messageId)
      })
      .then((nextDetail) => {
        if (isMounted) {
          setDetail(nextDetail)
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
  }, [messageId])

  useEffect(() => {
    if (detail !== null) {
      targetRef.current?.scrollIntoView?.({ block: 'center' })
    }
  }, [detail])

  async function runAction(
    actionId: string,
    action: () => Promise<MailDetail>,
    message?: string,
  ) {
    setBusyAction(actionId)
    setError(null)
    setNotice(null)
    try {
      setDetail(await action())
      if (message !== undefined) {
        setNotice(message)
      }
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setBusyAction(null)
    }
  }

  async function refreshUntilMailSummary(messageIdToSummarize: string) {
    for (let attempt = 0; attempt < 30; attempt += 1) {
      const nextDetail = await getMailDetail(messageId)
      const hasSummary = nextDetail.summary?.items?.some(
        (summary) => summary.message_id === messageIdToSummarize,
      )
      if (hasSummary === true) {
        return nextDetail
      }
      await delay(2000)
    }
    return getMailDetail(messageId)
  }

  async function requestSummaryAndRefresh(messageIdToSummarize: string) {
    await requestMailSummary(messageIdToSummarize)
    return refreshUntilMailSummary(messageIdToSummarize)
  }

  async function updateImportanceAndRefreshSummary(
    messageIdToUpdate: string,
    importance: 'high' | 'middle' | 'low' | 'skip',
    hasSummary: boolean,
  ) {
    const nextDetail = await updateMailImportance(messageIdToUpdate, importance)
    if (!['high', 'middle'].includes(importance) || hasSummary) {
      return nextDetail
    }
    return refreshUntilMailSummary(messageIdToUpdate)
  }

  function incomingActionsFor(message: MailThreadMessage): IncomingAction[] {
    const isProcessed = message.processed_status === 'processed'
    const hasSummary = detail?.summary?.items?.some(
      (summary) => summary.message_id === message.id,
    ) === true
    return [
      {
        id: 'done',
        label: isProcessed
          ? t('mail.thread.action.undo')
          : t('mail.thread.action.done'),
        disabled: busyAction !== null,
        className: isProcessed
          ? 'mail-thread-action-subtle'
          : 'mail-thread-action-primary',
        title: isProcessed
          ? t('mail.thread.unprocessed')
          : t('mail.thread.processed'),
        onClick: () => {
          void runAction(
            `${message.id}-done`,
            async () => {
              if (isProcessed) {
                await unprocessMail(message.id)
              } else {
                await processMail(message.id)
              }
              return getMailDetail(messageId)
            },
          )
        },
      },
      ...incomingActionKeys.slice(1).map((key) => ({
        id: key,
        label: t(key),
        disabled:
          !['mail.thread.action.reply', 'mail.thread.action.summary'].includes(key) ||
          busyAction !== null ||
          (key === 'mail.thread.action.summary' && hasSummary),
        className: 'mail-thread-action-quiet',
        title:
          key === 'mail.thread.action.summary'
            ? hasSummary
              ? t('mail.thread.summaryExistsTitle')
              : t('mail.thread.summaryMockTitle')
            : key === 'mail.thread.action.reply'
              ? t('mail.thread.action.reply')
              : t('common.notImplemented'),
        onClick: () => {
          if (key === 'mail.thread.action.reply') {
            navigateTo(replyHrefFor(message))
            return
          }
          if (key !== 'mail.thread.action.summary') {
            return
          }
          void runAction(
            `${message.id}-summary`,
            () => requestSummaryAndRefresh(message.id),
            t('mail.thread.summaryRequested'),
          )
        },
      })),
    ]
  }

  function outgoingActionsFor(message: MailThreadMessage): IncomingAction[] {
    return outgoingActionKeys.map((key) => ({
      id: key,
      label: t(key),
      disabled:
        !['mail.thread.action.followUp', 'mail.thread.action.resend'].includes(key) ||
        busyAction !== null,
      className: 'mail-thread-action-quiet',
      title:
        key === 'mail.thread.action.followUp' || key === 'mail.thread.action.resend'
          ? t(key)
          : t('common.notImplemented'),
      onClick: () => {
        if (key === 'mail.thread.action.followUp') {
          navigateTo(followUpHrefFor(message))
          return
        }
        if (key === 'mail.thread.action.resend') {
          navigateTo(resendHrefFor(message))
        }
      },
    }))
  }

  function scheduledActionsFor(sendRequest: MailSendRequest): IncomingAction[] {
    return [
      {
        id: 'send-now',
        label: t('mail.thread.action.sendNow'),
        disabled: busyAction !== null,
        className: 'mail-thread-action-primary',
        title: t('mail.thread.action.sendNow'),
        onClick: () => {
          void runAction(
            `${sendRequest.id}-send-now`,
            async () => {
              await sendMailRequestNow(sendRequest.id)
              return getMailDetail(messageId)
            },
            t('mail.thread.sendNowQueued'),
          )
        },
      },
      {
        id: 'reschedule',
        label: t('mail.thread.action.reschedule'),
        disabled: busyAction !== null,
        className: 'mail-thread-action-quiet',
        title: t('mail.thread.action.reschedule'),
        onClick: () => {
          const nextValue = window.prompt(
            t('mail.compose.scheduledAt'),
            scheduledAtLocalValue(sendRequest),
          )
          if (nextValue === null || nextValue.trim() === '') {
            return
          }
          void runAction(
            `${sendRequest.id}-reschedule`,
            async () => {
              await rescheduleMailRequest(
                sendRequest.id,
                localDateTimeToJstIso(nextValue.trim()),
              )
              return getMailDetail(messageId)
            },
            t('mail.thread.rescheduled'),
          )
        },
      },
      {
        id: 'cancel',
        label: t('mail.thread.action.cancelSend'),
        disabled: busyAction !== null,
        className: 'mail-thread-action-subtle',
        title: t('mail.thread.action.cancelSend'),
        onClick: () => {
          void runAction(
            `${sendRequest.id}-cancel`,
            async () => {
              await cancelMailSendRequest(sendRequest.id)
              return getMailDetail(messageId)
            },
            t('mail.thread.sendCanceled'),
          )
        },
      },
    ]
  }

  if (detail === null) {
    return (
      <main className="app-shell">
        <div className="mail-thread-shell">
          <header className="maintenance-header">
            <div>
              <p>{t('app.name')}</p>
              <h1>{t('mail.thread.heading')}</h1>
            </div>
            <AppLink href="/mail">{t('mail.heading')}</AppLink>
          </header>
          {error === null ? (
            <p className="mail-empty">{t('session.checking.label')}</p>
          ) : (
            <p className="mail-feedback" role="alert">{error}</p>
          )}
        </div>
      </main>
    )
  }

  const threadMessages = [...detail.thread_messages].sort((first, second) => {
    const receivedOrder = second.received_at.localeCompare(first.received_at)
    return receivedOrder !== 0 ? receivedOrder : second.id.localeCompare(first.id)
  })
  const summaryItems = detail.summary?.items ?? []
  const focusedMessage =
    detail.thread_messages.find((threadMessage) => threadMessage.id === messageId) ??
    detail.message
  const mailListHref = mailListHrefFor(focusedMessage)
  const gmailThreadLink =
    detail.message.gmail_link ??
    threadMessages.find((message) => message.gmail_link !== null)?.gmail_link ??
    null
  const threadEntries: ThreadEntry[] = [
    ...threadMessages.map((message) => ({
      kind: 'mail' as const,
      id: message.id,
      at: message.received_at,
      message,
    })),
    ...(detail.scheduled_send_requests ?? []).map((request) => ({
      kind: 'scheduled' as const,
      id: request.id,
      at: request.scheduled_at ?? request.created_at,
      request,
    })),
  ].sort((first, second) => {
    const timeOrder = second.at.localeCompare(first.at)
    return timeOrder !== 0 ? timeOrder : second.id.localeCompare(first.id)
  })

  return (
    <main className="app-shell">
      <div className="mail-thread-shell">
        <header className="maintenance-header">
          <div>
            <p>{t('app.name')}</p>
            <div className="mail-thread-title-row">
              <h1>{detail.message.subject ?? t('mail.noSubject')}</h1>
              {gmailThreadLink !== null && (
                <a
                  aria-label={t('mail.thread.openGmail')}
                  className="mail-thread-gmail-link"
                  href={gmailThreadLink}
                  rel="noreferrer"
                  target="_blank"
                  title={t('mail.thread.openGmail')}
                >
                  <span aria-hidden="true" className="mail-thread-gmail-glyph">M</span>
                </a>
              )}
            </div>
          </div>
          <nav className="mail-thread-nav" aria-label={t('mail.thread.navLabel')}>
            <AppLink href={mailListHref}>{t('mail.heading')}</AppLink>
            <AppLink href="/">{t('top.heading')}</AppLink>
          </nav>
        </header>

        {(error !== null || notice !== null) && (
          <div className="mail-feedback">
            {error !== null && <p role="alert">{error}</p>}
            {notice !== null && <p>{notice}</p>}
          </div>
        )}

        {isBugImportance(detail.auto_state.effective_importance) && (
          <section className="mail-thread-bug">
            <strong>{t('mail.importance.bug')}</strong>
            <p>{t('mail.thread.bugNote')}</p>
          </section>
        )}

        {detail.auto_state.llm_blocked === true && (
          <section className="mail-thread-llm-blocked">
            <strong>{t('mail.llmBlocked')}</strong>
            <p>{llmBlockedTitle(detail.auto_state)}</p>
          </section>
        )}

        <section className="mail-panel mail-thread-summary">
          <h2>{t('mail.thread.summary')}</h2>
          {detail.summary == null ? (
            <p>{t('mail.thread.summaryEmpty')}</p>
          ) : (
            <p>{detail.summary.summary_text}</p>
          )}
        </section>

        <section className="mail-thread-list" aria-label={t('mail.thread.messages')}>
          {threadEntries.map((entry, index) => {
            const showDateDivider =
              index === 0 ||
              receivedDate(entry.at) !== receivedDate(threadEntries[index - 1].at)
            if (entry.kind === 'scheduled') {
              const sendRequest = entry.request
              return (
                <Fragment key={sendRequest.id}>
                  {showDateDivider && (
                    <div className="mail-thread-date-divider">
                      <span>{formatDateLabel(entry.at)}</span>
                    </div>
                  )}
                  <div className="mail-thread-item mail-thread-item-sent mail-thread-item-scheduled">
                    <article className="mail-panel mail-thread-message mail-thread-message-scheduled">
                      <header>
                        <div>
                          <div className="mail-thread-message-actions" aria-label="Scheduled mail actions">
                            {scheduledActionsFor(sendRequest).map((action) => (
                              <button
                                className={action.className}
                                disabled={action.disabled}
                                key={action.id}
                                onClick={action.onClick}
                                title={action.title}
                                type="button"
                              >
                                {action.label}
                              </button>
                            ))}
                          </div>
                          <span>
                            {t('mail.thread.scheduledFor', {
                              time: formatDateTime(entry.at),
                            })}
                          </span>
                          <h2>{sendRequest.subject ?? t('mail.noSubject')}</h2>
                        </div>
                        <span className="mail-thread-status mail-thread-scheduled-status">
                          {t('mail.thread.scheduled')}
                        </span>
                      </header>
                      <details className="mail-thread-section mail-thread-head-details">
                        <summary>{t('mail.thread.head')}</summary>
                        <dl className="mail-thread-meta mail-thread-head">
                          <div>
                            <dt>To</dt>
                            <dd>{sendRequest.to_addresses.join(', ') || t('common.none')}</dd>
                          </div>
                          {sendRequest.cc_addresses.length > 0 && (
                            <div>
                              <dt>Cc</dt>
                              <dd>{sendRequest.cc_addresses.join(', ')}</dd>
                            </div>
                          )}
                          {sendRequest.bcc_addresses.length > 0 && (
                            <div>
                              <dt>Bcc</dt>
                              <dd>{sendRequest.bcc_addresses.join(', ')}</dd>
                            </div>
                          )}
                        </dl>
                      </details>
                      <section className="mail-thread-section">
                        <h3>{t('mail.thread.body')}</h3>
                        <pre className="mail-thread-body">
                          {sendRequest.body_text || t('mail.thread.noBody')}
                        </pre>
                      </section>
                    </article>
                  </div>
                </Fragment>
              )
            }
            const message = entry.message
            const isTarget = message.id === messageId
            const isSent = isSentMessage(message)
            const sender = senderRecipient(message)
            const messageImportance =
              message.effective_importance ?? detail.auto_state.effective_importance
            const messageSummary = summaryItems.find(
              (summary) => summary.message_id === message.id,
            )
            const replyToAddress = message.reply_to_address
            return (
              <Fragment key={message.id}>
                {showDateDivider && (
                  <div className="mail-thread-date-divider">
                    <span>{formatDateLabel(message.received_at)}</span>
                  </div>
                )}
                <div
                  className={`mail-thread-item ${
                    isSent ? 'mail-thread-item-sent' : 'mail-thread-item-received'
                  } ${isTarget ? 'mail-thread-item-target' : ''}`}
                  id={`mail-${message.id}`}
                  ref={isTarget ? targetRef : undefined}
                >
                  {!isSent && <SenderCard recipient={sender} />}
                  <article
                    className={`mail-panel mail-thread-message ${
                      isTarget ? 'mail-thread-message-target' : ''
                    }`}
                  >
                  <header>
                  <div>
                    <div className="mail-thread-message-actions" aria-label="Mail actions">
                      {isSent
                        ? outgoingActionsFor(message).map((action) => (
                            <button
                              className={action.className}
                              disabled={action.disabled}
                              key={action.id}
                              onClick={action.onClick}
                              title={action.title}
                              type="button"
                            >
                              {action.label}
                            </button>
                          ))
                        : incomingActionsFor(message).map((action) => (
                            <button
                              className={`${action.className ?? ''} ${
                                action.id === 'mail.thread.action.summary' &&
                                busyAction === `${message.id}-summary`
                                  ? 'mail-thread-action-loading'
                                  : ''
                              }`.trim()}
                              disabled={action.disabled}
                              key={action.id}
                              onClick={action.onClick}
                              title={action.title}
                              type="button"
                            >
                              {action.label}
                            </button>
                          ))}
                    </div>
                    <span>{formatDateTime(message.received_at)}</span>
                    <h2>{message.subject ?? t('mail.noSubject')}</h2>
                  </div>
                  {!isSent && (
                    <div className="mail-thread-importance">
                      {message.llm_blocked === true && (
                        <span
                          className="mail-llm-blocked-badge"
                          title={llmBlockedTitle(message)}
                        >
                          {t('mail.llmBlocked')}
                        </span>
                      )}
                      <button
                        aria-expanded={importanceMenuId === message.id}
                        className={`mail-thread-status ${
                          isBugImportance(messageImportance)
                            ? 'mail-priority-bug'
                            : `mail-priority-${messageImportance}`
                        }`}
                        disabled={busyAction !== null}
                        onClick={() =>
                          setImportanceMenuId((currentId) =>
                            currentId === message.id ? null : message.id,
                          )
                        }
                        type="button"
                      >
                        {displayImportance(messageImportance)}
                      </button>
                      {importanceMenuId === message.id && (
                        <div className="mail-thread-importance-menu">
                          {(['high', 'middle', 'low', 'skip'] as const).map((importance) => (
                            <button
                              disabled={busyAction !== null}
                              key={importance}
                              onClick={() => {
                                setImportanceMenuId(null)
                                const shouldWaitForSummary =
                                  ['high', 'middle'].includes(importance) &&
                                  messageSummary === undefined
                                void runAction(
                                  shouldWaitForSummary
                                    ? `${message.id}-summary`
                                    : `${message.id}-${importance}`,
                                  () =>
                                    updateImportanceAndRefreshSummary(
                                      message.id,
                                      importance,
                                      messageSummary !== undefined,
                                    ),
                                  t('mail.thread.importanceUpdated'),
                                )
                              }}
                              type="button"
                            >
                              {t(importanceLabelKeys[importance])}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                  </header>

                  <details className="mail-thread-section mail-thread-head-details">
                    <summary>{t('mail.thread.head')}</summary>
                    <dl className="mail-thread-meta mail-thread-head">
                      <div>
                        <dt>{t('mail.from')}</dt>
                        <dd><RecipientList recipients={[sender]} /></dd>
                      </div>
                      <div>
                        <dt>To</dt>
                        <dd>
                          <RecipientList
                            recipients={recipientsFor(
                              message.to_addresses,
                              message.to_recipients,
                            )}
                          />
                        </dd>
                      </div>
                      {message.cc_addresses.length > 0 && (
                        <div>
                          <dt>Cc</dt>
                          <dd>
                            <RecipientList
                              recipients={recipientsFor(
                                message.cc_addresses,
                                message.cc_recipients,
                              )}
                            />
                          </dd>
                        </div>
                      )}
                      {replyToAddress !== null && replyToAddress !== message.from_address && (
                        <div>
                          <dt>{t('mail.replyTo')}</dt>
                          <dd>
                            <RecipientList
                              recipients={recipientsFor([replyToAddress])}
                            />
                          </dd>
                        </div>
                      )}
                    </dl>
                  </details>

                  {messageSummary !== undefined && (
                    <section className="mail-thread-section mail-thread-mail-summary">
                      <h3>{t('mail.thread.mailSummary')}</h3>
                      <p>{messageSummary.summary_text}</p>
                    </section>
                  )}

                  {busyAction === `${message.id}-summary` && (
                    <section
                      aria-live="polite"
                      className="mail-thread-section mail-thread-mail-summary mail-thread-summary-progress"
                    >
                      <h3>{t('mail.thread.action.summarizing')}</h3>
                      <p>{t('mail.thread.summaryInProgress')}</p>
                    </section>
                  )}

                  {messageSummary?.translation_text != null && (
                    <details className="mail-thread-section mail-thread-head-details">
                      <summary>{t('mail.thread.translation')}</summary>
                      <pre className="mail-thread-body">
                        {messageSummary.translation_text}
                      </pre>
                    </details>
                  )}

                  {messageSummary === undefined ? (
                    <section className="mail-thread-section">
                      <h3>{t('mail.thread.body')}</h3>
                      <pre className="mail-thread-body">
                        {mailBody(message) || t('mail.thread.noBody')}
                      </pre>
                    </section>
                  ) : (
                    <details className="mail-thread-section mail-thread-head-details">
                      <summary>{t('mail.thread.originalBody')}</summary>
                      <pre className="mail-thread-body">
                        {mailBody(message) || t('mail.thread.noBody')}
                      </pre>
                    </details>
                  )}
                </article>
                </div>
              </Fragment>
            )
          })}
        </section>
      </div>
    </main>
  )
}

export default MailThreadView
