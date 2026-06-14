export type TaskItem = {
  id: string
  case_id: string
  case_name: string | null
  case_open_when_date: string | null
  case_archived_at: string | null
  storage_directory_id: string | null
  parent_task_id: string | null
  title: string
  description: string | null
  done_when_text: string | null
  progress_memo: string | null
  status: string
  priority: string
  start_at: string | null
  due_at: string | null
  estimate_minutes: number | null
  recurrence_rule_type: string | null
  recurrence_month_day: number | null
  recurrence_year_month: number | null
  recurrence_month_week: number | null
  recurrence_month_weekday: number | null
  recurrence_weekdays: number[]
  recurrence_start_offset_days: number | null
  recurrence_series_id: string | null
  recurrence_sequence: number
  scheduled_minutes: number
  worked_minutes: number
  source_type: string | null
  source_id: string | null
  completed_at: string | null
  canceled_at: string | null
  canceled_reason: string | null
  deleted_at: string | null
  deleted_reason: string | null
  created_at: string
  updated_at: string
  version: number
  links?: TaskLink[]
  progress_entries?: TaskProgressEntry[]
  subtasks?: TaskItem[]
}

export type TaskLink = {
  id: string
  task_id: string
  linked_type: string
  linked_id: string | null
  url: string | null
  label: string | null
  created_at: string
}

export type TaskProgressEntry = {
  id: string
  task_id: string
  body: string
  created_at: string
}

export type TaskCreatePayload = {
  case_id: string
  parent_task_id?: string | null
  title: string
  description?: string | null
  done_when_text?: string | null
  progress_memo?: string | null
  priority?: string
  start_at?: string | null
  due_at?: string | null
  estimate_minutes?: number | null
  recurrence_rule_type?: string | null
  recurrence_month_day?: number | null
  recurrence_year_month?: number | null
  recurrence_month_week?: number | null
  recurrence_month_weekday?: number | null
  recurrence_weekdays?: number[] | null
  recurrence_start_offset_days?: number | null
  source_type?: string
  source_id?: string | null
}

export type TaskUpdatePayload = {
  base_version?: number
  case_id?: string | null
  parent_task_id?: string | null
  title?: string
  description?: string | null
  done_when_text?: string | null
  progress_memo?: string | null
  status?: string
  priority?: string
  start_at?: string | null
  due_at?: string | null
  estimate_minutes?: number | null
  recurrence_rule_type?: string | null
  recurrence_month_day?: number | null
  recurrence_year_month?: number | null
  recurrence_month_week?: number | null
  recurrence_month_weekday?: number | null
  recurrence_weekdays?: number[] | null
  recurrence_start_offset_days?: number | null
  scheduled_minutes?: number
  worked_minutes?: number
}

export type TaskPrefill = {
  title: string | null
  description: string | null
  done_when_text: string | null
  priority: string
  due_at: string | null
  estimate_minutes: number | null
  reasoning_summary: string | null
  warnings: string[]
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

export class Phase8ApiError extends Error {
  code: string
  status: number

  constructor(status: number, error: ApiError) {
    super(error.message)
    this.name = 'Phase8ApiError'
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
      : { code: 'PHASE_8_REQUEST_FAILED', message: 'Request failed.' }
    throw new Phase8ApiError(response.status, error)
  }

  return payload.data
}

export async function listTasks(params: {
  case_id?: string | null
  status?: string
  due?: string
  include_deleted?: boolean
  limit?: number
} = {}): Promise<TaskItem[]> {
  const searchParams = new URLSearchParams()
  if (params.case_id !== undefined && params.case_id !== null) {
    searchParams.set('case_id', params.case_id)
  }
  if (params.status !== undefined) searchParams.set('status', params.status)
  if (params.due !== undefined) searchParams.set('due', params.due)
  if (params.include_deleted !== undefined) {
    searchParams.set('include_deleted', params.include_deleted ? 'true' : 'false')
  }
  if (params.limit !== undefined) searchParams.set('limit', String(params.limit))

  const query = searchParams.toString()
  const data = await request<ListResponse<TaskItem>>(`/api/v1/tasks${query === '' ? '' : `?${query}`}`)
  return data.items
}

export async function createTask(payload: TaskCreatePayload): Promise<TaskItem> {
  const data = await request<{ task: TaskItem }>('/api/v1/tasks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return data.task
}

export async function prefillTask(payload: {
  prompt: string
  case_id?: string | null
  current_fields?: Record<string, unknown>
}): Promise<{ prefill: TaskPrefill; llm_run_id: string }> {
  return request<{ prefill: TaskPrefill; llm_run_id: string }>('/api/v1/tasks/prefill', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export async function prefillTasksFromHandover(payload: {
  case_id: string
  storage_object_ids: string[]
  additional_prompt?: string | null
}): Promise<{ suggestions: TaskPrefill[]; llm_run_id: string }> {
  return request<{ suggestions: TaskPrefill[]; llm_run_id: string }>(
    '/api/v1/tasks/handover-prefill',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export async function createTaskFromMail(payload: {
  message_id: string
  case_id?: string | null
  prompt?: string | null
}): Promise<{ task: TaskItem; prefill: TaskPrefill; llm_run_id: string }> {
  return request<{ task: TaskItem; prefill: TaskPrefill; llm_run_id: string }>(
    '/api/v1/tasks/from-mail',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export async function getTask(taskId: string): Promise<TaskItem> {
  const data = await request<{ task: TaskItem }>(
    `/api/v1/tasks/${encodeURIComponent(taskId)}`,
  )
  return data.task
}

export async function updateTask(
  taskId: string,
  payload: TaskUpdatePayload,
): Promise<TaskItem> {
  const data = await request<{ task: TaskItem }>(
    `/api/v1/tasks/${encodeURIComponent(taskId)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  return data.task
}

export async function createTaskProgressEntry(
  taskId: string,
  body: string,
): Promise<{ entry: TaskProgressEntry; task: TaskItem }> {
  return request<{ entry: TaskProgressEntry; task: TaskItem }>(
    `/api/v1/tasks/${encodeURIComponent(taskId)}/progress-entries`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ body }),
    },
  )
}

export async function updateTaskProgressEntry(
  taskId: string,
  entryId: string,
  body: string,
): Promise<{ entry: TaskProgressEntry; task: TaskItem }> {
  return request<{ entry: TaskProgressEntry; task: TaskItem }>(
    `/api/v1/tasks/${encodeURIComponent(taskId)}/progress-entries/${encodeURIComponent(entryId)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ body }),
    },
  )
}

export async function deleteTaskProgressEntry(
  taskId: string,
  entryId: string,
): Promise<{ deleted: boolean; task: TaskItem }> {
  return request<{ deleted: boolean; task: TaskItem }>(
    `/api/v1/tasks/${encodeURIComponent(taskId)}/progress-entries/${encodeURIComponent(entryId)}`,
    {
      method: 'DELETE',
    },
  )
}

export async function completeTask(taskId: string): Promise<TaskItem> {
  const data = await request<{ task: TaskItem }>(
    `/api/v1/tasks/${encodeURIComponent(taskId)}/complete`,
    {
      method: 'POST',
    },
  )
  return data.task
}

export async function deleteTask(
  taskId: string,
  reason: string | null = null,
): Promise<{ deleted: boolean; task: TaskItem }> {
  return request<{ deleted: boolean; task: TaskItem }>(
    `/api/v1/tasks/${encodeURIComponent(taskId)}/delete`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason }),
    },
  )
}
