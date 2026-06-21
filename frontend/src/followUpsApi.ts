export type FollowUpStatus = 'active' | 'resolved' | 'dismissed'

export type FollowUpMessage = {
  id: string
  subject: string | null
  from_address: string
  from_name: string | null
  received_at: string
  snippet: string | null
}

export type FollowUp = {
  id: string
  source_message_id: string
  thread_id: string
  case_id: string | null
  case_name: string | null
  status: FollowUpStatus
  due_on: string
  reason: string
  matched_phrase: string
  source: string
  resolved_by_message_id: string | null
  resolved_by_subject: string | null
  resolved_at: string | null
  dismissed_at: string | null
  dismissed_reason: string | null
  created_at: string
  updated_at: string
  version: number
  message: FollowUpMessage | null
}

type ListResponse<T> = {
  items: T[]
}

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

function hasApiError(payload: unknown): payload is ErrorResponse {
  if (typeof payload !== 'object' || payload === null) return false
  const candidate = payload as Partial<ErrorResponse>
  return (
    candidate.ok === false &&
    typeof candidate.error?.code === 'string' &&
    typeof candidate.error.message === 'string'
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

export class FollowUpsApiError extends Error {
  code: string
  status: number

  constructor(status: number, error: ApiError) {
    super(error.message)
    this.name = 'FollowUpsApiError'
    this.code = error.code
    this.status = status
  }
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
      : { code: 'FOLLOW_UP_REQUEST_FAILED', message: 'Follow-up request failed.' }
    throw new FollowUpsApiError(response.status, error)
  }

  return payload.data
}

export async function listFollowUps(
  params: {
    status?: FollowUpStatus | 'all'
    due_on_or_before?: string
    case_id?: string
  } = {},
): Promise<FollowUp[]> {
  const searchParams = new URLSearchParams()
  if (params.status !== undefined) searchParams.set('status', params.status)
  if (params.due_on_or_before !== undefined) {
    searchParams.set('due_on_or_before', params.due_on_or_before)
  }
  if (params.case_id !== undefined) searchParams.set('case_id', params.case_id)
  const query = searchParams.toString()
  const response = await request<ListResponse<FollowUp>>(
    `/api/v1/follow-ups${query === '' ? '' : `?${query}`}`,
  )
  return response.items
}

export async function dismissFollowUp(id: string, reason: string | null = null) {
  return request<FollowUp>(`/api/v1/follow-ups/${encodeURIComponent(id)}/dismiss`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason }),
  })
}

export async function resolveFollowUp(id: string) {
  return request<FollowUp>(`/api/v1/follow-ups/${encodeURIComponent(id)}/resolve`, {
    method: 'POST',
  })
}

export async function snoozeFollowUp(id: string, dueOn: string) {
  return request<FollowUp>(`/api/v1/follow-ups/${encodeURIComponent(id)}/snooze`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ due_on: dueOn }),
  })
}
