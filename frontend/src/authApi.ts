export type ApiError = {
  code: string
  message: string
}

export type SessionData = {
  authenticated: true
  session_expires_at: string
  client_certificate_id: string | null
  device_name: string | null
  ip_address: string | null
  access_mode: 'full' | 'low_mail_review'
}

export type LoginData = {
  session_expires_at: string
  device_name: string | null
  ip_address: string | null
  access_mode: 'full' | 'low_mail_review'
}

type SuccessResponse<T> = {
  ok: true
  data: T
}

type ErrorResponse = {
  ok: false
  error: ApiError
}

export class AuthApiError extends Error {
  code: string
  status: number

  constructor(status: number, error: ApiError) {
    super(error.message)
    this.name = 'AuthApiError'
    this.code = error.code
    this.status = status
  }
}

async function request<T>(
  path: string,
  init?: RequestInit,
): Promise<SuccessResponse<T>> {
  const response = await fetch(path, {
    credentials: 'include',
    ...init,
  })
  const payload = (await response.json()) as SuccessResponse<T> | ErrorResponse

  if (!response.ok || !payload.ok) {
    const error =
      !payload.ok
        ? payload.error
        : { code: 'AUTH_REQUEST_FAILED', message: 'Authentication failed.' }
    throw new AuthApiError(response.status, error)
  }

  return payload
}

export async function readSession(): Promise<SessionData> {
  const response = await request<SessionData>('/api/v1/auth/session')
  return response.data
}

export async function logout(): Promise<void> {
  await request<Record<string, never>>('/api/v1/auth/logout', { method: 'POST' })
}

export async function login(password: string): Promise<LoginData> {
  const response = await request<LoginData>('/api/v1/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password }),
  })
  return response.data
}

export async function resetPasswordByEmail(): Promise<void> {
  await request<{
    email_sent: true
    invalidated_sessions: number
    retry_after_seconds: number
  }>('/api/v1/auth/password-reset', { method: 'POST' })
}
