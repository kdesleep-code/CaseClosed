export type MaintenanceStatus = {
  job_accepting: boolean
  running_jobs: number
  action_required_jobs?: number
  pending_write_requests: number
  external_unknown_count: number
  llm_cost_month_used?: number
  llm_cost_month_remaining?: number | null
  llm_cost_month_projected?: number
  storage_active_bytes?: number
  storage_active_objects?: number
  mail_total?: number
  mail_received_7d?: number
  mail_sent_7d?: number
  mail_daily_average_30d?: number
  mail_importance_high?: number
  mail_importance_middle?: number
  mail_importance_low?: number
  mail_importance_sent?: number
  mail_importance_unclassified?: number
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
  related_mail: JobRelatedMail | null
}

export type JobRelatedMail = {
  context_type: string
  message_id: string | null
  thread_id: string | null
  gmail_message_id: string | null
  gmail_thread_id: string | null
  subject: string | null
  received_at: string | null
  from_address: string | null
  mail_url: string | null
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

export type PendingMail = {
  id: string
  received_at: string
  subject: string | null
  from_address: string
  pending_reason: string | null
}

export type PendingMailRefreshResult = {
  changed: boolean
  reason: string
  queued_job_id: string | null
  mail: PendingMail
}

export type LlmCostHistory = {
  currency: string
  source: string
  monthly_budget: number | null
  month_used: number
  month_remaining: number | null
  today_used: number
  total_used: number
  by_function: Array<{
    function_type: string
    run_count: number
    prompt_tokens: number
    completion_tokens: number
    total_tokens: number
    estimated_cost: number
  }>
  daily: Array<{
    date: string
    run_count: number
    estimated_cost: number
  }>
  recent_runs: Array<{
    id: string
    function_type: string
    provider_name: string
    model_name: string
    status: string
    prompt_tokens: number | null
    completion_tokens: number | null
    total_tokens: number | null
    estimated_cost: number | null
    created_at: string
    finished_at: string | null
  }>
}

export type StorageOperationHistoryItem = {
  id: string
  storage_object_id: string | null
  operation_type: string
  actor: string
  scope: string | null
  original_filename: string | null
  content_type: string | null
  byte_size: number | null
  storage_path: string | null
  source_type: string | null
  source_message_id: string | null
  directory_id: string | null
  details: Record<string, unknown> | null
  created_at: string
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

export function readLlmCostHistory(): Promise<LlmCostHistory> {
  return request<LlmCostHistory>('/api/v1/maintenance/llm-cost-history')
}

export function updateLlmCostSettings(
  monthlyBudget: number | null,
): Promise<LlmCostHistory> {
  return request<LlmCostHistory>('/api/v1/maintenance/llm-cost-settings', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ monthly_budget: monthlyBudget }),
  })
}

export async function listStorageOperationHistory(): Promise<StorageOperationHistoryItem[]> {
  const data = await request<ListResponse<StorageOperationHistoryItem>>(
    '/api/v1/maintenance/storage-operation-history',
  )
  return data.items
}

export async function listJobs(): Promise<Job[]> {
  const data = await request<ListResponse<Job>>('/api/v1/jobs')
  return data.items
}

export function retryJob(jobId: string): Promise<Job> {
  return request<Job>(`/api/v1/jobs/${jobId}/retry`, { method: 'POST' })
}

export function discardJob(jobId: string): Promise<Job> {
  return request<Job>(`/api/v1/jobs/${jobId}/discard`, { method: 'POST' })
}

export async function listExternalOperations(): Promise<ExternalOperation[]> {
  const data = await request<ListResponse<ExternalOperation>>(
    '/api/v1/external-operations',
  )
  return data.items
}

export async function listPendingMails(): Promise<PendingMail[]> {
  const data = await request<ListResponse<PendingMail>>(
    '/api/v1/mails?tab=pending&limit=50',
  )
  return data.items
}

export function refreshPendingMail(
  messageId: string,
): Promise<PendingMailRefreshResult> {
  return request<PendingMailRefreshResult>(
    `/api/v1/mails/${messageId}/refresh-pending`,
    { method: 'POST' },
  )
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
