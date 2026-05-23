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
}

export type MailDetail = {
  message: MailListItem & {
    thread_id: string
    from_name: string | null
    sender_address: string | null
    to_addresses: string[]
    cc_addresses: string[]
    bcc_addresses: string[]
    message_id_header: string | null
    in_reply_to_header: string | null
    references_header: string | null
    snippet: string | null
    gmail_link: string | null
    external_starred: boolean
    body_text?: string | null
    body_html?: string | null
    created_at: string
    updated_at: string
    version: number
  }
  thread_messages: MailListItem[]
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
  }
  available_actions: string[]
}

export type MockMailPayload = {
  gmail_message_id: string
  gmail_thread_id: string
  message_id_header: string
  subject: string
  from_address: string
  received_at: string
  body_text: string
}

export type MailListFilters = {
  tab?: 'all' | 'pending' | 'unprocessed' | 'processed' | 'skip'
  processed?: 'all' | 'processed' | 'unprocessed' | '0' | '1'
  importance?: 'all' | 'pinned' | 'high' | 'middle' | 'low' | 'skip' | 'pending' | 'unclassified'
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
  const payload = (await response.json()) as unknown

  if (!response.ok || !isSuccessResponse<T>(payload)) {
    const error = hasApiError(payload)
      ? payload.error
      : { code: 'PHASE_4_REQUEST_FAILED', message: 'Request failed.' }
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

export function getMailDetail(messageId: string): Promise<MailDetail> {
  return request<MailDetail>(`/api/v1/mails/${encodeURIComponent(messageId)}`)
}

export function ingestMockMail(
  payload: MockMailPayload,
): Promise<{
  message_id: string
  pending: boolean
  pending_address: string | null
  queued_job_id: string | null
}> {
  return request('/api/v1/mails/mock-ingest', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function runNextJob(): Promise<{ job_id: string | null }> {
  return request('/api/v1/jobs/run-next', { method: 'POST' })
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
