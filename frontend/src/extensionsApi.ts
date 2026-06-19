export type ExtensionDefinition = {
  id: string
  slug: string
  name: string
  description: string | null
  root_path: string
  command: string[]
  url_path: string | null
  tags: string[]
  status: string
  source: 'default' | 'user' | string
  created_at: string
  updated_at: string
  version: number
}

export type ExtensionInstance = {
  id: string
  extension_id: string
  case_id: string | null
  status: string
  host: string
  port: number
  base_url: string
  process_id: number | null
  launch_context: {
    case_id: string | null
    context: Record<string, unknown>
  }
  started_at: string
  last_seen_at: string
  idle_timeout_seconds: number
  stopped_at: string | null
  error_message: string | null
  created_at: string
  updated_at: string
  version: number
}

export type ExtensionList = {
  items: ExtensionDefinition[]
  running_instances: ExtensionInstance[]
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

class ExtensionsApiError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ExtensionsApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: 'include',
    ...init,
  })
  const payload = (await response.json()) as unknown
  if (!response.ok || !isSuccessResponse<T>(payload)) {
    throw new ExtensionsApiError(
      isErrorResponse(payload) ? payload.error.message : 'Extensions request failed.',
    )
  }
  return payload.data
}

export function listExtensions(): Promise<ExtensionList> {
  return request('/api/v1/extensions')
}

export function registerExtension(payload: {
  manifest_path?: string | null
  root_path?: string | null
  manifest?: Record<string, unknown> | null
}): Promise<ExtensionDefinition> {
  return request<{ extension: ExtensionDefinition }>('/api/v1/extensions/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then((data) => data.extension)
}

export function startExtension(
  extensionId: string,
  payload: {
    case_id?: string | null
    context?: Record<string, unknown> | null
    idle_timeout_seconds?: number
  },
): Promise<{ instance: ExtensionInstance; open_url: string }> {
  return request<{ instance: ExtensionInstance; open_url: string; extension_token: string }>(
    `/api/v1/extensions/${encodeURIComponent(extensionId)}/start`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  ).then((data) => ({ instance: data.instance, open_url: data.open_url }))
}

export function stopExtensionInstance(instanceId: string): Promise<ExtensionInstance> {
  return request<{ instance: ExtensionInstance }>(
    `/api/v1/extensions/instances/${encodeURIComponent(instanceId)}/stop`,
    {
      method: 'POST',
    },
  ).then((data) => data.instance)
}
