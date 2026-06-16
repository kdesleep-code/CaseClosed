import type { StorageObject } from './phase3Api'

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
  attachment_count?: number
  has_attachments?: boolean
  sender_contact?: {
    id: string
    display_name: string
    avatar_url: string | null
    kind: string
    status?: string
    sender_resolution_mode?: 'self' | 'reply_to'
    tags?: string[]
  } | null
  case_links?: MailCaseLink[]
  summary?: string | null
}

export type MailCaseLink = {
  id: string
  case_id: string
  title: string
}

export type MailAttachment = {
  id: string
  message_id: string
  filename: string
  mime_type: string | null
  byte_size: number
  download_url: string
  cached: boolean
  storage_object_id: string | null
  source_type?: string | null
}

export type MailAttachmentStorageMoveResult = {
  attachment: MailAttachment
  storage_object: StorageObject
}

export type MailAttachmentFetchJobResult = {
  job_id: string
  attachment: MailAttachment
}

export type MailContactSummary = {
  id: string
  display_name: string
  avatar_url: string | null
  kind: string
  status?: string
  sender_resolution_mode?: 'self' | 'reply_to'
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
  attachments?: MailAttachment[]
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
  summary_jobs?: Record<
    string,
    {
      job_id: string
      status: string
      created_at: string
      updated_at: string
    }
  >
  case_links?: MailCaseLink[]
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
  attachments?: MailAttachment[]
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
    data_base64?: string
    storage_object_id?: string
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
  attachments?: MailAttachment[]
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
  generation_language?: 'japanese' | 'english'
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

export type MailDraftGenerationStandardPrompt = {
  standard_prompt: string
  generation_language: 'japanese' | 'english'
}

export type MailDraftAttachmentRef = {
  name: string
  path?: string
  content_type?: string | null
  data_base64?: string
  size?: number
  storage_object_id?: string | null
}

export type ResolvedMailDraftAttachment = {
  filename: string
  path: string
  content_type: string
  data_base64: string
  size: number
  storage_object_id: string | null
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
  calendar_read_enabled?: boolean
  calendar_write_enabled?: boolean
  redirect_uri: string
  has_refresh_token: boolean
  token_expires_at: string | null
  mail_loading_enabled: boolean
  auto_import: GoogleGmailAutoImportSettings
  calendar_auto_sync: GoogleCalendarAutoSyncSettings
}

export type GoogleGmailAutoImportSettings = {
  enabled: boolean
  interval_minutes: number
  max_messages_per_run: number
  last_run_at: string | null
  last_success_at: string | null
  last_error: string | null
  last_imported_count: number
  last_checked_count: number
  last_stop_reason: string | null
  last_stopped_gmail_message_id: string | null
  last_stopped_received_at: string | null
  last_reached_loaded_message: boolean
  unloaded_dates: string[]
  updated_at: string | null
}

export type GoogleCalendarAutoSyncSettings = {
  enabled: boolean
  interval_minutes: number
  calendar_ids: string[]
  month_count: number
  last_run_at: string | null
  last_success_at: string | null
  last_error: string | null
  last_imported_count: number
  last_updated_count: number
  last_cancelled_count: number
  last_missing_count: number
  last_time_min: string | null
  last_time_max: string | null
  last_stop_reason: string | null
  updated_at: string | null
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

export type GoogleGmailSpecialImportResult = {
  source_id: string
  imported_count: number
  candidate_count: number
  skipped_drafts: number
  items: Array<{
    subject: string | null
    from_address: string
    received_at: string
    mail: NonNullable<GoogleGmailImportResult['mail']>
  }>
}

export type GoogleCalendarEvent = {
  id: string | null
  google_event_id?: string | null
  calendar_source_id?: string | null
  summary: string
  description: string | null
  location: string | null
  html_link: string | null
  start: Record<string, unknown>
  end: Record<string, unknown>
  status: string | null
  created: string | null
  updated: string | null
  sync_status?: string | null
  recurring_event_id?: string | null
  academic_series_id?: string | null
  attendance_requirement?: string | null
  tags_json?: string | null
  metadata_json?: string | null
  local_note?: string | null
}

export type CalendarEventTitleFitPayload = {
  title: string
  font_size_px: number
  line_height: number
  line_clamp: number
  measured_width: number
  measured_height: number
}

export type CalendarEventUpdatePayload = {
  summary?: string | null
  calendar_id?: string | null
}

export type CalendarEventLink = {
  id: string
  calendar_event_id: string
  linked_type: string
  linked_id: string
  role: string
  title: string | null
  href: string | null
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
  version: number
}

export type CalendarEventDetail = {
  event: GoogleCalendarEvent
  links: CalendarEventLink[]
  mail_summaries?: CalendarEventMailSummary[]
}

export type CalendarEventMailSummary = {
  message_id: string
  thread_id: string
  subject: string | null
  from: string
  received_at: string
  summary: string
  next_action: string | null
  source: string
  href: string
}

export type GoogleCalendarListItem = {
  id: string
  summary: string
  description: string | null
  primary: boolean
  access_role: string
  background_color: string | null
  foreground_color: string | null
  time_zone: string | null
  can_write: boolean
}

export type GoogleCalendarEventCreatePayload = {
  summary: string
  start: string
  end: string
  calendar_id?: string
  description?: string | null
  location?: string | null
  recurrence_rule?: string | null
  time_zone?: string
  linked_mail_message_id?: string | null
  linked_case_id?: string | null
  academic_series_id?: string | null
}

export function toJstIsoDateTime(value: string): string {
  const trimmed = value.trim()
  if (/[zZ]|[+-]\d{2}:?\d{2}$/.test(trimmed)) {
    return trimmed.endsWith('Z') ? `${trimmed.slice(0, -1)}+00:00` : trimmed
  }
  const match = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?$/.exec(trimmed)
  if (match === null) return trimmed
  const [, date, hour, minute, second] = match
  return `${date}T${hour}:${minute}:${second ?? '00'}+09:00`
}

export type CalendarEventFromMailPrefill = {
  summary: string
  description: string | null
  location: string | null
  start_at: string
  end_at: string
  time_zone: string
  reasoning_summary: string | null
  warnings: string[]
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

export type MailDayStats = {
  date: string
  total_count: number
  received_count: number
  sent_count: number
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

export function getMailDayStats(date: string): Promise<MailDayStats> {
  const params = new URLSearchParams({ date })
  return request(`/api/v1/mails/day-stats?${params.toString()}`)
}

export function getMailDetail(messageId: string): Promise<MailDetail> {
  return request<MailDetail>(`/api/v1/mails/${encodeURIComponent(messageId)}`)
}

export async function listMailThreadCaseLinks(messageId: string): Promise<MailCaseLink[]> {
  const data = await request<ItemsResponse<MailCaseLink>>(
    `/api/v1/mails/${encodeURIComponent(messageId)}/case-links`,
  )
  return data.items
}

export function assignMailThreadToCase(
  messageId: string,
  caseId: string,
): Promise<MailDetail> {
  return request(`/api/v1/mails/${encodeURIComponent(messageId)}/case-links`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ case_id: caseId }),
  })
}

export function unassignMailThreadFromCase(
  messageId: string,
  caseId: string,
): Promise<MailDetail> {
  return request(
    `/api/v1/mails/${encodeURIComponent(messageId)}/case-links/${encodeURIComponent(caseId)}`,
    { method: 'DELETE' },
  )
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

export function getMailDraftGenerationStandardPrompt(): Promise<MailDraftGenerationStandardPrompt> {
  return request('/api/v1/mails/draft-generation-standard-prompt')
}

export function updateMailDraftGenerationStandardPrompt(
  standardPrompt: string,
  generationLanguage: 'japanese' | 'english',
): Promise<MailDraftGenerationStandardPrompt> {
  return request('/api/v1/mails/draft-generation-standard-prompt', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      standard_prompt: standardPrompt,
      generation_language: generationLanguage,
    }),
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

export function importSpecialGoogleGmailThread(
  source: string,
): Promise<GoogleGmailSpecialImportResult> {
  return request('/api/v1/google/gmail/import-special-thread', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source }),
  })
}

export function updateGoogleGmailAutoImportSettings(payload: {
  enabled: boolean
  interval_minutes: number
  max_messages_per_run: number
}): Promise<GoogleGmailAutoImportSettings> {
  return request('/api/v1/google/gmail/auto-import-settings', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function updateGoogleCalendarAutoSyncSettings(payload: {
  enabled: boolean
  interval_minutes: number
  calendar_ids?: string[]
  month_count?: number
}): Promise<GoogleCalendarAutoSyncSettings> {
  return request('/api/v1/google/gmail/calendar/auto-sync-settings', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function listGoogleCalendarEvents(params: {
  calendar_id?: string
  time_min?: string
  time_max?: string
  max_results?: number
} = {}): Promise<{ items: GoogleCalendarEvent[]; calendar_id: string }> {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value).trim() !== '') {
      query.set(key, String(value))
    }
  })
  return request(
    `/api/v1/google/gmail/calendar/events${query.size === 0 ? '' : `?${query}`}`,
  )
}

export function listCalendarDbEvents(params: {
  calendar_id?: string[]
  time_min?: string
  time_max?: string
} = {}): Promise<{ items: GoogleCalendarEvent[]; calendar_ids: string[] }> {
  const query = new URLSearchParams()
  params.calendar_id?.forEach((calendarId) => {
    if (calendarId.trim() !== '') {
      query.append('calendar_id', calendarId)
    }
  })
  if (params.time_min !== undefined && params.time_min.trim() !== '') {
    query.set('time_min', params.time_min)
  }
  if (params.time_max !== undefined && params.time_max.trim() !== '') {
    query.set('time_max', params.time_max)
  }
  return request(
    `/api/v1/google/gmail/calendar/db-events${query.size === 0 ? '' : `?${query}`}`,
  )
}

export function getCalendarDbEvent(eventId: string): Promise<CalendarEventDetail> {
  return request(`/api/v1/google/gmail/calendar/db-events/${encodeURIComponent(eventId)}`)
}

export function createCalendarDbEventLink(
  eventId: string,
  payload: { linked_type: string; linked_id: string; role?: string },
): Promise<{ link: CalendarEventLink }> {
  return request(`/api/v1/google/gmail/calendar/db-events/${encodeURIComponent(eventId)}/links`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function moveCalendarDbEvent(
  eventId: string,
  payload: { start: string; end: string; time_zone?: string },
): Promise<{ event: GoogleCalendarEvent; google_event: GoogleCalendarEvent | null }> {
  return request(`/api/v1/google/gmail/calendar/db-events/${encodeURIComponent(eventId)}/move`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function updateCalendarDbEvent(
  eventId: string,
  payload: CalendarEventUpdatePayload,
): Promise<{ event: GoogleCalendarEvent; google_event: GoogleCalendarEvent | null }> {
  return request(`/api/v1/google/gmail/calendar/db-events/${encodeURIComponent(eventId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function deleteCalendarDbEvent(
  eventId: string,
  scope: 'event' | 'series' = 'event',
): Promise<{ deleted: boolean; deleted_count: number; scope: string; event: GoogleCalendarEvent }> {
  const query = new URLSearchParams({ scope })
  return request(`/api/v1/google/gmail/calendar/db-events/${encodeURIComponent(eventId)}?${query}`, {
    method: 'DELETE',
  })
}

export function updateCalendarDbEventTitleFit(
  eventId: string,
  payload: CalendarEventTitleFitPayload,
): Promise<{ event: GoogleCalendarEvent }> {
  return request(`/api/v1/google/gmail/calendar/db-events/${encodeURIComponent(eventId)}/title-fit`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function deleteCalendarDbEventLink(
  eventId: string,
  linkId: string,
): Promise<{ deleted: boolean }> {
  return request(
    `/api/v1/google/gmail/calendar/db-events/${encodeURIComponent(eventId)}/links/${encodeURIComponent(linkId)}`,
    { method: 'DELETE' },
  )
}

export function syncGoogleCalendarEvents(payload: {
  calendar_ids: string[]
  base_date?: string | null
  month_count?: number
}): Promise<{
  calendar_ids: string[]
  time_min: string
  time_max: string
  imported_count: number
  updated_count: number
  cancelled_count: number
  missing_count: number
}> {
  return request('/api/v1/google/gmail/calendar/sync', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export async function listGoogleCalendars(): Promise<GoogleCalendarListItem[]> {
  const data = await request<ItemsResponse<GoogleCalendarListItem>>(
    '/api/v1/google/gmail/calendar/calendars',
  )
  return data.items
}

export function createGoogleCalendarEvent(
  payload: GoogleCalendarEventCreatePayload,
): Promise<{
  event: GoogleCalendarEvent
  db_event?: GoogleCalendarEvent
  links?: CalendarEventLink[]
}> {
  return request('/api/v1/google/gmail/calendar/events', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function prefillCalendarEventFromMail(payload: {
  message_id: string
  case_id?: string | null
  prompt?: string | null
}): Promise<{
  prefill: CalendarEventFromMailPrefill
  llm_run_id: string
  linked_mail_message_id: string
  linked_case_id: string | null
  linked_case_name: string | null
}> {
  return request('/api/v1/google/gmail/calendar/events/prefill-from-mail', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
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

export function allowMailLlm(messageId: string): Promise<MailDetail> {
  return request(`/api/v1/mails/${encodeURIComponent(messageId)}/allow-llm`, {
    method: 'POST',
  })
}

export function requestMailSummary(messageId: string): Promise<{ job_id: string }> {
  return request(`/api/v1/mails/${encodeURIComponent(messageId)}/summary`, {
    method: 'POST',
  })
}

export function moveMailAttachmentToStorage(
  attachmentId: string,
): Promise<MailAttachmentStorageMoveResult> {
  return request<MailAttachmentStorageMoveResult>(
    `/api/v1/mails/attachments/${encodeURIComponent(attachmentId)}/move-to-storage`,
    { method: 'POST' },
  )
}

export function enqueueMailAttachmentFetchJob(
  attachmentId: string,
): Promise<MailAttachmentFetchJobResult> {
  return request<MailAttachmentFetchJobResult>(
    `/api/v1/mails/attachments/${encodeURIComponent(attachmentId)}/fetch-job`,
    { method: 'POST' },
  )
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
