import { useEffect, useRef, useState } from 'react'
import type { DragEvent, FormEvent } from 'react'
import { t } from './i18n'
import { AppLink, navigateTo } from './navigation'
import { sendMail } from './phase4Api'

type ComposeState = {
  to: string
  cc: string
  bcc: string
  subject: string
  body: string
}

type ComposeAttachment = {
  id: string
  key: string
  file: File
  name: string
}

function initialStateFromQuery(): ComposeState {
  const params = new URLSearchParams(window.location.search)
  return {
    to: params.get('to') ?? '',
    cc: params.get('cc') ?? '',
    bcc: '',
    subject: params.get('subject') ?? '',
    body: params.get('body') ?? '',
  }
}

function replyToMessageIdFromQuery() {
  const params = new URLSearchParams(window.location.search)
  return params.get('reply_to_message_id')
}

function splitAddressList(value: string) {
  return value
    .split(/[,\n;]/)
    .map((address) => address.trim())
    .filter((address) => address !== '')
}

function describeError(error: unknown) {
  return error instanceof Error ? error.message : t('mail.compose.sendFailed')
}

export default function ComposeMailView() {
  const [form, setForm] = useState<ComposeState>(() => initialStateFromQuery())
  const [replyToMessageId] = useState<string | null>(() => replyToMessageIdFromQuery())
  const [showCcBcc, setShowCcBcc] = useState(() => {
    const params = new URLSearchParams(window.location.search)
    return (params.get('cc') ?? '') !== ''
  })
  const [attachments, setAttachments] = useState<ComposeAttachment[]>([])
  const [feedback, setFeedback] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isSending, setIsSending] = useState(false)
  const [showSchedule, setShowSchedule] = useState(false)
  const [scheduledAt, setScheduledAt] = useState('')
  const bodyRef = useRef<HTMLTextAreaElement | null>(null)

  useEffect(() => {
    const textarea = bodyRef.current
    if (textarea === null) {
      return
    }
    textarea.style.height = 'auto'
    textarea.style.height = `${textarea.scrollHeight}px`
  }, [form.body])

  function updateField(field: keyof ComposeState, value: string) {
    setForm((current) => ({ ...current, [field]: value }))
  }

  function defaultScheduleLocal() {
    const date = new Date(Date.now() + 60 * 60 * 1000)
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}T${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
  }

  function localDateTimeToJstIso(value: string) {
    return value === '' ? null : `${value}:00+09:00`
  }

  async function submitMail(scheduledAtIso: string | null = null) {
    setFeedback(null)
    setError(null)
    setIsSending(true)

    try {
      const sendRequest = await sendMail({
        to_addresses: splitAddressList(form.to),
        cc_addresses: splitAddressList(form.cc),
        bcc_addresses: splitAddressList(form.bcc),
        subject: form.subject,
        body_text: form.body,
        attachment_names: attachments.map((attachment) => attachment.name),
        reply_to_message_id: replyToMessageId,
        scheduled_at: scheduledAtIso,
      })
      setFeedback(t('mail.compose.scheduleQueued'))
      navigateTo(
        `/mail/${encodeURIComponent(sendRequest.reply_to_message_id ?? sendRequest.id)}`,
      )
    } catch (sendError) {
      setError(describeError(sendError))
    } finally {
      setIsSending(false)
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    await submitMail()
  }

  async function handleScheduleSend() {
    if (!showSchedule) {
      setScheduledAt((current) => current || defaultScheduleLocal())
      setShowSchedule(true)
      return
    }
    await submitMail(localDateTimeToJstIso(scheduledAt))
  }

  function handleAttachmentChange(files: FileList | null) {
    if (files === null || files.length === 0) {
      return
    }
    const attachmentKey = (file: File) =>
      `${file.name}:${file.size}:${file.lastModified}`
    setAttachments((current) => {
      const knownKeys = new Set(current.map((attachment) => attachment.key))
      const selectedAttachments = Array.from(files)
        .filter((file) => !knownKeys.has(attachmentKey(file)))
        .map((file, index) => ({
          id: `${attachmentKey(file)}:${Date.now()}:${index}`,
          key: attachmentKey(file),
          file,
          name: file.name,
        }))
      return [...current, ...selectedAttachments]
    })
  }

  function handleAttachmentDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    handleAttachmentChange(event.dataTransfer.files)
  }

  function removeAttachment(idToRemove: string) {
    setAttachments((current) =>
      current.filter((attachment) => attachment.id !== idToRemove),
    )
  }

  return (
    <main className="app-shell">
      <div className="compose-shell">
        <header className="maintenance-header">
          <div>
            <p>CaseClosed</p>
            <h1>{t('mail.compose.heading')}</h1>
          </div>
          <nav aria-label={t('mail.compose.navigation')} className="maintenance-nav">
            <AppLink href="/mail">{t('mail.heading')}</AppLink>
            <AppLink href="/">{t('top.heading')}</AppLink>
          </nav>
        </header>

        <div className="compose-layout">
          <section className="mail-panel compose-main-panel">
            <form className="compose-form" onSubmit={handleSubmit}>
              <div className="compose-to-row">
                <label className="compose-field compose-field-line">
                  <span>{t('mail.compose.to')}</span>
                  <input
                    autoComplete="email"
                    onChange={(event) => updateField('to', event.target.value)}
                    type="text"
                    value={form.to}
                  />
                </label>

                <div className="compose-recipient-toggles">
                  <button
                    aria-expanded={showCcBcc}
                    onClick={() => setShowCcBcc((current) => !current)}
                    type="button"
                  >
                    {t('mail.compose.ccBcc')}
                  </button>
                </div>
              </div>

              {showCcBcc && (
                <div className="compose-optional-recipients">
                  <label className="compose-field compose-field-line">
                    <span>{t('mail.compose.cc')}</span>
                    <input
                      autoComplete="email"
                      onChange={(event) => updateField('cc', event.target.value)}
                      type="text"
                      value={form.cc}
                    />
                  </label>
                  <label className="compose-field compose-field-line">
                    <span>{t('mail.compose.bcc')}</span>
                    <input
                      autoComplete="email"
                      onChange={(event) => updateField('bcc', event.target.value)}
                      type="text"
                      value={form.bcc}
                    />
                  </label>
                </div>
              )}

              <label className="compose-field compose-field-line">
                <span>{t('mail.compose.subject')}</span>
                <input
                  onChange={(event) => updateField('subject', event.target.value)}
                  type="text"
                  value={form.subject}
                />
              </label>

              <label className="compose-field compose-body-field">
                <span className="visually-hidden">{t('mail.compose.body')}</span>
                <textarea
                  aria-label={t('mail.compose.body')}
                  onChange={(event) => updateField('body', event.target.value)}
                  ref={bodyRef}
                  value={form.body}
                />
              </label>

              <div className="compose-footer">
                <section className="compose-attachments" aria-label={t('mail.compose.attachments')}>
                  <div
                    className="compose-attachment-dropzone"
                    onDragOver={(event) => event.preventDefault()}
                    onDrop={handleAttachmentDrop}
                  >
                    {t('mail.compose.dropAttachment')}
                  </div>
                  {attachments.length > 0 && (
                    <ul className="compose-attachment-list">
                      {attachments.map((attachment) => (
                        <li key={attachment.id}>
                          <span>{attachment.name}</span>
                          <button
                            aria-label={t('mail.compose.removeAttachment', {
                              name: attachment.name,
                            })}
                            onClick={() => removeAttachment(attachment.id)}
                            type="button"
                          >
                            x
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>

                <div className="compose-actions">
                  {showSchedule && (
                    <label className="compose-schedule-field">
                      <span>{t('mail.compose.scheduledAt')}</span>
                      <input
                        aria-label={t('mail.compose.scheduledAt')}
                        onChange={(event) => setScheduledAt(event.target.value)}
                        type="datetime-local"
                        value={scheduledAt}
                      />
                    </label>
                  )}
                  <button
                    className="compose-schedule-button"
                    disabled={
                      isSending ||
                      form.to.trim() === '' ||
                      form.body.trim() === '' ||
                      (showSchedule && scheduledAt === '')
                    }
                    onClick={handleScheduleSend}
                    type="button"
                  >
                    {t('mail.compose.scheduleSend')}
                  </button>
                  <button
                    className="compose-send-button"
                    disabled={isSending || form.to.trim() === '' || form.body.trim() === ''}
                    type="submit"
                  >
                    {t('mail.compose.send')}
                  </button>
                </div>
              </div>
              {(feedback !== null || error !== null) && (
                <div
                  className={`compose-feedback ${error === null ? 'is-success' : 'is-error'}`}
                  role="status"
                >
                  {error ?? feedback}
                </div>
              )}
            </form>
          </section>

          <aside aria-label={t('mail.compose.tools')} className="mail-panel compose-tools-panel" />
        </div>
      </div>
    </main>
  )
}
