export type ExternalToolLink = {
  id: string
  title: string
  url: string
  tags: string[]
  note: string | null
  icon_label: string
  icon_setting_id: string | null
  icon_url: string | null
  sort_order: number
  created_at: string
  updated_at: string
  version: number
}

export type ExternalToolList = {
  items: ExternalToolLink[]
  tag_order: string[]
}

type SuccessResponse<T> = {
  ok: true
  data: T
}

type ErrorResponse = {
  ok: false
  error: { code: string; message: string }
}

function isSuccessResponse<T>(payload: unknown): payload is SuccessResponse<T> {
  return typeof payload === 'object' && payload !== null && (payload as SuccessResponse<T>).ok === true
}

function isErrorResponse(payload: unknown): payload is ErrorResponse {
  return typeof payload === 'object' && payload !== null && (payload as ErrorResponse).ok === false
}

class ExternalToolsApiError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ExternalToolsApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: 'include',
    ...init,
  })
  const payload = (await response.json()) as unknown
  if (!response.ok || !isSuccessResponse<T>(payload)) {
    throw new ExternalToolsApiError(
      isErrorResponse(payload) ? payload.error.message : 'External tools request failed.',
    )
  }
  return payload.data
}

export function listExternalTools(): Promise<ExternalToolList> {
  return request('/api/v1/external-tools')
}

export function createExternalTool(payload: {
  title: string
  url: string
  tags: string[]
  note: string | null
}): Promise<ExternalToolLink> {
  return request<{ tool: ExternalToolLink }>('/api/v1/external-tools', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then((data) => data.tool)
}

export function updateExternalTool(
  toolId: string,
  payload: {
    title?: string
    url?: string
    tags?: string[]
    note?: string | null
  },
): Promise<ExternalToolLink> {
  return request<{ tool: ExternalToolLink }>(`/api/v1/external-tools/${encodeURIComponent(toolId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then((data) => data.tool)
}

export function reorderExternalTools(payload: {
  tag_order?: string[]
  tool_ids?: string[]
}): Promise<ExternalToolList> {
  return request('/api/v1/external-tools/reorder', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function deleteExternalTool(toolId: string): Promise<{ deleted: boolean }> {
  return request(`/api/v1/external-tools/${encodeURIComponent(toolId)}`, {
    method: 'DELETE',
  })
}
