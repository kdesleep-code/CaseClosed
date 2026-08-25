import { useEffect, useRef, useState } from 'react'
import type { DragEvent, FormEvent } from 'react'
import { t } from './i18n'
import { authoredBodyMentionsAttachment } from './mailAttachmentReminder'
import { TopNav, navigateTo } from './navigation'
import { listContacts } from './phase3Api'
import type { Contact } from './phase3Api'
import {
  caseRoleSelectorSuggestions,
  describeContactSelectorList,
  resolveRecipientAddressList,
} from './contactSelectors'
import type { ContactSelectorCaseContext } from './contactSelectors'
import { listCases, listCaseStakeholders } from './phase7Api'
import SuggestInput from './SuggestInput'
import type { SuggestInputOption } from './SuggestInput'
import {
  deleteMailDraft,
  generateMailDraft,
  getMailDraftGenerationStandardPrompt,
  getMailSendRequest,
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
  kindRank: number
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
    bcc: params.get('bcc') ?? '',
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

function canceledSendRequestIdFromQuery() {
  return new URLSearchParams(window.location.search).get('canceled_send_request_id')
}

function replyToMessageIdFromQuery() {
  const params = new URLSearchParams(window.location.search)
  return params.get('reply_to_message_id')
}

function relatedCaseIdFromQuery() {
  return new URLSearchParams(window.location.search).get('case_id') ?? ''
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

function contactSuggestKindRank(contact: Contact) {
  if (contact.kind === 'mailing_list') {
    return 1
  }
  if (contact.kind === 'service') {
    return 2
  }
  return 0
}

function recipientSuggestionsFromContacts(
  contacts: Contact[],
  options: { primaryOnly?: boolean } = {},
): ComposeRecipientSuggestion[] {
  const suggestions: ComposeRecipientSuggestion[] = []
  const seen = new Set<string>()
  for (const contact of contacts) {
    const kindRank = contactSuggestKindRank(contact)
    const statusRank = contactStatusRank(contact.status)
    if (statusRank === 99) {
      continue
    }
    for (const emailAddress of contact.email_addresses) {
      if ((emailAddress.status ?? 'active') !== 'active') {
        continue
      }
      if (options.primaryOnly === true && !emailAddress.is_primary) {
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
        kindRank,
        statusRank,
        displayName: contact.display_name,
        emailAddress: emailAddress.email_address,
      })
    }
  }
  return suggestions.sort(
    (left, right) =>
      left.kindRank - right.kindRank ||
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

export default function ComposeMailView() {
  const [form, setForm] = useState<ComposeState>(() => initialStateFromQuery())
  const [signatures, setSignatures] = useState<ComposeSignature[]>(() =>
    loadStoredSignatures(),
  )
  const [recipientSuggestions, setRecipientSuggestions] = useState<
    ComposeRecipientSuggestion[]
  >([])
  const [allRecipientSuggestions, setAllRecipientSuggestions] = useState<
    ComposeRecipientSuggestion[]
  >([])
  const [contacts, setContacts] = useState<Contact[]>([])
  const [caseContexts, setCaseContexts] = useState<ContactSelectorCaseContext[]>([])
  const [relatedCaseId, setRelatedCaseId] = useState(relatedCaseIdFromQuery)
  const [relatedCaseEditing, setRelatedCaseEditing] = useState(false)
  const [relatedCaseInput, setRelatedCaseInput] = useState('')
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
  const [replyToMessageId, setReplyToMessageId] = useState<string | null>(() =>
    replyToMessageIdFromQuery(),
  )
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
    const sendRequestId = canceledSendRequestIdFromQuery()
    if (sendRequestId === null) return

    let canceled = false
    setIsDraftBusy(true)
    void getMailSendRequest(sendRequestId)
      .then(async (sendRequest) => {
        const loadedAttachments = await Promise.all(
          (sendRequest.attachments ?? []).map(async (attachment, index) => {
            const response = await fetch(attachment.download_url, { credentials: 'include' })
            if (!response.ok) throw new Error(t('mail.compose.canceledLoadFailed'))
            const blob = await response.blob()
            const file = new File([blob], attachment.filename, {
              type: (attachment.mime_type ?? blob.type) || 'application/octet-stream',
            })
            return {
              id: `${sendRequest.id}:${index}`,
              key: `${sendRequest.id}:${index}:${attachment.byte_size}`,
              file,
              name: attachment.filename,
              contentType: file.type,
              size: file.size,
            }
          }),
        )
        if (canceled) return
        setForm({
          to: sendRequest.to_addresses.join(', '),
          cc: sendRequest.cc_addresses.join(', '),
          bcc: sendRequest.bcc_addresses.join(', '),
          subject: sendRequest.subject ?? '',
          body: sendRequest.body_text,
          autoBody: '',
        })
        setReplyToMessageId(sendRequest.reply_to_message_id)
        setRelatedCaseId(sendRequest.case_ids?.[0] ?? '')
        setSelectedSignatureId(noneSignature.id)
        setAttachments(loadedAttachments)
        setScheduledAt(isoToLocalDateTime(sendRequest.scheduled_at))
        setShowSchedule(sendRequest.scheduled_at !== null)
        setFeedback(t('mail.compose.canceledLoaded'))
      })
      .catch((requestError) => {
        if (!canceled) setError(describeError(requestError))
      })
      .finally(() => {
        if (!canceled) setIsDraftBusy(false)
      })
    return () => {
      canceled = true
    }
  }, [])

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
          setContacts(contacts)
          setAllRecipientSuggestions(recipientSuggestionsFromContacts(contacts))
          setRecipientSuggestions(
            recipientSuggestionsFromContacts(contacts, { primaryOnly: true }),
          )
        }
      })
      .catch(() => {
        if (!canceled) {
          setContacts([])
          setRecipientSuggestions([])
          setAllRecipientSuggestions([])
        }
      })
    return () => {
      canceled = true
    }
  }, [])

  useEffect(() => {
    let canceled = false
    async function loadCaseContexts() {
      const caseLists = await Promise.all([listCases('all')])
      const cases = Array.from(
        new Map(caseLists.flat().map((caseItem) => [caseItem.id, caseItem])).values(),
      )
      const stakeholders = await Promise.all(
        cases.map(async (caseItem) => ({
          case: caseItem,
          stakeholders: await listCaseStakeholders(caseItem.id),
        })),
      )
      if (!canceled) {
        setCaseContexts(stakeholders)
      }
    }
    void loadCaseContexts().catch(() => {
      if (!canceled) {
        setCaseContexts([])
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

  function resolvedAddressLists() {
    return {
      to: resolveRecipientAddressList(form.to, contacts, caseContexts),
      cc: resolveRecipientAddressList(form.cc, contacts, caseContexts),
      bcc: resolveRecipientAddressList(form.bcc, contacts, caseContexts),
    }
  }

  function recipientPreviewItems(value: string) {
    return describeContactSelectorList(value, contacts, caseContexts)
      .filter((item) => item.contacts.length > 0)
      .map((item) => ({
        selector: item.selector,
        contacts: item.contacts,
      }))
      .filter((item) => item.contacts.length > 0)
  }

  function recipientPreview(value: string) {
    const items = recipientPreviewItems(value)
    if (items.length === 0) {
      return null
    }
    return (
      <div className="compose-recipient-preview" aria-live="polite">
        {items.map((item) => (
          <div key={item.selector} className="compose-recipient-preview-row">
            <span>{item.selector}</span>
            <div>
              {item.contacts.map((contact) => (
                <em key={contact.id}>{contact.display_name}</em>
              ))}
            </div>
          </div>
        ))}
      </div>
    )
  }

  function caseRecipientSuggestions(field: 'to' | 'cc' | 'bcc') {
    const suggestions = caseRoleSelectorSuggestions(form[field], caseContexts)
    return suggestions.map<SuggestInputOption>((suggestion) => ({
      key: suggestion.value,
      value: suggestion.value,
      label: suggestion.label,
      badgeLabel: suggestion.label,
    }))
  }

  function recipientSuggestOptions(field: 'to' | 'cc' | 'bcc'): SuggestInputOption[] {
    const contactSuggestions = form[field].includes('@')
      ? allRecipientSuggestions
      : recipientSuggestions
    return [
      ...contactSuggestions.map((suggestion) => ({
        key: suggestion.key,
        value: suggestion.value,
        label: suggestion.label,
        badgeLabel: suggestion.value,
      })),
      ...caseRecipientSuggestions(field),
    ]
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
    if (form.subject.trim() === '') {
      setFeedback(null)
      setError(t('mail.compose.subjectRequired'))
      return
    }
    if (
      attachments.length === 0 &&
      authoredBodyMentionsAttachment(form.body, form.autoBody) &&
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
      const recipients = resolvedAddressLists()
      setForm((current) => ({
        ...current,
        to: recipients.to.join(', '),
        cc: recipients.cc.join(', '),
        bcc: recipients.bcc.join(', '),
      }))
      const sendRequest = await sendMail({
        to_addresses: recipients.to,
        cc_addresses: recipients.cc,
        bcc_addresses: recipients.bcc,
        subject: form.subject,
        body_text: bodyText,
        attachment_names: attachments.map((attachment) => attachment.name),
        attachments: encodedAttachments,
        reply_to_message_id: replyToMessageId,
        scheduled_at: scheduledAtIso,
        case_ids: relatedCaseId === '' ? [] : [relatedCaseId],
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

  function selectedRelatedCase() {
    return caseContexts.find(({ case: caseItem }) => caseItem.id === relatedCaseId)?.case ?? null
  }

  function applyRelatedCaseInput() {
    const normalized = relatedCaseInput.trim().toLowerCase()
    const selected = caseContexts.find(({ case: caseItem }) =>
      caseItem.id.toLowerCase() === normalized || caseItem.name.toLowerCase() === normalized
    )?.case ?? null
    if (selected === null) {
      setError(t('mail.thread.caseAssignInvalid'))
      return
    }
    setRelatedCaseId(selected.id)
    setRelatedCaseInput(selected.name)
    setRelatedCaseEditing(false)
    setError(null)
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
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
        to_addresses: resolvedAddressLists().to,
        cc_addresses: resolvedAddressLists().cc,
        bcc_addresses: resolvedAddressLists().bcc,
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
        to_addresses: resolvedAddressLists().to,
        cc_addresses: resolvedAddressLists().cc,
        bcc_addresses: resolvedAddressLists().bcc,
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
            <p>C@seClosed</p>
            <h1>{t('mail.compose.heading')}</h1>
          </div>
          <TopNav
            ariaLabelKey="mail.compose.navigation"
            items={[
              { href: '/mail', labelKey: 'nav.mail' },
              { href: '/', labelKey: 'top.heading' },
              { href: '/follow-ups', labelKey: 'nav.followUps' },
              { href: '/cases', labelKey: 'nav.cases' },
              { href: '/tasks', labelKey: 'nav.tasks' },
              { href: '/calendar', labelKey: 'nav.calendar' },
              { href: '/contacts', labelKey: 'nav.contacts' },
            ]}
          />
        </header>

        <div className="compose-layout">
          <section className="mail-panel compose-main-panel">
            <form className="compose-form" onSubmit={handleSubmit}>
              <div className="compose-to-row">
                <label className="compose-field compose-field-line">
                  <span>{t('mail.compose.to')}</span>
                  <SuggestInput
                    ariaLabel={t('mail.compose.to')}
                    autoComplete="email"
                    onChange={(value) => updateField('to', value)}
                    options={recipientSuggestOptions('to')}
                    value={form.to}
                  />
                  {recipientPreview(form.to)}
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
                    <SuggestInput
                      ariaLabel={t('mail.compose.cc')}
                      autoComplete="email"
                      onChange={(value) => updateField('cc', value)}
                      options={recipientSuggestOptions('cc')}
                      value={form.cc}
                    />
                    {recipientPreview(form.cc)}
                  </label>
                  <label className="compose-field compose-field-line">
                    <span>{t('mail.compose.bcc')}</span>
                    <SuggestInput
                      ariaLabel={t('mail.compose.bcc')}
                      autoComplete="email"
                      onChange={(value) => updateField('bcc', value)}
                      options={recipientSuggestOptions('bcc')}
                      value={form.bcc}
                    />
                    {recipientPreview(form.bcc)}
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

              <div className="mail-thread-related-badge-row compose-related-case-row">
                <div className="mail-thread-case-links">
                  <span>{t("mail.compose.relatedCase")}</span>
                  <div className="mail-thread-case-badges">
                    {selectedRelatedCase() === null ? (
                      <span className="mail-thread-case-empty">
                        {t("mail.compose.relatedCaseNone")}
                      </span>
                    ) : (
                      <span className="mail-thread-case-badge-wrap">
                        <span className={`mail-thread-case-badge${relatedCaseEditing ? " mail-thread-case-badge-editing" : ""}`}>
                          {selectedRelatedCase()?.name}
                        </span>
                        {relatedCaseEditing && (
                          <button
                            aria-label={t("mail.thread.caseUnassign", { name: selectedRelatedCase()?.name ?? "" })}
                            className="mail-thread-case-badge-remove"
                            onClick={() => {
                              setRelatedCaseId("")
                              setRelatedCaseInput("")
                            }}
                            type="button"
                          >×</button>
                        )}
                      </span>
                    )}
                  </div>
                  <button
                    aria-expanded={relatedCaseEditing}
                    className="mail-thread-case-settings"
                    onClick={() => {
                      setRelatedCaseEditing((current) => !current)
                      setRelatedCaseInput(selectedRelatedCase()?.name ?? "")
                    }}
                    title={t("mail.thread.caseAssignSettings")}
                    type="button"
                  >
                    <img alt="" aria-hidden="true" src={settingsGearIconUrl} />
                  </button>
                </div>
              </div>
              {relatedCaseEditing && (
                <div className="mail-thread-case-editor compose-related-case-editor">
                  <div className="mail-thread-case-editor-input">
                    <label>{t("mail.thread.caseAssignInput")}</label>
                    <SuggestInput
                      ariaLabel={t("mail.thread.caseAssignInput")}
                      autoComplete="off"
                      maxItems={1}
                      onChange={setRelatedCaseInput}
                      options={caseContexts.map(({ case: caseItem }) => ({
                        key: caseItem.id,
                        value: caseItem.name,
                        label: caseItem.name,
                        badgeLabel: caseItem.name,
                      }))}
                      placeholder={t("mail.thread.caseAssignPlaceholder")}
                      value={relatedCaseInput}
                    />
                    <button
                      disabled={relatedCaseInput.trim() === ""}
                      onClick={applyRelatedCaseInput}
                      type="button"
                    >
                      {t("common.ok")}
                    </button>
                  </div>
                </div>
              )}

              <label className="compose-field compose-body-field">
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
                    onClick={() => {
                      void submitMail()
                    }}
                    type="button"
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
                  <p>{t("mail.compose.llmGeneration.settingsMoved")}</p>
                  <a className="compose-tool-button" href="/settings?tab=llm">
                    {t("mail.compose.llmGeneration.openLlmSettings")}
                  </a>
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
