export type MaintenanceStatus = {
  job_accepting: boolean
  running_jobs: number
  pending_write_requests: number
  external_unknown_count: number
  backup_status: string
}

export type Job = {
  id: string
  job_type: string
  priority: number
  status: string
  error_type: string | null
  error_message: string | null
  retry_count: number
  max_retries: number
  created_at: string
  updated_at: string
}

export type ExternalOperation = {
  id: string
  operation_type: string
  status: string
  external_service: string
  external_id: string | null
  unknown_reason: string | null
  manual_resolution_required: boolean
  created_at: string
  updated_at: string
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
  if (typeof payload !== 'object' || payload === null) {
    return false
  }

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

export class Phase2ApiError extends Error {
  code: string
  status: number

  constructor(status: number, error: ApiError) {
    super(error.message)
    this.name = 'Phase2ApiError'
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
      : { code: 'PHASE_2_REQUEST_FAILED', message: 'Request failed.' }
    throw new Phase2ApiError(response.status, error)
  }

  return payload.data
}

export function readMaintenanceStatus(): Promise<MaintenanceStatus> {
  return request<MaintenanceStatus>('/api/v1/maintenance/status')
}

export async function listJobs(): Promise<Job[]> {
  const data = await request<ListResponse<Job>>('/api/v1/jobs')
  return data.items
}

export function retryJob(jobId: string): Promise<Job> {
  return request<Job>(`/api/v1/jobs/${jobId}/retry`, { method: 'POST' })
}

export async function listExternalOperations(): Promise<ExternalOperation[]> {
  const data = await request<ListResponse<ExternalOperation>>(
    '/api/v1/external-operations',
  )
  return data.items
}

export function resolveExternalOperation(
  operationId: string,
  resolution: 'mark_succeeded' | 'mark_failed' | 'mark_canceled',
): Promise<ExternalOperation> {
  return request<ExternalOperation>(
    `/api/v1/external-operations/${operationId}/resolve`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ resolution }),
    },
  )
}
