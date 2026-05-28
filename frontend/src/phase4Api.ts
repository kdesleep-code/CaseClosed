type ApiError = {
  code: string
  message: string
}

type SuccessResponse<T> = {
  ok: true
  data: T
}

type ErrorResponse = {
  ok: false
  error: ApiError
}

type ListResponse<T> = {
  items: T[]
  next_cursor?: string | null
  limit?: number
}

type ItemsResponse<T> = {
  items: T[]
}

export type MailListItem = {
  id: string
  gmail_message_id: string
  gmail_thread_id: string
  thread_id?: string
  received_at: string
  received_date?: string
  subject: string | null
  from_address: string
  from_name?: string | null
  reply_to_address: string | null
  list_id: string | null
  processed_status: string
  read_status?: string
  read_at?: string | null
  user_importance: string | null
  effective_importance: string
  importance_rank?: number
  external_importance: string | null
  suggested_importance: string | null
  llm_run_id: string | null
  pending_reason: string | null
  llm_blocked?: boolean
  llm_block_reason?: string | null
  llm_blocked_at?: string | null
  sender_contact?: {
    id: string
    display_name: string
    avatar_url: string | null
    kind: string
    status?: string
    tags?: string[]
  } | null
  case_links?: Array<{
    id: string
    title: string
  }>
  summary?: string | null
}

export type MailContactSummary = {
  id: string
  display_name: string
  avatar_url: string | null
  kind: string
  status?: string
  tags?: string[]
}

export type MailRecipient = {
  email_address: string
  contact: MailContactSummary | null
}

export type MailThreadMessage = MailListItem & {
  thread_id: string
  sender_address: string | null
  to_addresses: string[]
  cc_addresses: string[]
  bcc_addresses: string[]
  to_recipients?: MailRecipient[]
  cc_recipients?: MailRecipient[]
  bcc_recipients?: MailRecipient[]
  from_contact?: MailContactSummary | null
  message_id_header: string | null
  in_reply_to_header: string | null
  references_header: string | null
  snippet: string | null
  gmail_link: string | null
  external_starred: boolean
  gmail_labels?: string[]
  body_text?: string | null
  body_html?: string | null
  created_at: string
  updated_at: string
  version: number
}

export type MailSummary = {
  summary_text: string
  items?: Array<{
    id: string
    message_id: string
    summary_text: string
    action_required: boolean | null
    deadline_text: string | null
    next_action: string | null
    key_points: string[]
    translation_text?: string | null
    language: string
    llm_run_id: string | null
    updated_at: string
    version: number
  }>
}

export type MailDetail = {
  message: MailThreadMessage
  thread_messages: MailThreadMessage[]
  scheduled_send_requests?: MailSendRequest[]
  user_state: {
    user_importance: string | null
    processed_status: string
    processed_at: string | null
    read_status: string
    read_at: string | null
    version: number
  }
  auto_state: {
    external_importance: string | null
    suggested_importance: string | null
    llm_run_id: string | null
    effective_importance: string
    pending_reason: string | null
    llm_blocked?: boolean
    llm_block_reason?: string | null
    llm_blocked_at?: string | null
  }
  summary: MailSummary | null
  available_actions: string[]
}

export type MailSendPayload = {
  to_addresses: string[]
  cc_addresses?: string[]
  bcc_addresses?: string[]
  subject?: string
  body_text: string
  attachment_names?: string[]
  attachments?: Array<{
    filename: string
    content_type: string
    data_base64: string
    size: number
  }>
  reply_to_message_id?: string | null
  scheduled_at?: string | null
}

export type MailSendRequest = {
  id: string
  status: string
  to_addresses: string[]
  cc_addresses: string[]
  bcc_addresses: string[]
  subject: string | null
  body_text: string
  attachment_names: string[]
  reply_to_message_id: string | null
  sent_message_id: string | null
  scheduled_at: string | null
  created_at: string
  updated_at: string
  version: number
}

export type MailDraftGenerationPayload = {
  instruction?: string | null
  standard_prompt?: string | null
  to_addresses?: string[]
  cc_addresses?: string[]
  bcc_addresses?: string[]
  subject?: string | null
  auto_body_text?: string | null
  body_text?: string | null
  reply_to_message_id?: string | null
  related_case_summaries?: Array<Record<string, unknown>>
}

export type MailDraftGenerationResult = {
  subject: string
  body_text: string
  llm_run_id: string
}

export type MailDraftAttachmentRef = {
  name: string
  path: string
}

export type ResolvedMailDraftAttachment = {
  filename: string
  path: string
  content_type: string
  data_base64: string
  size: number
}

export type MailDraft = {
  key: string
  name: string
  reply_to_message_id: string | null
  to_addresses: string[]
  cc_addresses: string[]
  bcc_addresses: string[]
  subject: string | null
  body_text: string
  auto_body_text: string
  selected_signature_id: string | null
  attachment_refs: MailDraftAttachmentRef[]
  scheduled_at: string | null
  created_at: string
  updated_at: string
  version: number
}

export type MailDraftPayload = {
  reply_to_message_id?: string | null
  to_addresses: string[]
  cc_addresses?: string[]
  bcc_addresses?: string[]
  subject?: string | null
  body_text: string
  auto_body_text?: string
  selected_signature_id?: string | null
  attachment_refs?: MailDraftAttachmentRef[]
  scheduled_at?: string | null
}

export type ScheduledSendRequest = MailSendRequest

export type LlmBlockedMail = {
  id: string
  received_at: string
  subject: string | null
  from_address: string
  llm_block_reason: string | null
  llm_blocked_at: string | null
}

export type LlmBlockFilter = {
  id: string
  query_text: string
  reason: string
  is_enabled: boolean
  created_at: string
  updated_at: string
  version: number
}

export type MailLlmBlockFilterResult = {
  filter: LlmBlockFilter
  matched: number
  changed: number
  items: LlmBlockedMail[]
}

export type LlmModelProfile = {
  id: string
  provider: string
  model: string
  api_key_env: string | null
  endpoint_env: string | null
  timeout_seconds: number
}

export type LlmFunctionConfig = {
  function_type: string
  label: string
  profile_id: string
  env_key: string
}

export type LlmModelConfig = {
  profiles: LlmModelProfile[]
  functions: LlmFunctionConfig[]
}

export type GoogleGmailStatus = {
  configured: boolean
  connected: boolean
  connected_at: string | null
  last_error: string | null
  scopes: string[]
  send_enabled?: boolean
  redirect_uri: string
  has_refresh_token: boolean
  token_expires_at: string | null
  mail_loading_enabled: boolean
}

export type GoogleGmailImportResult = {
  imported: boolean
  reason?: string
  subject?: string | null
  from_address?: string | null
  received_at?: string | null
  mail: null | {
    message_id: string
    gmail_message_id: string
    pending: boolean
    pending_address: string | null
    pending_reason: string | null
    queued_job_id: string | null
    queued_contact_ai_memo_job_id?: string | null
  }
}

export type GoogleGmailImportByDateResult = {
  date: string
  imported_count: number
  candidate_count: number
  skipped_out_of_date: number
  items: Array<{
    subject: string | null
    from_address: string
    received_at: string
    mail: NonNullable<GoogleGmailImportResult['mail']>
  }>
}

export type MailListFilters = {
  tab?: 'all' | 'pending' | 'unprocessed' | 'processed' | 'skip'
  processed?: 'all' | 'processed' | 'unprocessed' | '0' | '1'
  importance?: 'all' | 'pinned' | 'high' | 'middle' | 'low' | 'skip' | 'pending' | 'unclassified'
  importance_any?: string
  needs_action?: boolean | '0' | '1'
  contact_status?: 'all' | 'pending' | 'resolved'
  read?: 'all' | 'read' | 'unread'
  q?: string
  date_from?: string
  date_to?: string
  limit?: number
  cursor?: string
}

export type MailListPage = {
  items: MailListItem[]
  next_cursor: string | null
  limit: number
}

export type MailDateSummary = {
  date: string
  count: number
}

export class Phase4ApiError extends Error {
  code: string
  status: number

  constructor(status: number, error: ApiError) {
    super(error.message)
    this.name = 'Phase4ApiError'
    this.code = error.code
    this.status = status
  }
}

function hasApiError(payload: unknown): payload is ErrorResponse {
  return (
    typeof payload === 'object' &&
    payload !== null &&
    (payload as Partial<ErrorResponse>).ok === false &&
    typeof (payload as Partial<ErrorResponse>).error?.code === 'string' &&
    typeof (payload as Partial<ErrorResponse>).error?.message === 'string'
  )
}

function isSuccessResponse<T>(payload: unknown): payload is SuccessResponse<T> {
  return (
    typeof payload === 'object' &&
    payload !== null &&
    (payload as Partial<SuccessResponse<T>>).ok === true &&
    'data' in payload
  )
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: 'include',
    ...init,
  })
  const responseText = await response.text()
  let payload: unknown
  try {
    payload = responseText === '' ? null : JSON.parse(responseText)
  } catch {
    payload = null
  }

  if (!response.ok || !isSuccessResponse<T>(payload)) {
    const error = hasApiError(payload)
      ? payload.error
      : {
          code: 'PHASE_4_REQUEST_FAILED',
          message: responseText === '' ? 'Request failed.' : responseText,
        }
    throw new Phase4ApiError(response.status, error)
  }

  return payload.data
}

export async function listMails(): Promise<MailListItem[]> {
  const data = await listMailPage()
  return data.items
}

export async function listMailPage(
  filters: MailListFilters = {},
): Promise<MailListPage> {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== null && value !== '') {
      params.set(key, String(value))
    }
  }
  const query = params.toString()
  const data = await request<ListResponse<MailListItem>>(
    `/api/v1/mails${query === '' ? '' : `?${query}`}`,
  )
  return {
    items: data.items,
    next_cursor: data.next_cursor ?? null,
    limit: data.limit ?? data.items.length,
  }
}

export async function listMailDates(
  tab: MailListFilters['tab'] = 'all',
): Promise<MailDateSummary[]> {
  const params = new URLSearchParams()
  if (tab !== undefined && tab !== null) {
    params.set('tab', tab)
  }
  const data = await request<ItemsResponse<MailDateSummary>>(
    `/api/v1/mails/dates?${params.toString()}`,
  )
  return data.items
}

export function getMailDetail(messageId: string): Promise<MailDetail> {
  return request<MailDetail>(`/api/v1/mails/${encodeURIComponent(messageId)}`)
}

export function sendMail(payload: MailSendPayload): Promise<MailSendRequest> {
  return request('/api/v1/mails/send', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function generateMailDraft(
  payload: MailDraftGenerationPayload,
): Promise<MailDraftGenerationResult> {
  return request('/api/v1/mails/generate-draft', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export async function saveMailDraft(payload: MailDraftPayload): Promise<MailDraft> {
  return request('/api/v1/mail-drafts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export async function listMailDrafts(
  replyToMessageId: string | null,
): Promise<MailDraft[]> {
  const params = new URLSearchParams()
  if (replyToMessageId !== null) {
    params.set('reply_to_message_id', replyToMessageId)
  }
  const query = params.toString()
  const data = await request<ItemsResponse<MailDraft>>(
    `/api/v1/mail-drafts${query === '' ? '' : `?${query}`}`,
  )
  return data.items
}

export function deleteMailDraft(draftKey: string): Promise<{ key: string }> {
  return request(`/api/v1/mail-drafts/${encodeURIComponent(draftKey)}`, {
    method: 'DELETE',
  })
}

export function resolveMailDraftAttachments(
  attachmentRefs: MailDraftAttachmentRef[],
): Promise<{
  items: ResolvedMailDraftAttachment[]
  missing: MailDraftAttachmentRef[]
}> {
  return request('/api/v1/mail-drafts/attachments/resolve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ attachment_refs: attachmentRefs }),
  })
}

export function sendMailRequestNow(
  sendRequestId: string,
): Promise<MailSendRequest> {
  return request(
    `/api/v1/mails/send-requests/${encodeURIComponent(sendRequestId)}/send-now`,
    { method: 'POST' },
  )
}

export function rescheduleMailRequest(
  sendRequestId: string,
  scheduledAt: string,
): Promise<MailSendRequest> {
  return request(
    `/api/v1/mails/send-requests/${encodeURIComponent(sendRequestId)}/schedule`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scheduled_at: scheduledAt }),
    },
  )
}

export function cancelMailSendRequest(
  sendRequestId: string,
): Promise<MailSendRequest> {
  return request(
    `/api/v1/mails/send-requests/${encodeURIComponent(sendRequestId)}/cancel`,
    { method: 'POST' },
  )
}

export async function listMailSendRequests(): Promise<MailSendRequest[]> {
  const data = await request<ItemsResponse<MailSendRequest>>(
    '/api/v1/mails/send-requests',
  )
  return data.items
}

export async function listLlmBlockedMails(): Promise<LlmBlockedMail[]> {
  const data = await request<ItemsResponse<LlmBlockedMail>>(
    '/api/v1/mails/llm-blocked',
  )
  return data.items
}

export async function listLlmBlockFilters(): Promise<LlmBlockFilter[]> {
  const data = await request<ItemsResponse<LlmBlockFilter>>(
    '/api/v1/mails/llm-block-filters',
  )
  return data.items
}

export function applyMailLlmBlockFilter(
  q: string,
  reason: string | null,
): Promise<MailLlmBlockFilterResult> {
  return request('/api/v1/mails/llm-block-filter', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ q, reason }),
  })
}

export function updateLlmBlockFilter(
  filterId: string,
  isEnabled: boolean,
): Promise<LlmBlockFilter> {
  return request(`/api/v1/mails/llm-block-filters/${encodeURIComponent(filterId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ is_enabled: isEnabled }),
  })
}

export function getLlmModelConfig(): Promise<LlmModelConfig> {
  return request('/api/v1/mails/llm-model-config')
}

export function updateLlmModelAssignment(
  functionType: string,
  profileId: string,
): Promise<LlmModelConfig> {
  return request('/api/v1/mails/llm-model-config', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ function_type: functionType, profile_id: profileId }),
  })
}

export function getGoogleGmailStatus(): Promise<GoogleGmailStatus> {
  return request('/api/v1/google/gmail/status')
}

export function createGoogleGmailConnectUrl(): Promise<{
  authorization_url: string
  mail_loading_enabled: boolean
}> {
  return request('/api/v1/google/gmail/connect-url', { method: 'POST' })
}

export function disconnectGoogleGmail(): Promise<GoogleGmailStatus> {
  return request('/api/v1/google/gmail/disconnect', { method: 'POST' })
}

export function importLatestUnloadedGoogleGmail(): Promise<GoogleGmailImportResult> {
  return request('/api/v1/google/gmail/import-latest-unloaded', { method: 'POST' })
}

export function importUnloadedGoogleGmailByDate(
  date: string,
): Promise<GoogleGmailImportByDateResult> {
  return request('/api/v1/google/gmail/import-unloaded-by-date', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ date }),
  })
}

export function updateMailImportance(
  messageId: string,
  importance: string,
): Promise<MailDetail> {
  return request(`/api/v1/mails/${encodeURIComponent(messageId)}/importance`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ importance }),
  })
}

export function requestMailSummary(messageId: string): Promise<{ job_id: string }> {
  return request(`/api/v1/mails/${encodeURIComponent(messageId)}/summary`, {
    method: 'POST',
  })
}

export function processMail(messageId: string): Promise<MailDetail> {
  return request(`/api/v1/mails/${encodeURIComponent(messageId)}/process`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason: 'manual' }),
  })
}

export function markMailRead(messageId: string): Promise<MailDetail> {
  return request(`/api/v1/mails/${encodeURIComponent(messageId)}/read`, {
    method: 'POST',
  })
}

export function markMailUnread(messageId: string): Promise<MailDetail> {
  return request(`/api/v1/mails/${encodeURIComponent(messageId)}/unread`, {
    method: 'POST',
  })
}

export function unprocessMail(messageId: string): Promise<MailDetail> {
  return request(`/api/v1/mails/${encodeURIComponent(messageId)}/unprocess`, {
    method: 'POST',
  })
}
