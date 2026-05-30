import { useEffect, useRef, useState } from 'react'
import type { DragEvent, FormEvent } from 'react'
import { t } from './i18n'
import { AppLink, navigateTo } from './navigation'
import { listContacts } from './phase3Api'
import type { Contact } from './phase3Api'
import {
  deleteMailDraft,
  generateMailDraft,
  getMailDraftGenerationStandardPrompt,
  listMailDrafts,
  resolveMailDraftAttachments,
  saveMailDraft,
  sendMail,
  updateMailDraftGenerationStandardPrompt,
} from './phase4Api'
import type { MailDraft, MailDraftAttachmentRef } from './phase4Api'
import settingsGearIconUrl from './assets/settings-gear.svg'

type ComposeState = {
  to: string
  cc: string
  bcc: string
  subject: string
  body: string
  autoBody: string
}

type ComposeAttachment = {
  id: string
  key: string
  file?: File
  name: string
  contentType: string
  size: number
  storageObjectId?: string | null
}

type ComposeSignature = {
  id: string
  name: string
  content: string
  system?: boolean
}

type ComposeRecipientSuggestion = {
  key: string
  value: string
  label: string
  statusRank: number
  displayName: string
  emailAddress: string
}

type LlmGenerationLanguage = 'japanese' | 'english'

const noneSignature: ComposeSignature = {
  id: 'none',
  name: t('mail.compose.signature.none'),
  content: '',
  system: true,
}

const signaturesStorageKey = 'caseclosed.compose.signatures'
const selectedSignatureStorageKey = 'caseclosed.compose.selectedSignatureId'
const llmGenerationStandardPromptStorageKey =
  'caseclosed.compose.llmGeneration.standardPrompt'

function initialStateFromQuery(): ComposeState {
  const params = new URLSearchParams(window.location.search)
  return {
    to: params.get('to') ?? '',
    cc: params.get('cc') ?? '',
    bcc: '',
    subject: params.get('subject') ?? '',
    body: params.get('manual_body') ?? '',
    autoBody: params.get('auto_body') ?? params.get('body') ?? '',
  }
}

function newSignatureId() {
  return `signature_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`
}

function normalizeLlmGenerationLanguage(
  value: unknown,
  fallback: LlmGenerationLanguage = 'japanese',
): LlmGenerationLanguage {
  return value === 'english' || value === 'japanese' ? value : fallback
}

function isStoredSignature(value: unknown): value is ComposeSignature {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as Partial<ComposeSignature>).id === 'string' &&
    typeof (value as Partial<ComposeSignature>).name === 'string' &&
    typeof (value as Partial<ComposeSignature>).content === 'string'
  )
}

function loadStoredSignatures(): ComposeSignature[] {
  try {
    const stored = window.localStorage.getItem(signaturesStorageKey)
    const parsed: unknown = stored === null ? [] : JSON.parse(stored)
    const customSignatures = Array.isArray(parsed)
      ? parsed
          .filter(isStoredSignature)
          .filter((signature) => signature.id !== noneSignature.id)
          .map((signature) => ({
            id: signature.id,
            name: signature.name,
            content: signature.content,
          }))
      : []
    return [noneSignature, ...customSignatures]
  } catch {
    return [noneSignature]
  }
}

function saveStoredSignatures(signatures: ComposeSignature[]) {
  window.localStorage.setItem(
    signaturesStorageKey,
    JSON.stringify(signatures.filter((signature) => !signature.system)),
  )
}

function loadSelectedSignatureId(signatures: ComposeSignature[]) {
  const stored = window.localStorage.getItem(selectedSignatureStorageKey)
  return signatures.some((signature) => signature.id === stored)
    ? stored ?? noneSignature.id
    : noneSignature.id
}

function loadLlmGenerationStandardPrompt() {
  return ''
}

function signatureText(content: string) {
  return content.trimEnd()
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

function contactStatusRank(status: string) {
  if (status === 'active') {
    return 0
  }
  if (status === 'archived') {
    return 1
  }
  if (status === 'skipped') {
    return 2
  }
  return 99
}

function recipientSuggestionsFromContacts(
  contacts: Contact[],
): ComposeRecipientSuggestion[] {
  const suggestions: ComposeRecipientSuggestion[] = []
  const seen = new Set<string>()
  for (const contact of contacts) {
    const statusRank = contactStatusRank(contact.status)
    if (statusRank === 99) {
      continue
    }
    for (const emailAddress of contact.email_addresses) {
      if ((emailAddress.status ?? 'active') !== 'active') {
        continue
      }
      const normalizedEmail = emailAddress.normalized_email_address.toLowerCase()
      if (seen.has(normalizedEmail)) {
        continue
      }
      seen.add(normalizedEmail)
      suggestions.push({
        key: `${contact.id}:${emailAddress.id}`,
        value: `${contact.display_name} <${emailAddress.email_address}>`,
        label: `${contact.status} / ${contact.kind ?? 'person'}`,
        statusRank,
        displayName: contact.display_name,
        emailAddress: emailAddress.email_address,
      })
    }
  }
  return suggestions.sort(
    (left, right) =>
      left.statusRank - right.statusRank ||
      left.displayName.localeCompare(right.displayName) ||
      left.emailAddress.localeCompare(right.emailAddress),
  )
}

function describeError(error: unknown) {
  return error instanceof Error ? error.message : t('mail.compose.sendFailed')
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(reader.error ?? new Error(t('mail.compose.sendFailed')))
    reader.onload = () => {
      const result = reader.result
      if (typeof result !== 'string') {
        reject(new Error(t('mail.compose.sendFailed')))
        return
      }
      resolve(result.split(',', 2)[1] ?? '')
    }
    reader.readAsDataURL(file)
  })
}

function fileFromBase64(
  filename: string,
  contentType: string,
  dataBase64: string,
): File {
  const binary = window.atob(dataBase64)
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index)
  }
  return new File([bytes], filename, { type: contentType })
}

function bodyMentionsAttachment(bodyText: string) {
  return /添付|送付|attach(?:ed|ment)?|enclos(?:e|ed|ure)/i.test(bodyText)
}

export default function ComposeMailView() {
  const [form, setForm] = useState<ComposeState>(() => initialStateFromQuery())
  const [signatures, setSignatures] = useState<ComposeSignature[]>(() =>
    loadStoredSignatures(),
  )
  const [recipientSuggestions, setRecipientSuggestions] = useState<
    ComposeRecipientSuggestion[]
  >([])
  const [selectedSignatureId, setSelectedSignatureId] = useState(() =>
    loadSelectedSignatureId(loadStoredSignatures()),
  )
  const [showSignatureSettings, setShowSignatureSettings] = useState(false)
  const [showLlmGenerationSettings, setShowLlmGenerationSettings] = useState(false)
  const [showDraftList, setShowDraftList] = useState(false)
  const [drafts, setDrafts] = useState<MailDraft[]>([])
  const [isDraftBusy, setIsDraftBusy] = useState(false)
  const [isLlmGenerating, setIsLlmGenerating] = useState(false)
  const [signatureName, setSignatureName] = useState('')
  const [signatureContent, setSignatureContent] = useState('')
  const [llmGenerationStandardPrompt, setLlmGenerationStandardPrompt] = useState(
    () => loadLlmGenerationStandardPrompt(),
  )
  const [llmGenerationLanguage, setLlmGenerationLanguage] =
    useState<LlmGenerationLanguage>('japanese')
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
  const [showAutoBody, setShowAutoBody] = useState(false)
  const [llmGenerationInstruction, setLlmGenerationInstruction] = useState('')
  const bodyRef = useRef<HTMLTextAreaElement | null>(null)
  const llmInstructionRef = useRef<HTMLTextAreaElement | null>(null)

  useEffect(() => {
    const selectedSignature =
      signatures.find((signature) => signature.id === selectedSignatureId) ??
      noneSignature
    window.localStorage.setItem(selectedSignatureStorageKey, selectedSignature.id)
  }, [selectedSignatureId, signatures])

  useEffect(() => {
    let canceled = false
    void listContacts()
      .then((contacts) => {
        if (!canceled) {
          setRecipientSuggestions(recipientSuggestionsFromContacts(contacts))
        }
      })
      .catch(() => {
        if (!canceled) {
          setRecipientSuggestions([])
        }
      })
    return () => {
      canceled = true
    }
  }, [])

  useEffect(() => {
    resizeTextAreaToContent(bodyRef.current)
  }, [form.body])

  useEffect(() => {
    resizeTextAreaToContent(llmInstructionRef.current)
  }, [llmGenerationInstruction])

  useEffect(() => {
    let canceled = false
    void getMailDraftGenerationStandardPrompt()
      .then(async (setting) => {
        if (canceled) return
        const localPrompt =
          window.localStorage.getItem(llmGenerationStandardPromptStorageKey) ?? ''
        if (setting.standard_prompt === '' && localPrompt.trim() !== '') {
          const migrated = await updateMailDraftGenerationStandardPrompt(
            localPrompt,
            normalizeLlmGenerationLanguage(setting.generation_language),
          )
          if (!canceled) {
            setLlmGenerationStandardPrompt(migrated.standard_prompt)
            setLlmGenerationLanguage(
              normalizeLlmGenerationLanguage(migrated.generation_language),
            )
          }
          return
        }
        setLlmGenerationStandardPrompt(setting.standard_prompt)
        setLlmGenerationLanguage(
          normalizeLlmGenerationLanguage(setting.generation_language),
        )
      })
      .catch((requestError) => {
        if (!canceled) setError(describeError(requestError))
      })
    return () => {
      canceled = true
    }
  }, [])

  function resizeTextAreaToContent(textarea: HTMLTextAreaElement | null) {
    if (textarea === null) {
      return
    }
    textarea.style.height = 'auto'
    textarea.style.height = `${textarea.scrollHeight}px`
  }

  function updateField(field: keyof ComposeState, value: string) {
    setForm((current) => ({ ...current, [field]: value }))
  }

  function composedBodyText() {
    const manualBody = form.body.trimEnd()
    const autoBody = form.autoBody.trim()
    const selectedSignature =
      signatures.find((signature) => signature.id === selectedSignatureId) ??
      noneSignature
    const selectedSignatureText = signatureText(selectedSignature.content)
    const bodyParts = []
    if (manualBody !== '') {
      bodyParts.push(manualBody)
    }
    if (autoBody !== '') {
      bodyParts.push(autoBody)
    }
    if (selectedSignatureText !== '') {
      bodyParts.push(selectedSignatureText)
    }
    return bodyParts.join('\n\n')
  }

  function defaultScheduleLocal() {
    const date = new Date(Date.now() + 60 * 60 * 1000)
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}T${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
  }

  function localDateTimeToJstIso(value: string) {
    return value === '' ? null : `${value}:00+09:00`
  }

  function isoToLocalDateTime(value: string | null) {
    return value === null ? '' : value.slice(0, 16)
  }

  async function attachmentRefs(): Promise<MailDraftAttachmentRef[]> {
    return Promise.all(attachments.map(async (attachment) => {
      if (attachment.storageObjectId !== undefined && attachment.storageObjectId !== null) {
        return {
          name: attachment.name,
          path: attachment.storageObjectId,
          content_type: attachment.contentType,
          size: attachment.size,
          storage_object_id: attachment.storageObjectId,
        }
      }
      if (attachment.file === undefined) {
        return {
          name: attachment.name,
          content_type: attachment.contentType,
          size: attachment.size,
        }
      }
      const fileWithPath = attachment.file as File & { webkitRelativePath?: string }
      return {
        name: attachment.name,
        path: fileWithPath.webkitRelativePath || attachment.name,
        content_type: attachment.contentType,
        data_base64: await fileToBase64(attachment.file),
        size: attachment.size,
      }
    }))
  }

  async function submitMail(scheduledAtIso: string | null = null) {
    const bodyText = composedBodyText()
    if (
      attachments.length === 0 &&
      bodyMentionsAttachment(bodyText) &&
      !window.confirm(t('mail.compose.missingAttachmentConfirm'))
    ) {
      return
    }

    setFeedback(null)
    setError(null)
    setIsSending(true)

    try {
      const encodedAttachments = await Promise.all(
        attachments.map(async (attachment) => ({
          filename: attachment.name,
          content_type: attachment.contentType,
          ...(attachment.storageObjectId !== undefined && attachment.storageObjectId !== null
            ? { storage_object_id: attachment.storageObjectId }
            : { data_base64: await fileToBase64(attachment.file as File) }),
          size: attachment.size,
        })),
      )
      const sendRequest = await sendMail({
        to_addresses: splitAddressList(form.to),
        cc_addresses: splitAddressList(form.cc),
        bcc_addresses: splitAddressList(form.bcc),
        subject: form.subject,
        body_text: bodyText,
        attachment_names: attachments.map((attachment) => attachment.name),
        attachments: encodedAttachments,
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
          contentType: file.type || 'application/octet-stream',
          size: file.size,
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

  async function handleSaveDraft() {
    setFeedback(null)
    setError(null)
    setIsDraftBusy(true)
    try {
      const draft = await saveMailDraft({
        reply_to_message_id: replyToMessageId,
        to_addresses: splitAddressList(form.to),
        cc_addresses: splitAddressList(form.cc),
        bcc_addresses: splitAddressList(form.bcc),
        subject: form.subject,
        body_text: form.body,
        auto_body_text: form.autoBody,
        selected_signature_id: selectedSignatureId,
        attachment_refs: await attachmentRefs(),
        scheduled_at: localDateTimeToJstIso(scheduledAt),
      })
      setDrafts((current) => [draft, ...current.filter((item) => item.key !== draft.key)])
      setFeedback(t('mail.compose.draft.saved'))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsDraftBusy(false)
    }
  }

  async function handleLoadDrafts() {
    setFeedback(null)
    setError(null)
    setIsDraftBusy(true)
    try {
      const items = await listMailDrafts(replyToMessageId)
      setDrafts(items)
      setShowDraftList(true)
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsDraftBusy(false)
    }
  }

  async function applyDraft(draft: MailDraft) {
    setError(null)
    setFeedback(null)
    setIsDraftBusy(true)
    setForm({
      to: draft.to_addresses.join(', '),
      cc: draft.cc_addresses.join(', '),
      bcc: draft.bcc_addresses.join(', '),
      subject: draft.subject ?? '',
      body: draft.body_text,
      autoBody: draft.auto_body_text,
    })
    if (
      draft.selected_signature_id !== null &&
      signatures.some((signature) => signature.id === draft.selected_signature_id)
    ) {
      setSelectedSignatureId(draft.selected_signature_id)
    }
    setScheduledAt(isoToLocalDateTime(draft.scheduled_at))
    setShowSchedule(draft.scheduled_at !== null)
    setShowDraftList(false)
    try {
      if (draft.attachment_refs.length === 0) {
        setAttachments([])
        setFeedback(t('mail.compose.draft.loaded'))
        return
      }
      const resolved = await resolveMailDraftAttachments(draft.attachment_refs)
      setAttachments(
        resolved.items.map((item, index) => {
          const file = fileFromBase64(item.filename, item.content_type, item.data_base64)
          const storageObjectId = item.storage_object_id
          return {
            id: `${item.path}:${item.size}:${Date.now()}:${index}`,
            key: `${item.path}:${item.size}`,
            ...(storageObjectId === null
              ? { file }
              : {}),
            name: item.filename,
            contentType: item.content_type,
            size: item.size,
            storageObjectId,
          }
        }),
      )
      if (resolved.missing.length > 0) {
        setError(
          t('mail.compose.draft.missingAttachments', {
            names: resolved.missing.map((item) => item.name).join(', '),
          }),
        )
      } else {
        setFeedback(t('mail.compose.draft.loaded'))
      }
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsDraftBusy(false)
    }
  }

  async function handleDeleteDraft(draftKey: string) {
    setIsDraftBusy(true)
    try {
      await deleteMailDraft(draftKey)
      setDrafts((current) => current.filter((draft) => draft.key !== draftKey))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsDraftBusy(false)
    }
  }

  function addSignature() {
    const name = signatureName.trim()
    if (name === '') {
      return
    }
    const nextSignatures = [
      ...signatures,
      {
        id: newSignatureId(),
        name,
        content: signatureContent.trimEnd(),
      },
    ]
    setSignatures(nextSignatures)
    saveStoredSignatures(nextSignatures)
    setSignatureName('')
    setSignatureContent('')
  }

  function deleteSignature(signatureId: string) {
    const signature = signatures.find((item) => item.id === signatureId)
    if (signature === undefined || signature.system) {
      return
    }
    const nextSignatures = signatures.filter((item) => item.id !== signatureId)
    setSignatures(nextSignatures)
    saveStoredSignatures(nextSignatures)
    if (selectedSignatureId === signatureId) {
      setSelectedSignatureId(noneSignature.id)
    }
  }

  async function saveLlmGenerationStandardPrompt() {
    const prompt = llmGenerationStandardPrompt.trimEnd()
    try {
      const setting = await updateMailDraftGenerationStandardPrompt(
        prompt,
        llmGenerationLanguage,
      )
      setLlmGenerationStandardPrompt(setting.standard_prompt)
      setLlmGenerationLanguage(
        normalizeLlmGenerationLanguage(setting.generation_language, llmGenerationLanguage),
      )
      window.localStorage.removeItem(llmGenerationStandardPromptStorageKey)
      setFeedback(t('mail.compose.llmGeneration.standardPromptSaved'))
      setError(null)
    } catch (requestError) {
      setError(describeError(requestError))
      setFeedback(null)
    }
  }

  async function handleLlmGenerationLanguageChange(language: LlmGenerationLanguage) {
    setLlmGenerationLanguage(language)
    try {
      const setting = await updateMailDraftGenerationStandardPrompt(
        llmGenerationStandardPrompt.trimEnd(),
        language,
      )
      setLlmGenerationStandardPrompt(setting.standard_prompt)
      setLlmGenerationLanguage(
        normalizeLlmGenerationLanguage(setting.generation_language, language),
      )
      setError(null)
    } catch (requestError) {
      setError(describeError(requestError))
    }
  }

  async function handleGenerateDraft() {
    setFeedback(null)
    setError(null)
    setIsLlmGenerating(true)
    const standardPrompt = llmGenerationStandardPrompt
    try {
      const generated = await generateMailDraft({
        instruction: llmGenerationInstruction,
        standard_prompt: standardPrompt,
        generation_language: llmGenerationLanguage,
        to_addresses: splitAddressList(form.to),
        cc_addresses: splitAddressList(form.cc),
        bcc_addresses: splitAddressList(form.bcc),
        subject: form.subject,
        auto_body_text: replyToMessageId === null ? '' : form.autoBody,
        body_text: form.body,
        reply_to_message_id: replyToMessageId,
        related_case_summaries: [],
      })
      setForm((current) => ({
        ...current,
        subject:
          current.subject.trim() === '' ? generated.subject : current.subject,
        body: generated.body_text,
      }))
      setLlmGenerationInstruction('')
      setFeedback(t('mail.compose.llmGeneration.generated'))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsLlmGenerating(false)
    }
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
              <datalist id="compose-recipient-suggestions">
                {recipientSuggestions.map((suggestion) => (
                  <option
                    key={suggestion.key}
                    label={suggestion.label}
                    value={suggestion.value}
                  />
                ))}
              </datalist>
              <div className="compose-to-row">
                <label className="compose-field compose-field-line">
                  <span>{t('mail.compose.to')}</span>
                  <input
                    autoComplete="email"
                    list="compose-recipient-suggestions"
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
                      list="compose-recipient-suggestions"
                      onChange={(event) => updateField('cc', event.target.value)}
                      type="text"
                      value={form.cc}
                    />
                  </label>
                  <label className="compose-field compose-field-line">
                    <span>{t('mail.compose.bcc')}</span>
                    <input
                      autoComplete="email"
                      list="compose-recipient-suggestions"
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

              {form.autoBody.trim() !== '' && (
                <section className="compose-auto-body">
                  <button
                    aria-expanded={showAutoBody}
                    onClick={() => setShowAutoBody((current) => !current)}
                    type="button"
                  >
                    {t('mail.compose.autoBody')}
                  </button>
                  {showAutoBody && (
                    <pre aria-label={t('mail.compose.autoBodyPreview')}>
                      {form.autoBody}
                    </pre>
                  )}
                </section>
              )}

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
                    className={`compose-schedule-button button-loading-dot${
                      isSending ? ' is-loading' : ''
                    }`}
                    disabled={
                      isSending ||
                      form.to.trim() === '' ||
                      composedBodyText().trim() === '' ||
                      (showSchedule && scheduledAt === '')
                    }
                    onClick={handleScheduleSend}
                    type="button"
                  >
                    {t('mail.compose.scheduleSend')}
                  </button>
                  <button
                    className={`compose-send-button button-loading-dot${
                      isSending ? ' is-loading' : ''
                    }`}
                    disabled={isSending || form.to.trim() === '' || composedBodyText().trim() === ''}
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

          <aside aria-label={t('mail.compose.tools')} className="mail-panel compose-tools-panel">
            <section className="compose-tool-card compose-draft-card">
              <div className="compose-tool-heading-row">
                <span>{t('mail.compose.draft.heading')}</span>
              </div>
              <div className="compose-tool-actions">
                <button
                  className={`compose-tool-button button-loading-dot${
                    isDraftBusy ? ' is-loading' : ''
                  }`}
                  disabled={isDraftBusy}
                  onClick={handleSaveDraft}
                  type="button"
                >
                  {t('mail.compose.draft.save')}
                </button>
                <button
                  className={`compose-tool-button button-loading-dot${
                    isDraftBusy ? ' is-loading' : ''
                  }`}
                  disabled={isDraftBusy}
                  onClick={handleLoadDrafts}
                  type="button"
                >
                  {t('mail.compose.draft.load')}
                </button>
              </div>
              {showDraftList && (
                <div className="compose-draft-list-wrap">
                  {drafts.length === 0 ? (
                    <p>{t('mail.compose.draft.empty')}</p>
                  ) : (
                    <ul className="compose-draft-list">
                      {drafts.map((draft) => (
                        <li key={draft.key}>
                          <button
                            className={`compose-draft-load-button button-loading-dot${
                              isDraftBusy ? ' is-loading' : ''
                            }`}
                            onClick={() => {
                              void applyDraft(draft)
                            }}
                            type="button"
                          >
                            <span>{draft.name}</span>
                            <small>{draft.updated_at.replace('T', ' ').slice(0, 16)}</small>
                          </button>
                          <button
                            aria-label={t('mail.compose.draft.delete')}
                            className={`compose-draft-delete-button button-loading-dot${
                              isDraftBusy ? ' is-loading' : ''
                            }`}
                            disabled={isDraftBusy}
                            onClick={() => {
                              void handleDeleteDraft(draft.key)
                            }}
                            type="button"
                          >
                            x
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </section>

            <section className="compose-tool-card compose-llm-generation-card">
              <div className="compose-tool-heading-row">
                <span>{t('mail.compose.llmGeneration.heading')}</span>
                <button
                  aria-expanded={showLlmGenerationSettings}
                  aria-label={t('mail.compose.llmGeneration.settings')}
                  className="compose-icon-button"
                  onClick={() =>
                    setShowLlmGenerationSettings((current) => !current)
                  }
                  title={t('mail.compose.llmGeneration.settings')}
                  type="button"
                >
                  <img alt="" aria-hidden="true" src={settingsGearIconUrl} />
                </button>
              </div>
              <div
                aria-label={t('mail.compose.llmGeneration.language')}
                className="compose-language-segmented"
                role="group"
              >
                <button
                  aria-pressed={llmGenerationLanguage === 'japanese'}
                  onClick={() => {
                    void handleLlmGenerationLanguageChange('japanese')
                  }}
                  type="button"
                >
                  {t('mail.compose.llmGeneration.languageJapanese')}
                </button>
                <button
                  aria-pressed={llmGenerationLanguage === 'english'}
                  onClick={() => {
                    void handleLlmGenerationLanguageChange('english')
                  }}
                  type="button"
                >
                  {t('mail.compose.llmGeneration.languageEnglish')}
                </button>
              </div>
              <label className="compose-field">
                <span>{t('mail.compose.llmGeneration.instruction')}</span>
                <textarea
                  onChange={(event) => setLlmGenerationInstruction(event.target.value)}
                  ref={llmInstructionRef}
                  value={llmGenerationInstruction}
                />
              </label>
              <button
                className={`compose-tool-button compose-generation-button button-loading-dot${
                  isLlmGenerating ? ' is-loading' : ''
                }`}
                disabled={isLlmGenerating}
                onClick={() => {
                  void handleGenerateDraft()
                }}
                type="button"
              >
                {isLlmGenerating
                  ? t('mail.compose.llmGeneration.generating')
                  : t('mail.compose.llmGeneration.generate')}
              </button>

              {showLlmGenerationSettings && (
                <div className="compose-tool-settings">
                  <h2>{t('mail.compose.llmGeneration.settingsHeading')}</h2>
                  <label className="compose-field">
                    <span>{t('mail.compose.llmGeneration.standardPrompt')}</span>
                    <textarea
                      onChange={(event) =>
                        setLlmGenerationStandardPrompt(event.target.value)
                      }
                      value={llmGenerationStandardPrompt}
                    />
                  </label>
                  <button
                    className="compose-tool-button"
                    onClick={() => {
                      void saveLlmGenerationStandardPrompt()
                    }}
                    type="button"
                  >
                    {t('mail.compose.llmGeneration.saveStandardPrompt')}
                  </button>
                </div>
              )}
            </section>

            <section className="compose-tool-card compose-signature-card">
              <label className="compose-field">
                <span className="compose-signature-label-row">
                  <span>{t('mail.compose.signature.select')}</span>
                  <button
                    aria-expanded={showSignatureSettings}
                    aria-label={t('mail.compose.signature.settings')}
                    className="compose-icon-button compose-signature-settings-button"
                    onClick={(event) => {
                      event.preventDefault()
                      setShowSignatureSettings((current) => !current)
                    }}
                    title={t('mail.compose.signature.settings')}
                    type="button"
                  >
                    <img alt="" aria-hidden="true" src={settingsGearIconUrl} />
                  </button>
                </span>
                <select
                  onChange={(event) => setSelectedSignatureId(event.target.value)}
                  value={selectedSignatureId}
                >
                  {signatures.map((signature) => (
                    <option key={signature.id} value={signature.id}>
                      {signature.name}
                    </option>
                  ))}
                </select>
              </label>

              {showSignatureSettings && (
                <div className="compose-signature-settings">
                  <h2>{t('mail.compose.signature.heading')}</h2>
                  <label className="compose-field">
                    <span>{t('mail.compose.signature.name')}</span>
                    <input
                      onChange={(event) => setSignatureName(event.target.value)}
                      type="text"
                      value={signatureName}
                    />
                  </label>
                  <label className="compose-field">
                    <span>{t('mail.compose.signature.content')}</span>
                    <textarea
                      onChange={(event) => setSignatureContent(event.target.value)}
                      value={signatureContent}
                    />
                  </label>
                  <button
                    className="compose-tool-button"
                    disabled={signatureName.trim() === ''}
                    onClick={addSignature}
                    type="button"
                  >
                    {t('mail.compose.signature.add')}
                  </button>
                  <ul className="compose-signature-list">
                    {signatures.map((signature) => (
                      <li key={signature.id}>
                        <span>{signature.name}</span>
                        <button
                          disabled={signature.system === true}
                          onClick={() => deleteSignature(signature.id)}
                          type="button"
                        >
                          {t('mail.compose.signature.delete')}
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </section>
          </aside>
        </div>
      </div>
    </main>
  )
}
