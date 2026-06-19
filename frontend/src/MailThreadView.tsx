import { Fragment, useEffect, useId, useMemo, useRef, useState } from 'react'
import type { MouseEvent, ReactNode } from 'react'
import { t } from './i18n'
import type { MessageKey } from './i18n'
import { AppLink, TopNav, navigateTo } from './navigation'
import defaultContactAvatarUrl from './assets/default-contact-avatar.svg'
import defaultMailingListAvatarUrl from './assets/default-mailing-list-avatar.svg'
import defaultServiceAvatarUrl from './assets/default-service-avatar.svg'
import defaultSpamAvatarUrl from './assets/default-spam-avatar.webp'
import gmailIconUrl from './assets/gmail-icon-2020.svg'
import paperclipDiagonalUrl from './assets/paperclip-diagonal.svg'
import unknownContactAvatarUrl from './assets/default-unknown-contact-avatar.svg'
import {
  allowMailLlm,
  cancelMailSendRequest,
  assignMailThreadToCase,
  createGoogleCalendarEvent,
  enqueueMailAttachmentFetchJob,
  getMailDetail,
  markMailRead,
  moveMailAttachmentToStorage,
  prefillCalendarEventFromMail,
  processMail,
  requestMailSummary,
  rescheduleMailRequest,
  sendMailRequestNow,
  toJstIsoDateTime,
  unassignMailThreadFromCase,
  unprocessMail,
  updateMailImportance,
} from './phase4Api'
import type { MailAttachment, MailDetail, MailSendRequest, MailThreadMessage } from './phase4Api'
import type { CalendarEventFromMailPrefill } from './phase4Api'
import type { MailRecipient } from './phase4Api'
import { isCaseOpenForSuggestion, listCases } from './phase7Api'
import type { CaseItem } from './phase7Api'
import { createTaskFromMail } from './phase8Api'
import { getProfile } from './profileApi'
import SuggestInput from './SuggestInput'

type MailThreadViewProps = {
  messageId: string
}

type CalendarDraftState = {
  message: MailThreadMessage
  prefill: CalendarEventFromMailPrefill
  caseInput: string
  caseId: string | null
  caseName: string | null
  summary: string
  date: string
  startTime: string
  endTime: string
  location: string
  description: string
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

function normalizedCalendarDate(value: string) {
  const match = value.match(/(\d{4})[-/](\d{1,2})[-/](\d{1,2})/)
  if (match === null) {
    return value.slice(0, 10)
  }
  const [, year, month, day] = match
  return `${year}-${month.padStart(2, '0')}-${day.padStart(2, '0')}`
}

function datePart(value: string) {
  return normalizedCalendarDate(value)
}

function timePart(value: string) {
  const match = value.match(/[T ](\d{1,2}):(\d{2})/)
  if (match === null) {
    return '10:00'
  }
  const [, hour, minute] = match
  return `${hour.padStart(2, '0')}:${minute}`
}

function normalizedCalendarTime(value: string) {
  const match = value.trim().match(/^(\d{1,2}):(\d{2})/)
  if (match === null) {
    return ''
  }
  const [, hour, minute] = match
  return `${hour.padStart(2, '0')}:${minute}`
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

function normalizedRecipientAddress(address: string) {
  return address.trim().toLowerCase()
}

function uniqueRecipientAddresses(
  recipients: MailRecipient[],
  excludedAddresses: string[] = [],
) {
  const excluded = new Set(excludedAddresses.map(normalizedRecipientAddress))
  const seen = new Set<string>()
  const addresses: string[] = []
  for (const recipient of recipients) {
    const normalized = normalizedRecipientAddress(recipient.email_address)
    if (normalized === '' || excluded.has(normalized) || seen.has(normalized)) {
      continue
    }
    seen.add(normalized)
    addresses.push(recipient.email_address)
  }
  return addresses
}

function isExcludedRecipientAddress(address: string, excludedAddresses: string[]) {
  const normalized = normalizedRecipientAddress(address)
  return (
    normalized === '' ||
    excludedAddresses
      .map(normalizedRecipientAddress)
      .some((excludedAddress) => excludedAddress === normalized)
  )
}

function senderRecipient(message: MailThreadMessage): MailRecipient {
  const shouldUseReplyTo =
    message.from_contact?.kind === 'mailing_list' &&
    message.from_contact.sender_resolution_mode === 'reply_to' &&
    message.reply_to_address !== null &&
    message.reply_to_address.trim() !== ''

  if (shouldUseReplyTo) {
    return {
      email_address: message.reply_to_address ?? message.from_address,
      contact: message.sender_contact ?? null,
    }
  }

  return {
    email_address: message.from_address,
    contact: message.from_contact ?? message.sender_contact ?? null,
  }
}

function fromRecipient(message: MailThreadMessage): MailRecipient {
  return {
    email_address: message.from_address,
    contact: message.from_contact ?? null,
  }
}

function isSentMessage(message: MailThreadMessage) {
  return (
    message.effective_importance === 'sent' ||
    (message.gmail_labels ?? []).some((label) => label.toLowerCase() === 'sent')
  )
}

function isIncompleteActionRequiredIncomingMessage(message: MailThreadMessage) {
  return (
    !isSentMessage(message) &&
    message.pending_reason === null &&
    message.processed_status !== 'processed' &&
    ['high', 'middle', 'pending', 'unclassified'].includes(message.effective_importance)
  )
}

function isIncompleteNeedsActionIncomingMessage(message: MailThreadMessage) {
  return (
    !isSentMessage(message) &&
    message.pending_reason === null &&
    message.processed_status !== 'processed' &&
    ['high', 'middle'].includes(message.effective_importance)
  )
}

function importanceRank(importance: string) {
  const ranks: Record<string, number> = {
    pinned: 0,
    high: 1,
    middle: 2,
    low: 3,
    pending: 4,
    unclassified: 5,
    skip: 6,
    sent: 7,
  }
  return ranks[importance] ?? 99
}

function aggregateThreadListState(messages: MailThreadMessage[]) {
  const displayGroup = messages.filter((message) => !isSentMessage(message))
  const targetGroup = displayGroup.length > 0 ? displayGroup : messages
  const latestMessage = [...targetGroup].sort(
    (left, right) =>
      right.received_at.localeCompare(left.received_at) || right.id.localeCompare(left.id),
  )[0]
  const processedStatus =
    targetGroup.length > 0 && targetGroup.every((message) => isSentMessage(message))
      ? 'processed'
      : targetGroup.some((message) => message.processed_status === 'unprocessed')
        ? 'unprocessed'
        : 'processed'
  const importanceCandidates = targetGroup
    .map((message) => message.user_importance ?? message.effective_importance)
    .filter((importance) => importance !== 'skip')
  const effectiveImportance =
    importanceCandidates.length === 0
      ? 'skip'
      : importanceCandidates.sort(
          (left, right) =>
            importanceRank(left) - importanceRank(right) || left.localeCompare(right),
        )[0]
  return {
    effectiveImportance,
    latestPendingReason: latestMessage?.pending_reason ?? null,
    processedStatus,
  }
}

function detailStillVisibleInReturnTo(detail: MailDetail, returnTo: string) {
  const destination = new URL(returnTo, window.location.origin)
  if (destination.pathname === '/mail/action-needed') {
    return detail.thread_messages.some(isIncompleteNeedsActionIncomingMessage)
  }
  if (destination.pathname !== '/mail') {
    return false
  }

  const tab = destination.searchParams.get('tab') ?? 'unprocessed'
  const date = destination.searchParams.get('date')
  const messages =
    date === null
      ? detail.thread_messages
      : detail.thread_messages.filter((message) => message.received_at.slice(0, 10) === date)
  if (messages.length === 0) {
    return false
  }
  const listState = aggregateThreadListState(messages)
  if (tab === 'skip') {
    return listState.latestPendingReason === null && listState.effectiveImportance === 'skip'
  }
  if (tab === 'processed') {
    return (
      listState.latestPendingReason === null &&
      listState.effectiveImportance !== 'skip' &&
      listState.processedStatus === 'processed'
    )
  }
  return (
    listState.latestPendingReason === null &&
    listState.effectiveImportance !== 'skip' &&
    listState.processedStatus === 'unprocessed'
  )
}

function latestReceivedMailDate(threadMessages: MailThreadMessage[]) {
  const receivedMessages = threadMessages.filter((message) => !isSentMessage(message))
  const messages = receivedMessages.length > 0 ? receivedMessages : threadMessages
  return messages
    .map((message) => message.received_at)
    .sort((left, right) => right.localeCompare(left))[0]
    ?.slice(0, 10)
}

function mailBody(message: MailThreadMessage) {
  return message.body_text ?? message.snippet ?? ''
}

function formatFileSize(byteSize: number) {
  if (byteSize < 1024) {
    return `${byteSize} B`
  }
  const kib = byteSize / 1024
  if (kib < 1024) {
    return `${kib.toFixed(kib >= 10 ? 0 : 1)} KB`
  }
  const mib = kib / 1024
  return `${mib.toFixed(mib >= 10 ? 0 : 1)} MB`
}

function AttachmentBadges({
  attachments,
  movingAttachmentId,
  onContextMenu,
}: {
  attachments: MailAttachment[]
  movingAttachmentId: string | null
  onContextMenu?: (event: MouseEvent<HTMLAnchorElement>, attachment: MailAttachment) => void
}) {
  if (attachments.length === 0) {
    return null
  }
  return (
    <div className="mail-attachment-badges">
      {attachments.map((attachment) => (
        <a
          aria-label={t('mail.thread.downloadAttachment', {
            name: attachment.filename,
          })}
          className="mail-attachment-badge"
          href={attachment.download_url}
          key={attachment.id}
          onContextMenu={
            onContextMenu === undefined || attachment.source_type === 'sent_attachment'
              ? undefined
              : (event) => onContextMenu(event, attachment)
          }
          title={`${attachment.filename} (${formatFileSize(attachment.byte_size)})`}
        >
          <img alt="" src={paperclipDiagonalUrl} />
          <span>{attachment.filename}</span>
          {movingAttachmentId === attachment.id && (
            <span aria-hidden="true" className="mail-attachment-moving-dot" />
          )}
        </a>
      ))}
    </div>
  )
}

const urlPattern = /(https?:\/\/[^\s<>"']+|www\.[^\s<>"']+)/gi
const trailingUrlPunctuationPattern = /[.,;:!?、。．，）)\]}」』】]+$/
const maxDisplayedUrlLength = 30

function urlHref(url: string) {
  return url.toLowerCase().startsWith('www.') ? `https://${url}` : url
}

function displayedUrlText(url: string) {
  if (url.length <= maxDisplayedUrlLength) {
    return url
  }
  return `${url.slice(0, maxDisplayedUrlLength)}...`
}

function linkifiedNodes(text: string): ReactNode[] {
  const nodes: ReactNode[] = []
  const matcher = new RegExp(urlPattern)
  let lastIndex = 0

  for (const match of text.matchAll(matcher)) {
    const rawUrl = match[0]
    const matchIndex = match.index ?? 0
    const trailingPunctuation = rawUrl.match(trailingUrlPunctuationPattern)?.[0] ?? ''
    const matchedUrl = rawUrl.slice(0, rawUrl.length - trailingPunctuation.length)
    if (matchedUrl === '') {
      continue
    }

    if (matchIndex > lastIndex) {
      nodes.push(text.slice(lastIndex, matchIndex))
    }
    nodes.push(
      <a href={urlHref(matchedUrl)} key={`${matchIndex}-${matchedUrl}`} rel="noreferrer" target="_blank">
        {displayedUrlText(matchedUrl)}
      </a>,
    )
    if (trailingPunctuation !== '') {
      nodes.push(trailingPunctuation)
    }
    lastIndex = matchIndex + rawUrl.length
  }

  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex))
  }
  return nodes.length > 0 ? nodes : [text]
}

function LinkifiedText({ text }: { text: string }) {
  return <>{linkifiedNodes(text)}</>
}

const unsafeHtmlTags = [
  'script',
  'iframe',
  'object',
  'embed',
  'applet',
  'form',
  'input',
  'button',
  'textarea',
  'select',
  'meta',
]

function isSafeHtmlUrl(value: string, allowImageData = false) {
  const trimmed = value.trim()
  if (trimmed === '') {
    return false
  }
  if (allowImageData && /^data:image\/(?:png|gif|jpe?g|webp);base64,/i.test(trimmed)) {
    return true
  }
  try {
    const url = new URL(trimmed, window.location.origin)
    return ['http:', 'https:', 'mailto:'].includes(url.protocol)
  } catch {
    return false
  }
}

function sanitizedMailHtml(rawHtml: string) {
  const document = new DOMParser().parseFromString(rawHtml, 'text/html')
  for (const tagName of unsafeHtmlTags) {
    document.querySelectorAll(tagName).forEach((element) => element.remove())
  }
  document.querySelectorAll('*').forEach((element) => {
    for (const attribute of [...element.attributes]) {
      const name = attribute.name.toLowerCase()
      const value = attribute.value
      if (name.startsWith('on')) {
        element.removeAttribute(attribute.name)
        continue
      }
      if (name === 'href') {
        if (!isSafeHtmlUrl(value)) {
          element.removeAttribute(attribute.name)
          continue
        }
        element.setAttribute('target', '_blank')
        element.setAttribute('rel', 'noreferrer')
      }
      if (name === 'src' && !isSafeHtmlUrl(value, true)) {
        element.removeAttribute(attribute.name)
      }
      if (name === 'srcset') {
        element.removeAttribute(attribute.name)
      }
      if (name === 'style' && /expression\s*\(|javascript\s*:|behavior\s*:/i.test(value)) {
        element.removeAttribute(attribute.name)
      }
    }
  })
  return document.body.innerHTML
}

function mailHtmlDocument(rawHtml: string, frameId: string) {
  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <base target="_blank">
  <style>
    :root { color-scheme: light; }
    html, body { margin: 0; padding: 0; background: transparent; color: #5a2a20; overflow: hidden; }
    body {
      box-sizing: border-box;
      padding: 16px 18px;
      font: 16px/1.55 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      overflow-wrap: anywhere;
    }
    img { max-width: 100%; height: auto; }
    table { max-width: 100%; border-collapse: collapse; }
    pre { white-space: pre-wrap; }
    a { color: #7a2f24; }
  </style>
</head>
<body><div id="caseclosed-mail-html-content">${sanitizedMailHtml(rawHtml)}</div><style>
html, body {
  height: auto !important;
  min-height: 0 !important;
  overflow: visible !important;
}
#caseclosed-mail-html-content {
  box-sizing: border-box;
  display: flow-root;
  width: 100%;
}
</style>
<script>
(() => {
  const frameId = ${JSON.stringify(frameId)};
  function measure() {
    const body = document.body;
    const content = document.getElementById('caseclosed-mail-html-content');
    if (!body || !content) {
      return;
    }
    const contentRect = content.getBoundingClientRect();
    let measuredTop = contentRect.top;
    let measuredBottom = contentRect.bottom;
    for (const element of content.querySelectorAll('*')) {
      const rect = element.getBoundingClientRect();
      measuredTop = Math.min(measuredTop, rect.top);
      measuredBottom = Math.max(
        measuredBottom,
        rect.bottom,
        rect.top + element.scrollHeight,
        rect.top + element.offsetHeight,
      );
    }
    const bodyStyle = window.getComputedStyle(body);
    const paddingTop = Number.parseFloat(bodyStyle.paddingTop) || 0;
    const paddingBottom = Number.parseFloat(bodyStyle.paddingBottom) || 0;
    const contentHeight = Math.max(
      contentRect.height,
      content.scrollHeight,
      content.offsetHeight,
      measuredBottom - measuredTop,
    );
    const height = Math.ceil(Math.max(
      180,
      contentHeight + paddingTop + paddingBottom,
    )) + 2;
    window.parent.postMessage(
      { type: 'caseclosed-mail-html-height', frameId, height },
      '*',
    );
  }
  window.addEventListener('load', measure);
  window.addEventListener('resize', measure);
  if ('ResizeObserver' in window) {
    const observer = new ResizeObserver(measure);
    observer.observe(document.documentElement);
    observer.observe(document.body);
    observer.observe(content);
  }
  for (const image of document.images) {
    image.addEventListener('load', measure);
    image.addEventListener('error', measure);
  }
  requestAnimationFrame(measure);
  [100, 300, 800, 1600, 3200].forEach((delay) => setTimeout(measure, delay));
})();
</script></body>
</html>`
}

function HtmlMailBody({ html }: { html: string }) {
  const frameId = useId()
  const [height, setHeight] = useState(180)
  const srcDoc = useMemo(() => mailHtmlDocument(html, frameId), [frameId, html])

  useEffect(() => {
    setHeight(180)
  }, [srcDoc])

  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      const data = event.data as {
        type?: unknown
        frameId?: unknown
        height?: unknown
      }
      if (
        data.type !== 'caseclosed-mail-html-height' ||
        data.frameId !== frameId ||
        typeof data.height !== 'number' ||
        !Number.isFinite(data.height)
      ) {
        return
      }
      setHeight(Math.max(180, Math.min(30000, Math.ceil(data.height))))
    }

    window.addEventListener('message', handleMessage)
    return () => window.removeEventListener('message', handleMessage)
  }, [frameId])

  return (
    <iframe
      className="mail-thread-html-body"
      sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox"
      scrolling="no"
      srcDoc={srcDoc}
      style={{ height: `${height}px` }}
      title={t('mail.thread.htmlBody')}
    />
  )
}

type SplitBody = {
  mainText: string
  quotedText: string | null
}

function looksLikeQuotedReplyIntro(line: string) {
  const trimmed = line.trim()
  const japaneseGmailReplyIntro =
    /\d{4}\u5e74\d{1,2}\u6708\d{1,2}\u65e5(?:\([^)]+\))?\s+\d{1,2}:\d{2}\s+[^<\n]+<[^<>@\s]+@[^<>@\s]+>:/
  const slashDateGmailReplyIntro =
    /\d{4}\/\d{1,2}\/\d{1,2}(?:\([^)]+\))?\s+\d{1,2}:\d{2}\s+[^<\n]+<[^<>@\s]+@[^<>@\s]+>:/
  return (
    /^On .+ wrote:$/i.test(trimmed) ||
    japaneseGmailReplyIntro.test(trimmed) ||
    slashDateGmailReplyIntro.test(trimmed)
  )
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
    if (trimmed.startsWith('>')) {
      return true
    }
    if (looksLikeOriginalMessageDivider(line)) {
      return true
    }
    return looksLikeQuotedReplyIntro(line)
  })

  if (quoteStartIndex <= 0) {
    return { mainText: text, quotedText: null }
  }

  const mainText = lines.slice(0, quoteStartIndex).join('\n').trimEnd()
  const quotedText = lines.slice(quoteStartIndex).join('\n').trim()
  if (mainText === '' || quotedText === '') {
    return { mainText: text, quotedText: null }
  }
  return { mainText, quotedText }
}

function MailBodyContent({ html, text }: { html?: string | null; text: string }) {
  const body = text || t('mail.thread.noBody')
  if (bodyContainsMarkdownTable(body)) {
    return <MarkdownMailBody text={body} />
  }
  const splitBody = splitQuotedReply(body)
  if (
    splitBody.quotedText === null &&
    html !== undefined &&
    html !== null &&
    html.trim() !== '' &&
    htmlRepresentsPlainText(html, text)
  ) {
    return <HtmlMailBody html={html} />
  }

  if (splitBody.quotedText === null) {
    return (
      <pre className="mail-thread-body">
        <LinkifiedText text={body} />
      </pre>
    )
  }

  return (
    <>
      <pre className="mail-thread-body">
        <LinkifiedText text={splitBody.mainText} />
      </pre>
      <details className="mail-thread-section mail-thread-head-details mail-thread-quoted-details">
        <summary>{t('mail.thread.quotedReply')}</summary>
        <pre className="mail-thread-body mail-thread-quoted-body">
          <LinkifiedText text={splitBody.quotedText} />
        </pre>
      </details>
    </>
  )
}

function MarkdownMailBody({ text }: { text: string }) {
  return (
    <article className="mail-thread-markdown-body">
      {renderMailMarkdownBlocks(text)}
    </article>
  )
}

function renderMailMarkdownBlocks(text: string) {
  const lines = text.replace(/\r\n?/g, '\n').split('\n')
  const blocks: ReactNode[] = []
  let index = 0

  function isBlockStart(line: string) {
    return (
      /^#{1,6}\s+/.test(line) ||
      /^>\s?/.test(line) ||
      /^[-*]\s+/.test(line) ||
      /^\d+\.\s+/.test(line) ||
      isMarkdownTableStart(lines, index)
    )
  }

  while (index < lines.length) {
    const line = lines[index]
    if (line.trim() === '') {
      index += 1
      continue
    }

    if (isMarkdownTableStart(lines, index)) {
      const headerCells = splitMarkdownTableRow(lines[index])
      index += 2
      const rows: string[][] = []
      while (index < lines.length && splitMarkdownTableRow(lines[index]).length > 1) {
        rows.push(splitMarkdownTableRow(lines[index]))
        index += 1
      }
      blocks.push(
        <div className="mail-thread-markdown-table-wrap" key={`table-${index}`}>
          <table>
            <thead>
              <tr>
                {headerCells.map((cell, cellIndex) => (
                  <th key={`table-${index}-head-${cellIndex}`} scope="col">
                    {markdownInlineNodes(cell, `table-${index}-head-${cellIndex}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={`table-${index}-row-${rowIndex}`}>
                  {headerCells.map((_, cellIndex) => (
                    <td key={`table-${index}-row-${rowIndex}-${cellIndex}`}>
                      {markdownInlineNodes(
                        row[cellIndex] ?? '',
                        `table-${index}-row-${rowIndex}-${cellIndex}`,
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      )
      continue
    }

    const headingMatch = /^(#{1,6})\s+(.+)$/.exec(line)
    if (headingMatch !== null) {
      const level = headingMatch[1].length
      const content = markdownInlineNodes(headingMatch[2], `heading-${index}`)
      const key = `heading-${index}`
      if (level === 1) blocks.push(<h2 key={key}>{content}</h2>)
      else if (level === 2) blocks.push(<h3 key={key}>{content}</h3>)
      else if (level === 3) blocks.push(<h4 key={key}>{content}</h4>)
      else if (level === 4) blocks.push(<h5 key={key}>{content}</h5>)
      else blocks.push(<h6 key={key}>{content}</h6>)
      index += 1
      continue
    }

    if (/^>\s?/.test(line)) {
      const quoteLines: string[] = []
      while (index < lines.length && /^>\s?/.test(lines[index])) {
        quoteLines.push(lines[index].replace(/^>\s?/, ''))
        index += 1
      }
      blocks.push(
        <blockquote key={`quote-${index}`}>
          {quoteLines.map((quoteLine, quoteIndex) => (
            <Fragment key={`quote-${index}-${quoteIndex}`}>
              {quoteIndex > 0 && <br />}
              {markdownInlineNodes(quoteLine, `quote-${index}-${quoteIndex}`)}
            </Fragment>
          ))}
        </blockquote>,
      )
      continue
    }

    if (/^[-*]\s+/.test(line)) {
      const items: string[] = []
      while (index < lines.length && /^[-*]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^[-*]\s+/, ''))
        index += 1
      }
      blocks.push(
        <ul key={`ul-${index}`}>
          {items.map((item, itemIndex) => (
            <li key={`ul-${index}-${itemIndex}`}>
              {markdownInlineNodes(item, `ul-${index}-${itemIndex}`)}
            </li>
          ))}
        </ul>,
      )
      continue
    }

    if (/^\d+\.\s+/.test(line)) {
      const items: string[] = []
      while (index < lines.length && /^\d+\.\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\d+\.\s+/, ''))
        index += 1
      }
      blocks.push(
        <ol key={`ol-${index}`}>
          {items.map((item, itemIndex) => (
            <li key={`ol-${index}-${itemIndex}`}>
              {markdownInlineNodes(item, `ol-${index}-${itemIndex}`)}
            </li>
          ))}
        </ol>,
      )
      continue
    }

    const paragraphLines: string[] = []
    while (
      index < lines.length &&
      lines[index].trim() !== '' &&
      !isBlockStart(lines[index])
    ) {
      paragraphLines.push(lines[index])
      index += 1
    }
    blocks.push(
      <p key={`p-${index}`}>
        {markdownInlineNodes(paragraphLines.join(' '), `p-${index}`)}
      </p>,
    )
  }

  return blocks
}

function markdownInlineNodes(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = []
  const pattern =
    /(`[^`]+`|\*\*[^*]+\*\*|_[^_\n]+_|\[[^\]]+\]\((?:https?:\/\/|mailto:)[^)]+\))/g
  let lastIndex = 0
  let match: RegExpExecArray | null
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index))
    }
    const token = match[0]
    const key = `${keyPrefix}-${match.index}`
    if (token.startsWith('`')) {
      nodes.push(<code key={key}>{token.slice(1, -1)}</code>)
    } else if (token.startsWith('**')) {
      nodes.push(<strong key={key}>{token.slice(2, -2)}</strong>)
    } else if (token.startsWith('_')) {
      nodes.push(<em key={key}>{token.slice(1, -1)}</em>)
    } else {
      const linkMatch = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(token)
      if (linkMatch === null) {
        nodes.push(token)
      } else {
        nodes.push(
          <a href={linkMatch[2]} key={key} rel="noreferrer" target="_blank">
            {linkMatch[1]}
          </a>,
        )
      }
    }
    lastIndex = pattern.lastIndex
  }
  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex))
  }
  return nodes
}

function bodyContainsMarkdownTable(text: string) {
  const lines = text.replace(/\r\n?/g, '\n').split('\n')
  return lines.some((_, index) => isMarkdownTableStart(lines, index))
}

function isMarkdownTableStart(lines: string[], index: number) {
  const headerCells = splitMarkdownTableRow(lines[index] ?? '')
  const separatorCells = splitMarkdownTableRow(lines[index + 1] ?? '')
  return (
    headerCells.length > 1 &&
    separatorCells.length === headerCells.length &&
    separatorCells.every((cell) => /^:?-{3,}:?$/.test(cell.trim()))
  )
}

function splitMarkdownTableRow(line: string) {
  const trimmed = line.trim()
  if (!trimmed.includes('|')) {
    return []
  }
  const withoutOuterPipes = trimmed.replace(/^\|/, '').replace(/\|$/, '')
  return withoutOuterPipes.split('|').map((cell) => cell.trim())
}

function htmlRepresentsPlainText(html: string, text: string) {
  const plainLines = meaningfulBodyLines(text)
    .map(plainTextLineForHtmlComparison)
    .filter((line) => line.length >= 3)
  if (plainLines.length < 4) {
    return true
  }

  const htmlText = normalizedInlineText(
    new DOMParser().parseFromString(sanitizedMailHtml(html), 'text/html').body
      .textContent ?? '',
  )
  if (htmlText === '') {
    return true
  }

  const leadingLines = plainLines.slice(0, 8)
  const missingLeadingLines = leadingLines.filter(
    (line) => !htmlText.includes(normalizedInlineText(line)),
  )
  const laterRepresented = plainLines
    .slice(8, 24)
    .some((line) => htmlText.includes(normalizedInlineText(line)))

  return !(missingLeadingLines.length >= 3 && laterRepresented)
}

function plainTextLineForHtmlComparison(line: string) {
  return normalizedInlineText(
    line
      .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
      .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
      .replace(/<https?:\/\/[^>]+>/gi, '')
      .replace(/https?:\/\/[^\s)]+/gi, '')
      .replace(/www\.[^\s)]+/gi, ''),
  )
}

function meaningfulBodyLines(text: string) {
  return text
    .split(/\r\n|\r|\n/)
    .map((line) => line.trim())
    .filter((line) => line.length >= 3 && line.length <= 220)
}

function normalizedInlineText(text: string) {
  return text.replace(/\s+/g, ' ').trim()
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

function replyHrefFor(
  message: MailThreadMessage,
  ownedEmailAddresses: string[] = [],
) {
  const replyToAddress = message.reply_to_address ?? message.from_address
  const toRecipients = recipientsFor(message.to_addresses, message.to_recipients)
  const ccRecipients = recipientsFor(message.cc_addresses, message.cc_recipients)
  const candidateRecipients = [...toRecipients, ...ccRecipients]
  const toAddress = isExcludedRecipientAddress(replyToAddress, ownedEmailAddresses)
    ? uniqueRecipientAddresses(candidateRecipients, ownedEmailAddresses)[0] ?? ''
    : replyToAddress
  const params = new URLSearchParams({
    to: toAddress,
    subject: message.subject ?? '',
    auto_body: composeReplyBody(message),
    reply_to_message_id: message.id,
  })
  const ccAddresses = uniqueRecipientAddresses(
    candidateRecipients,
    [toAddress, replyToAddress, ...ownedEmailAddresses],
  )
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

function returnToHrefFromLocation() {
  const returnTo = new URLSearchParams(window.location.search).get('return_to')
  if (returnTo === null || returnTo.trim() === '') {
    return null
  }
  try {
    const destination = new URL(returnTo, window.location.origin)
    if (
      destination.origin !== window.location.origin ||
      (destination.pathname.startsWith('/mail/') &&
        destination.pathname !== '/mail/action-needed') ||
      destination.pathname === window.location.pathname
    ) {
      return null
    }
    return `${destination.pathname}${destination.search}${destination.hash}`
  } catch {
    return null
  }
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
    (contact.status === 'spam'
      ? defaultSpamAvatarUrl
      : contact.kind === 'mailing_list'
        ? defaultMailingListAvatarUrl
        : contact.kind === 'service'
          ? defaultServiceAvatarUrl
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
  if (recipient.contact.kind === 'service') {
    return [t('contacts.kind.service')]
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

function focusMessageIdFromLocation() {
  const value = new URLSearchParams(window.location.search).get('focus_message')
  const trimmed = value?.trim() ?? ''
  return trimmed === '' ? null : trimmed
}

function MailThreadView({ messageId }: MailThreadViewProps) {
  const [detail, setDetail] = useState<MailDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busyAction, setBusyAction] = useState<string | null>(null)
  const [importanceMenuId, setImportanceMenuId] = useState<string | null>(null)
  const [movingAttachmentId, setMovingAttachmentId] = useState<string | null>(null)
  const [ownedEmailAddresses, setOwnedEmailAddresses] = useState<string[]>([])
  const [caseAssignEditing, setCaseAssignEditing] = useState(false)
  const [caseAssignInput, setCaseAssignInput] = useState('')
  const [caseCandidates, setCaseCandidates] = useState<CaseItem[]>([])
  const [caseAssignBusy, setCaseAssignBusy] = useState(false)
  const [taskCasePrompt, setTaskCasePrompt] = useState<{
    message: MailThreadMessage
  } | null>(null)
  const [taskCaseInput, setTaskCaseInput] = useState('')
  const [calendarDraft, setCalendarDraft] = useState<CalendarDraftState | null>(null)
  const [calendarDraftError, setCalendarDraftError] = useState<string | null>(null)
  const [attachmentMenu, setAttachmentMenu] = useState<{
    attachment: MailAttachment
    x: number
    y: number
  } | null>(null)
  const [llmBlockedMenu, setLlmBlockedMenu] = useState<{
    message: MailThreadMessage
    x: number
    y: number
  } | null>(null)
  const targetRef = useRef<HTMLDivElement | null>(null)
  const didScrollToTargetRef = useRef(false)
  const pendingInboxNavigationRef = useRef<{
    timeoutId: number
  } | null>(null)
  const requestedFocusMessageId = focusMessageIdFromLocation()
  const focusMessageId = requestedFocusMessageId ?? messageId

  useEffect(() => {
    let isMounted = true
    getProfile()
      .then((profile) => {
        if (!isMounted) {
          return
        }
        setOwnedEmailAddresses(
          [profile.primary_email, ...profile.email_aliases].filter(
            (address) => address.trim() !== '',
          ),
        )
      })
      .catch(() => {
        if (isMounted) {
          setOwnedEmailAddresses([])
        }
      })
    return () => {
      isMounted = false
    }
  }, [])

  useEffect(() => {
    let isMounted = true
    didScrollToTargetRef.current = false
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
    if (
      (!caseAssignEditing && taskCasePrompt === null && calendarDraft === null) ||
      caseCandidates.length > 0
    ) {
      return
    }
    let isMounted = true
    listCases('all')
      .then((items) => {
        if (isMounted) {
          setCaseCandidates(items.filter((item) => isCaseOpenForSuggestion(item)))
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
  }, [calendarDraft, caseAssignEditing, caseCandidates.length, taskCasePrompt])

  useEffect(() => {
    if (
      requestedFocusMessageId !== null &&
      detail !== null &&
      !didScrollToTargetRef.current
    ) {
      targetRef.current?.scrollIntoView?.({ block: 'start', inline: 'nearest' })
      didScrollToTargetRef.current = true
    }
  }, [detail, requestedFocusMessageId])

  useEffect(() => {
    if (
      detail === null ||
      Object.keys(detail.summary_jobs ?? {}).length === 0
    ) {
      return
    }
    let canceled = false
    const timeoutId = window.setTimeout(() => {
      void getMailDetail(messageId)
        .then((nextDetail) => {
          if (!canceled) {
            setDetail(nextDetail)
          }
        })
        .catch(() => {
          // Keep the current detail visible; the normal action path reports errors.
        })
    }, 2000)
    return () => {
      canceled = true
      window.clearTimeout(timeoutId)
    }
  }, [detail, messageId])

  useEffect(() => {
    return () => {
      cancelPendingInboxNavigation()
    }
  }, [])

  useEffect(() => {
    if (attachmentMenu === null && llmBlockedMenu === null) return undefined

    const closeMenu = () => {
      setAttachmentMenu(null)
      setLlmBlockedMenu(null)
    }
    const closeMenuOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeMenu()
    }
    window.addEventListener('click', closeMenu)
    window.addEventListener('scroll', closeMenu, true)
    window.addEventListener('keydown', closeMenuOnEscape)
    return () => {
      window.removeEventListener('click', closeMenu)
      window.removeEventListener('scroll', closeMenu, true)
      window.removeEventListener('keydown', closeMenuOnEscape)
    }
  }, [attachmentMenu, llmBlockedMenu])

  function cancelPendingInboxNavigation() {
    const pendingNavigation = pendingInboxNavigationRef.current
    if (pendingNavigation === null) {
      return
    }
    window.clearTimeout(pendingNavigation.timeoutId)
    pendingInboxNavigationRef.current = null
  }

  function scheduleNavigation(destination: string) {
    cancelPendingInboxNavigation()

    const timeoutId = window.setTimeout(() => {
      pendingInboxNavigationRef.current = null
      navigateTo(destination)
    }, 1500)
    pendingInboxNavigationRef.current = { timeoutId }
  }

  function scheduleInboxNavigation(date: string | undefined) {
    scheduleNavigation(
      date === undefined
        ? '/mail?tab=unprocessed'
        : `/mail?tab=unprocessed&date=${encodeURIComponent(date)}`,
    )
  }

  function scheduleReturnToNavigationIfResolved(nextDetail: MailDetail) {
    const returnTo = returnToHrefFromLocation()
    if (returnTo !== null) {
      if (!detailStillVisibleInReturnTo(nextDetail, returnTo)) {
        scheduleNavigation(returnTo)
      }
      return
    }
    if (!nextDetail.thread_messages.some(isIncompleteActionRequiredIncomingMessage)) {
      const inboxDate = latestReceivedMailDate(nextDetail.thread_messages)
      scheduleInboxNavigation(inboxDate)
    }
  }

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

  function handleAttachmentContextMenu(
    event: MouseEvent<HTMLAnchorElement>,
    attachment: MailAttachment,
  ) {
    event.preventDefault()
    setAttachmentMenu({
      attachment,
      x: Math.max(8, Math.min(event.clientX, window.innerWidth - 220)),
      y: Math.max(8, Math.min(event.clientY, window.innerHeight - 64)),
    })
  }

  async function handleMoveAttachmentToStorage() {
    if (attachmentMenu === null) return
    const attachment = attachmentMenu.attachment
    setAttachmentMenu(null)
    setMovingAttachmentId(attachment.id)
    setError(null)
    setNotice(null)
    try {
      await moveMailAttachmentToStorage(attachment.id)
      setDetail(await getMailDetail(messageId))
      setNotice(t('mail.thread.attachmentMovedToStorage', { name: attachment.filename }))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setMovingAttachmentId(null)
    }
  }

  async function handleEnqueueAttachmentFetchJob() {
    if (attachmentMenu === null) return
    const attachment = attachmentMenu.attachment
    setAttachmentMenu(null)
    setMovingAttachmentId(attachment.id)
    setError(null)
    setNotice(null)
    try {
      const result = await enqueueMailAttachmentFetchJob(attachment.id)
      setNotice(t('mail.thread.attachmentFetchJobQueued', { jobId: result.job_id }))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setMovingAttachmentId(null)
    }
  }

  function handleLlmBlockedContextMenu(
    event: MouseEvent<HTMLSpanElement>,
    message: MailThreadMessage,
  ) {
    event.preventDefault()
    setLlmBlockedMenu({
      message,
      x: Math.max(8, Math.min(event.clientX, window.innerWidth - 240)),
      y: Math.max(8, Math.min(event.clientY, window.innerHeight - 64)),
    })
  }

  function handleAllowLlmFromMenu() {
    if (llmBlockedMenu === null || busyAction !== null) {
      return
    }
    const message = llmBlockedMenu.message
    setLlmBlockedMenu(null)
    if (!window.confirm(t('mail.thread.allowLlmConfirm'))) {
      return
    }
    void runAction(
      `${message.id}-allow-llm`,
      () => allowMailLlm(message.id),
      t('mail.thread.llmAllowed'),
    )
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

  function selectedCaseCandidateFor(input: string) {
    const query = input.trim()
    if (query === '') {
      return null
    }
    const normalizedQuery = query.toLowerCase()
    const exactMatches = caseCandidates.filter(
      (item) => item.id === query || item.name.toLowerCase() === normalizedQuery,
    )
    if (exactMatches.length === 1) {
      return exactMatches[0]
    }
    const assignedMatch = (detail?.case_links ?? []).find(
      (item) => item.case_id === query || item.title.toLowerCase() === normalizedQuery,
    )
    if (assignedMatch !== undefined) {
      return {
        id: assignedMatch.case_id,
        name: assignedMatch.title,
      } as CaseItem
    }
    const prefixMatches = caseCandidates.filter((item) =>
      item.name.toLowerCase().startsWith(normalizedQuery),
    )
    return prefixMatches.length === 1 ? prefixMatches[0] : null
  }

  function calendarCaseOptions() {
    const options = [...caseCandidates]
    for (const link of detail?.case_links ?? []) {
      if (!options.some((item) => item.id === link.case_id)) {
        options.push({ id: link.case_id, name: link.title } as CaseItem)
      }
    }
    return options
  }

  function selectedCaseCandidate() {
    return selectedCaseCandidateFor(caseAssignInput)
  }

  async function handleAssignCase() {
    const selectedCase = selectedCaseCandidate()
    if (selectedCase === null) {
      setError(t('mail.thread.caseAssignInvalid'))
      return
    }
    setCaseAssignBusy(true)
    setError(null)
    setNotice(null)
    try {
      setDetail(await assignMailThreadToCase(messageId, selectedCase.id))
      setCaseAssignInput('')
      setNotice(t('mail.thread.caseAssigned', { name: selectedCase.name }))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setCaseAssignBusy(false)
    }
  }

  async function handleUnassignCase(caseId: string, caseTitle: string) {
    setCaseAssignBusy(true)
    setError(null)
    setNotice(null)
    try {
      setDetail(await unassignMailThreadFromCase(messageId, caseId))
      setNotice(t('mail.thread.caseUnassigned', { name: caseTitle }))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setCaseAssignBusy(false)
    }
  }

  async function requestSummaryAndRefresh(messageIdToSummarize: string) {
    await requestMailSummary(messageIdToSummarize)
    return refreshUntilMailSummary(messageIdToSummarize)
  }

  async function generateTaskFromMail(message: MailThreadMessage, caseId?: string | null) {
    setBusyAction(`${message.id}-task`)
    setError(null)
    setNotice(null)
    try {
      const result = await createTaskFromMail({
        message_id: message.id,
        case_id: caseId ?? null,
      })
      setNotice(t('mail.thread.taskCreated'))
      setTaskCasePrompt(null)
      setTaskCaseInput('')
      navigateTo(`/tasks/${encodeURIComponent(result.task.id)}`)
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setBusyAction(null)
    }
  }

  function handleTaskAction(message: MailThreadMessage) {
    const assignedCaseLinks = detail?.case_links ?? []
    if (assignedCaseLinks.length === 1) {
      void generateTaskFromMail(message, assignedCaseLinks[0].case_id)
      return
    }
    setTaskCasePrompt({ message })
    setTaskCaseInput('')
    setError(null)
    setNotice(null)
  }

  function handleTaskCaseGenerateFromInput() {
    if (taskCasePrompt === null) return
    const input = taskCaseInput.trim()
    if (input === '') {
      void generateTaskFromMail(taskCasePrompt.message, null)
      return
    }
    const selectedCase = selectedCaseCandidateFor(input)
    if (selectedCase === null) {
      setError(t('mail.thread.caseAssignInvalid'))
      return
    }
    void generateTaskFromMail(taskCasePrompt.message, selectedCase.id)
  }

  function renderTaskCasePicker(message: MailThreadMessage) {
    if (taskCasePrompt?.message.id !== message.id) {
      return null
    }
    return (
      <section className="mail-thread-task-case-picker">
        <div>
          <h3>{t('mail.thread.taskCaseHeading')}</h3>
          <p>{t('mail.thread.taskCaseBody')}</p>
        </div>
        {assignedCaseLinks.length > 0 && (
          <div className="mail-thread-task-case-options">
            {assignedCaseLinks.map((caseLink) => (
              <button
                className="mail-thread-case-badge"
                disabled={busyAction !== null}
                key={caseLink.case_id}
                onClick={() => void generateTaskFromMail(message, caseLink.case_id)}
                type="button"
              >
                {caseLink.title}
              </button>
            ))}
          </div>
        )}
        <div className="mail-thread-case-editor-input">
          <label>{t('mail.thread.taskCaseInput')}</label>
          <SuggestInput
            ariaLabel={t('mail.thread.taskCaseInput')}
            autoComplete="off"
            disabled={busyAction !== null}
            maxItems={1}
            onChange={setTaskCaseInput}
            options={caseCandidates.map((item) => ({
              key: item.id,
              value: item.name,
              label: item.name,
              badgeLabel: item.name,
            }))}
            placeholder={t('mail.thread.taskCasePlaceholder')}
            value={taskCaseInput}
          />
          <button
            className={`button-loading-dot${
              busyAction === `${message.id}-task` ? ' is-loading' : ''
            }`}
            disabled={busyAction !== null}
            onClick={handleTaskCaseGenerateFromInput}
            type="button"
          >
            {t('mail.thread.taskCaseGenerate')}
          </button>
          <button
            disabled={busyAction !== null}
            onClick={() => {
              setTaskCasePrompt(null)
              setTaskCaseInput('')
            }}
            type="button"
          >
            {t('common.cancel')}
          </button>
        </div>
      </section>
    )
  }

  async function generateCalendarDraftFromMail(
    message: MailThreadMessage,
    caseId?: string | null,
  ) {
    setBusyAction(`${message.id}-calendar`)
    setError(null)
    setNotice(null)
    try {
      const result = await prefillCalendarEventFromMail({
        message_id: message.id,
        case_id: caseId ?? null,
      })
      setTaskCasePrompt(null)
      setTaskCaseInput('')
      setCalendarDraftError(null)
      setCalendarDraft({
        message,
        prefill: result.prefill,
        caseInput: result.linked_case_name ?? '',
        caseId: result.linked_case_id,
        caseName: result.linked_case_name,
        summary: result.prefill.summary,
        date: datePart(result.prefill.start_at),
        startTime: timePart(result.prefill.start_at),
        endTime: timePart(result.prefill.end_at),
        location: result.prefill.location ?? '',
        description: result.prefill.description ?? '',
      })
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setBusyAction(null)
    }
  }

  function handleCalendarAction(message: MailThreadMessage) {
    const assignedCaseLinks = detail?.case_links ?? []
    if (assignedCaseLinks.length === 1) {
      void generateCalendarDraftFromMail(message, assignedCaseLinks[0].case_id)
      return
    }
    void generateCalendarDraftFromMail(message, null)
  }

  function updateCalendarDraft(patch: Partial<CalendarDraftState>) {
    setCalendarDraft((current) => (current === null ? current : { ...current, ...patch }))
  }

  async function createCalendarEventFromDraft() {
    if (calendarDraft === null) return
    const summary = calendarDraft.summary.trim()
    const date = normalizedCalendarDate(calendarDraft.date.trim())
    const startTime = normalizedCalendarTime(calendarDraft.startTime)
    const endTime = normalizedCalendarTime(calendarDraft.endTime)
    if (summary === '' || date === '' || startTime === '' || endTime === '') {
      setCalendarDraftError(t('mail.thread.calendarRequired'))
      setError(t('mail.thread.calendarRequired'))
      return
    }
    const caseInput = calendarDraft.caseInput.trim()
    let linkedCaseId = calendarDraft.caseId
    if (caseInput === '') {
      linkedCaseId = null
    } else if (
      calendarDraft.caseId !== null &&
      calendarDraft.caseName !== null &&
      caseInput === calendarDraft.caseName
    ) {
      linkedCaseId = calendarDraft.caseId
    } else {
      const selectedCase = selectedCaseCandidateFor(caseInput)
      if (selectedCase !== null) {
        linkedCaseId = selectedCase.id
      } else {
        linkedCaseId = null
      }
    }
    setBusyAction(`${calendarDraft.message.id}-calendar-create`)
    setCalendarDraftError(null)
    setError(null)
    setNotice(null)
    try {
      const result = await createGoogleCalendarEvent({
        summary,
        start: toJstIsoDateTime(`${date}T${startTime}`),
        end: toJstIsoDateTime(`${date}T${endTime}`),
        description: calendarDraft.description,
        location: calendarDraft.location,
        time_zone: calendarDraft.prefill.time_zone || 'Asia/Tokyo',
        linked_mail_message_id: calendarDraft.message.id,
        linked_case_id: linkedCaseId,
      })
      setNotice(t('mail.thread.calendarCreated'))
      setCalendarDraft(null)
      const dbEventId = result.db_event?.id ?? null
      if (dbEventId !== null) {
        navigateTo(`/calendar/events/${encodeURIComponent(dbEventId)}`)
      }
    } catch (requestError) {
      const message = describeError(requestError)
      setCalendarDraftError(message)
      setError(message)
    } finally {
      setBusyAction(null)
    }
  }

  function renderCalendarDraftForm(message: MailThreadMessage) {
    if (calendarDraft?.message.id !== message.id) {
      return null
    }
    const busy = busyAction === `${message.id}-calendar-create`
    return (
      <section className="mail-thread-calendar-event-form">
        <div>
          <h3>{t('mail.thread.calendarHeading')}</h3>
          <p>{t('mail.thread.calendarBody')}</p>
        </div>
        <div className="mail-thread-calendar-grid">
          <label>
            {t('mail.thread.calendarSummary')}
            <input
              disabled={busy}
              onChange={(event) => updateCalendarDraft({ summary: event.target.value })}
              value={calendarDraft.summary}
            />
          </label>
          <label>
            {t('mail.thread.calendarDate')}
            <input
              disabled={busy}
              onChange={(event) => updateCalendarDraft({ date: event.target.value })}
              type="date"
              value={calendarDraft.date}
            />
          </label>
          <label>
            {t('mail.thread.calendarStart')}
            <input
              disabled={busy}
              onChange={(event) => updateCalendarDraft({ startTime: event.target.value })}
              type="time"
              value={calendarDraft.startTime}
            />
          </label>
          <label>
            {t('mail.thread.calendarEnd')}
            <input
              disabled={busy}
              onChange={(event) => updateCalendarDraft({ endTime: event.target.value })}
              type="time"
              value={calendarDraft.endTime}
            />
          </label>
          <label>
            {t('mail.thread.calendarLocation')}
            <input
              disabled={busy}
              onChange={(event) => updateCalendarDraft({ location: event.target.value })}
              value={calendarDraft.location}
            />
          </label>
          <label>
            {t('mail.thread.calendarCase')}
            <SuggestInput
              ariaLabel={t('mail.thread.calendarCase')}
              autoComplete="off"
              disabled={busy}
              maxItems={1}
              onChange={(value) => updateCalendarDraft({ caseInput: value })}
              options={calendarCaseOptions().map((item) => ({
                key: item.id,
                value: item.name,
                label: item.name,
                badgeLabel: item.name,
              }))}
              placeholder={t('mail.thread.calendarCasePlaceholder')}
              value={calendarDraft.caseInput}
            />
          </label>
        </div>
        <label className="mail-thread-calendar-description">
          {t('mail.thread.calendarDescription')}
          <textarea
            disabled={busy}
            onChange={(event) => updateCalendarDraft({ description: event.target.value })}
            value={calendarDraft.description}
          />
        </label>
        <div className="mail-thread-calendar-linked-mail">
          <span>{t('mail.thread.calendarRelatedMail')}</span>
          <strong>{message.subject || '(no subject)'}</strong>
        </div>
        {calendarDraft.prefill.warnings.length > 0 && (
          <ul className="mail-thread-calendar-warnings">
            {calendarDraft.prefill.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        )}
        {calendarDraftError !== null && (
          <p className="mail-thread-calendar-error" role="alert">
            {calendarDraftError}
          </p>
        )}
        <div className="mail-thread-calendar-actions">
          <button
            className={`button-loading-dot${
              busyAction === `${message.id}-calendar-create` ? ' is-loading' : ''
            }`}
            disabled={busy}
            onClick={createCalendarEventFromDraft}
            type="button"
          >
            {t('mail.thread.calendarCreate')}
          </button>
          <button
            disabled={busy}
            onClick={() => {
              setCalendarDraft(null)
              setCalendarDraftError(null)
            }}
            type="button"
          >
            {t('common.cancel')}
          </button>
        </div>
      </section>
    )
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
    const isPinned = message.effective_importance === 'pinned'
    const hasSummary = detail?.summary?.items?.some(
      (summary) => summary.message_id === message.id,
    ) === true
    const hasActiveSummaryJob =
      detail?.summary_jobs?.[message.id] !== undefined
    const taskGenerationBusy = busyAction === `${message.id}-task`
    const calendarGenerationBusy = busyAction === `${message.id}-calendar`
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
                cancelPendingInboxNavigation()
                await unprocessMail(message.id)
              } else {
                const nextDetail = await processMail(message.id)
                scheduleReturnToNavigationIfResolved(nextDetail)
                return nextDetail
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
          ![
            'mail.thread.action.reply',
            'mail.thread.action.calendar',
            'mail.thread.action.task',
            'mail.thread.action.summary',
          ].includes(key) ||
          busyAction !== null ||
          (key === 'mail.thread.action.calendar' && message.llm_blocked === true) ||
          (key === 'mail.thread.action.task' && message.llm_blocked === true) ||
          (key === 'mail.thread.action.summary' && isPinned) ||
          (key === 'mail.thread.action.summary' && hasSummary) ||
          (key === 'mail.thread.action.summary' && hasActiveSummaryJob),
        className:
          key === 'mail.thread.action.summary' && hasActiveSummaryJob
            ? 'mail-thread-action-quiet mail-thread-action-loading button-loading-dot is-loading'
            : key === 'mail.thread.action.calendar' && calendarGenerationBusy
              ? 'mail-thread-action-quiet mail-thread-action-loading button-loading-dot is-loading'
            : key === 'mail.thread.action.task' && taskGenerationBusy
              ? 'mail-thread-action-quiet mail-thread-action-loading button-loading-dot is-loading'
            : 'mail-thread-action-quiet',
        title:
          key === 'mail.thread.action.summary'
            ? isPinned
              ? t('mail.thread.summaryPinnedTitle')
              : hasSummary
              ? t('mail.thread.summaryExistsTitle')
              : hasActiveSummaryJob
              ? t('mail.thread.summaryInProgress')
              : t('mail.thread.summaryMockTitle')
            : key === 'mail.thread.action.task'
              ? message.llm_blocked === true
                ? llmBlockedTitle(message)
                : t('mail.thread.taskCreateTitle')
            : key === 'mail.thread.action.calendar'
              ? message.llm_blocked === true
                ? llmBlockedTitle(message)
                : t('mail.thread.calendarCreateTitle')
            : key === 'mail.thread.action.reply'
              ? t('mail.thread.action.reply')
              : t('common.notImplemented'),
        onClick: () => {
          if (key === 'mail.thread.action.reply') {
            navigateTo(replyHrefFor(message, ownedEmailAddresses))
            return
          }
          if (key === 'mail.thread.action.task') {
            handleTaskAction(message)
            return
          }
          if (key === 'mail.thread.action.calendar') {
            handleCalendarAction(message)
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
    const taskGenerationBusy = busyAction === `${message.id}-task`
    const calendarGenerationBusy = busyAction === `${message.id}-calendar`
    return outgoingActionKeys.map((key) => ({
      id: key,
      label: t(key),
      disabled:
        ![
          'mail.thread.action.followUp',
          'mail.thread.action.resend',
          'mail.thread.action.calendar',
          'mail.thread.action.task',
        ].includes(key) ||
        busyAction !== null ||
        (key === 'mail.thread.action.calendar' && message.llm_blocked === true) ||
        (key === 'mail.thread.action.task' && message.llm_blocked === true),
      className:
        key === 'mail.thread.action.calendar' && calendarGenerationBusy
          ? 'mail-thread-action-quiet mail-thread-action-loading button-loading-dot is-loading'
        : key === 'mail.thread.action.task' && taskGenerationBusy
          ? 'mail-thread-action-quiet mail-thread-action-loading button-loading-dot is-loading'
          : 'mail-thread-action-quiet',
      title:
        key === 'mail.thread.action.followUp' || key === 'mail.thread.action.resend'
          ? t(key)
          : key === 'mail.thread.action.calendar'
            ? message.llm_blocked === true
              ? llmBlockedTitle(message)
              : t('mail.thread.calendarCreateTitle')
          : key === 'mail.thread.action.task'
            ? message.llm_blocked === true
              ? llmBlockedTitle(message)
              : t('mail.thread.taskCreateTitle')
          : t('common.notImplemented'),
      onClick: () => {
        if (key === 'mail.thread.action.followUp') {
          navigateTo(followUpHrefFor(message))
          return
        }
        if (key === 'mail.thread.action.resend') {
          navigateTo(resendHrefFor(message))
          return
        }
        if (key === 'mail.thread.action.calendar') {
          handleCalendarAction(message)
          return
        }
        if (key === 'mail.thread.action.task') {
          handleTaskAction(message)
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
            <TopNav
              ariaLabelKey="mail.thread.navLabel"
              className="mail-thread-nav"
              items={[
                { href: '/mail', labelKey: 'mail.heading' },
                { href: '/', labelKey: 'top.heading' },
              ]}
            />
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
  const assignedCaseLinks = detail.case_links ?? []
  const focusedMessage =
    detail.thread_messages.find((threadMessage) => threadMessage.id === focusMessageId) ??
    detail.thread_messages.find((threadMessage) => threadMessage.id === messageId) ??
    detail.message
  const mailListHref = mailListHrefFor(focusedMessage)
  const returnHref = returnToHrefFromLocation() ?? mailListHref
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
                  <img alt="" aria-hidden="true" src={gmailIconUrl} />
                </a>
              )}
            </div>
            <div className="mail-thread-case-links">
              <span>{t('mail.thread.assignedCases')}</span>
              <div className="mail-thread-case-badges">
                {assignedCaseLinks.length === 0 ? (
                  <span className="mail-thread-case-empty">
                    {t('mail.thread.noAssignedCases')}
                  </span>
                ) : (
                  assignedCaseLinks.map((caseLink) => (
                    <span className="mail-thread-case-badge-wrap" key={caseLink.case_id}>
                      {caseAssignEditing ? (
                        <span className="mail-thread-case-badge mail-thread-case-badge-editing">
                          {caseLink.title}
                        </span>
                      ) : (
                        <AppLink
                          className="mail-thread-case-badge"
                          href={`/cases/${encodeURIComponent(caseLink.case_id)}`}
                        >
                          {caseLink.title}
                        </AppLink>
                      )}
                      {caseAssignEditing && (
                        <button
                          aria-label={t('mail.thread.caseUnassign', {
                            name: caseLink.title,
                          })}
                          className="mail-thread-case-badge-remove"
                          disabled={caseAssignBusy}
                          onClick={() => void handleUnassignCase(caseLink.case_id, caseLink.title)}
                          type="button"
                        >
                          ×
                        </button>
                      )}
                    </span>
                  ))
                )}
              </div>
              <button
                aria-expanded={caseAssignEditing}
                className="mail-thread-case-settings"
                onClick={() => setCaseAssignEditing((current) => !current)}
                title={t('mail.thread.caseAssignSettings')}
                type="button"
              >
                {t('mail.thread.caseAssignSettingsShort')}
              </button>
            </div>
            {caseAssignEditing && (
              <div className="mail-thread-case-editor">
                <div className="mail-thread-case-editor-input">
                  <label>{t('mail.thread.caseAssignInput')}</label>
                  <SuggestInput
                    ariaLabel={t('mail.thread.caseAssignInput')}
                    autoComplete="off"
                    disabled={caseAssignBusy}
                    maxItems={1}
                    onChange={setCaseAssignInput}
                    options={caseCandidates.map((item) => ({
                      key: item.id,
                      value: item.name,
                      label: item.name,
                      badgeLabel: item.name,
                    }))}
                    placeholder={t('mail.thread.caseAssignPlaceholder')}
                    value={caseAssignInput}
                  />
                  <button
                    className={`button-loading-dot${caseAssignBusy ? ' is-loading' : ''}`}
                    disabled={caseAssignBusy || caseAssignInput.trim() === ''}
                    onClick={() => void handleAssignCase()}
                    type="button"
                  >
                    {t('common.ok')}
                  </button>
                </div>
              </div>
            )}
          </div>
          <TopNav
            ariaLabelKey="mail.thread.navLabel"
            className="mail-thread-nav"
            items={[
              { href: returnHref, labelKey: 'mail.heading' },
              { href: '/', labelKey: 'top.heading' },
            ]}
          />
        </header>

        {(error !== null || notice !== null) && (
          <div className="mail-feedback">
            {error !== null && <p role="alert">{error}</p>}
            {notice !== null && <p>{notice}</p>}
          </div>
        )}

        {attachmentMenu !== null && (
          <div
            aria-label={t('mail.thread.attachmentMenu')}
            className="mail-attachment-context-menu"
            onClick={(event) => event.stopPropagation()}
            role="menu"
            style={{ left: attachmentMenu.x, top: attachmentMenu.y }}
          >
            <button
              className={`button-loading-dot${
                movingAttachmentId === attachmentMenu.attachment.id ? ' is-loading' : ''
              }`}
              disabled={movingAttachmentId !== null}
              onClick={() => void handleMoveAttachmentToStorage()}
              role="menuitem"
              type="button"
            >
              {t('mail.thread.moveAttachmentToStorage')}
            </button>
            <button
              className={`button-loading-dot${
                movingAttachmentId === attachmentMenu.attachment.id ? ' is-loading' : ''
              }`}
              disabled={movingAttachmentId !== null}
              onClick={() => void handleEnqueueAttachmentFetchJob()}
              role="menuitem"
              type="button"
            >
              {t('mail.thread.fetchAttachmentInBackground')}
            </button>
          </div>
        )}

        {llmBlockedMenu !== null && (
          <div
            aria-label={t('mail.thread.llmBlockedMenu')}
            className="mail-attachment-context-menu"
            onClick={(event) => event.stopPropagation()}
            role="menu"
            style={{ left: llmBlockedMenu.x, top: llmBlockedMenu.y }}
          >
            <button
              className={`button-loading-dot${
                busyAction === `${llmBlockedMenu.message.id}-allow-llm`
                  ? ' is-loading'
                  : ''
              }`}
              disabled={busyAction !== null}
              onClick={() => handleAllowLlmFromMenu()}
              role="menuitem"
              type="button"
            >
              {t('mail.thread.allowLlmBlocked')}
            </button>
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
          <AttachmentBadges
            attachments={detail.attachments ?? []}
            movingAttachmentId={movingAttachmentId}
            onContextMenu={handleAttachmentContextMenu}
          />
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
                                className={`${action.className ?? ''} button-loading-dot${
                                  busyAction === `${sendRequest.id}-${action.id}`
                                    ? ' is-loading'
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
                        <MailBodyContent text={sendRequest.body_text} />
                      </section>
                      {(sendRequest.attachments ?? []).length > 0 && (
                        <section className="mail-thread-section">
                          <h3>{t('mail.thread.attachments')}</h3>
                          <AttachmentBadges
                            attachments={sendRequest.attachments ?? []}
                            movingAttachmentId={movingAttachmentId}
                          />
                        </section>
                      )}
                    </article>
                  </div>
                </Fragment>
              )
            }
            const message = entry.message
            const isTarget = message.id === focusMessageId
            const isSent = isSentMessage(message)
            const sender = senderRecipient(message)
            const fromSender = fromRecipient(message)
            const messageImportance =
              message.effective_importance ?? detail.auto_state.effective_importance
            const messageSummary = summaryItems.find(
              (summary) => summary.message_id === message.id,
            )
            const hasActiveSummaryJob =
              detail.summary_jobs?.[message.id] !== undefined
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
                                busyAction === `${message.id}-done` &&
                                action.id === 'done'
                                  ? 'button-loading-dot is-loading'
                                  : ''
                              } ${
                                action.id === 'mail.thread.action.summary' &&
                                busyAction === `${message.id}-summary`
                                  ? 'mail-thread-action-loading button-loading-dot is-loading'
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
                    {renderTaskCasePicker(message)}
                  </div>
                  {!isSent && (
                    <div className="mail-thread-importance">
                      {message.llm_blocked === true && (
                        <span
                          className={`mail-llm-blocked-badge ${
                            busyAction === `${message.id}-allow-llm`
                              ? 'button-loading-dot is-loading'
                              : ''
                          }`.trim()}
                          onContextMenu={(event) =>
                            handleLlmBlockedContextMenu(event, message)
                          }
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
                        <dd><RecipientList recipients={[fromSender]} /></dd>
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

                  {(message.attachments ?? []).length > 0 && (
                    <section className="mail-thread-section">
                      <h3>{t('mail.thread.attachments')}</h3>
                      <AttachmentBadges
                        attachments={message.attachments ?? []}
                        movingAttachmentId={movingAttachmentId}
                        onContextMenu={handleAttachmentContextMenu}
                      />
                    </section>
                  )}

                  {messageSummary !== undefined && (
                    <section className="mail-thread-section mail-thread-mail-summary">
                      <h3>{t('mail.thread.mailSummary')}</h3>
                      <p><LinkifiedText text={messageSummary.summary_text} /></p>
                    </section>
                  )}

                  {(busyAction === `${message.id}-summary` || hasActiveSummaryJob) && (
                    <section
                      aria-live="polite"
                      className="mail-thread-section mail-thread-mail-summary mail-thread-summary-progress"
                    >
                      <h3>{t('mail.thread.action.summarizing')}</h3>
                      <p>{t('mail.thread.summaryInProgress')}</p>
                    </section>
                  )}

                  {messageSummary === undefined ? (
                    <section className="mail-thread-section">
                      <h3>{t('mail.thread.body')}</h3>
                      <MailBodyContent html={message.body_html} text={mailBody(message)} />
                    </section>
                  ) : (
                    <details className="mail-thread-section mail-thread-head-details">
                      <summary>{t('mail.thread.originalBody')}</summary>
                      <MailBodyContent html={message.body_html} text={mailBody(message)} />
                    </details>
                  )}
                  {renderCalendarDraftForm(message)}
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
