export type LogTypeCount = {
  type: string
  count: number
}

export type LogEntry = {
  id: string
  source_type: string
  occurred_at: string
  level: string
  category: string
  summary: string
  detail: string | null
  status: string | null
  target_type: string | null
  target_id: string | null
  metadata: unknown
}

export type LogPage = {
  items: LogEntry[]
  page: number
  page_size: number
  total: number
  total_pages: number
  types: LogTypeCount[]
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

export type LogFilters = {
  page?: number
  types?: string[]
  query?: string
  dateFrom?: string
  dateTo?: string
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

export class LogsApiError extends Error {
  code: string
  status: number

  constructor(status: number, error: ApiError) {
    super(error.message)
    this.name = 'LogsApiError'
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
      : { code: 'LOGS_REQUEST_FAILED', message: 'Request failed.' }
    throw new LogsApiError(response.status, error)
  }

  return payload.data
}

export function buildLogParams(filters: LogFilters) {
  const params = new URLSearchParams()
  if (filters.page !== undefined && filters.page > 1) {
    params.set('page', String(filters.page))
  }
  if (filters.types !== undefined && filters.types.length > 0) {
    params.set('types', filters.types.join(','))
  }
  if (filters.query !== undefined && filters.query.trim() !== '') {
    params.set('q', filters.query.trim())
  }
  if (filters.dateFrom !== undefined && filters.dateFrom !== '') {
    params.set('date_from', filters.dateFrom)
  }
  if (filters.dateTo !== undefined && filters.dateTo !== '') {
    params.set('date_to', filters.dateTo)
  }
  return params
}

export function listLogs(filters: LogFilters = {}): Promise<LogPage> {
  const params = buildLogParams(filters)
  const query = params.toString()
  return request<LogPage>(`/api/v1/logs${query === '' ? '' : `?${query}`}`)
}

export function logsExportUrl(filters: LogFilters = {}) {
  const params = buildLogParams(filters)
  params.delete('page')
  const query = params.toString()
  return `/api/v1/logs/export${query === '' ? '' : `?${query}`}`
}
