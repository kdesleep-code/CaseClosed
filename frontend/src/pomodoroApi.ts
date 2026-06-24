export type PomodoroPhase = 'work' | 'break' | 'done'

export type PomodoroState = {
  work_minutes: number
  break_minutes: number
  cycle_count: number
  phase: PomodoroPhase
  current_cycle: number
  is_running: boolean
  remaining_seconds: number
  total_seconds: number
  phase_ends_at_epoch_ms: number | null
  updated_at_epoch_ms: number
  version: number
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

class PomodoroApiError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'PomodoroApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: 'include',
    ...init,
  })
  const payload = (await response.json()) as unknown
  if (!response.ok || !isSuccessResponse<T>(payload)) {
    throw new PomodoroApiError(
      isErrorResponse(payload) ? payload.error.message : 'Pomodoro request failed.',
    )
  }
  return payload.data
}

export async function readPomodoroState(): Promise<PomodoroState> {
  const data = await request<{ state: PomodoroState }>('/api/v1/pomodoro')
  return data.state
}

export async function updatePomodoroSettings(payload: {
  work_minutes: number
  break_minutes: number
  cycle_count: number
}): Promise<PomodoroState> {
  const data = await request<{ state: PomodoroState }>('/api/v1/pomodoro/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return data.state
}

export async function startPomodoro(): Promise<PomodoroState> {
  const data = await request<{ state: PomodoroState }>('/api/v1/pomodoro/start', { method: 'POST' })
  return data.state
}

export async function pausePomodoro(): Promise<PomodoroState> {
  const data = await request<{ state: PomodoroState }>('/api/v1/pomodoro/pause', { method: 'POST' })
  return data.state
}

export async function resetPomodoro(): Promise<PomodoroState> {
  const data = await request<{ state: PomodoroState }>('/api/v1/pomodoro/reset', { method: 'POST' })
  return data.state
}

export async function skipPomodoro(): Promise<PomodoroState> {
  const data = await request<{ state: PomodoroState }>('/api/v1/pomodoro/skip', { method: 'POST' })
  return data.state
}
