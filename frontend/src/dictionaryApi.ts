export type DictionaryEntry = {
  id: string
  headword: string
  aliases: string[]
  interpretation: string
  examples: string | null
  source_urls: string[]
  related_entry_ids: string[]
  created_at: string
  updated_at: string
  version: number
}

export type DictionaryEntryInput = {
  headword: string
  aliases: string[]
  interpretation: string
  examples: string | null
  source_urls: string[]
  related_entry_ids: string[]
}

type SuccessResponse<T> = { ok: true; data: T }
type ErrorResponse = { ok: false; error: { code: string; message: string } }

export class DictionaryApiError extends Error {
  code: string

  constructor(code: string, message: string) {
    super(message)
    this.name = 'DictionaryApiError'
    this.code = code
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: 'include',
    ...init,
    headers: {
      ...(init?.body === undefined ? {} : { 'Content-Type': 'application/json' }),
      ...init?.headers,
    },
  })
  const payload = (await response.json()) as SuccessResponse<T> | ErrorResponse
  if (!response.ok || payload.ok === false) {
    const error = payload.ok === false
      ? payload.error
      : { code: 'HTTP_ERROR', message: `Request failed with status ${response.status}.` }
    throw new DictionaryApiError(error.code, error.message)
  }
  return payload.data
}

export async function listDictionaryEntries(): Promise<DictionaryEntry[]> {
  const data = await request<{ items: DictionaryEntry[] }>('/api/v1/dictionary')
  return data.items
}

export function createDictionaryEntry(input: DictionaryEntryInput): Promise<DictionaryEntry> {
  return request<DictionaryEntry>('/api/v1/dictionary', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function updateDictionaryEntry(
  entryId: string,
  input: DictionaryEntryInput,
): Promise<DictionaryEntry> {
  return request<DictionaryEntry>(`/api/v1/dictionary/${encodeURIComponent(entryId)}`, {
    method: 'PUT',
    body: JSON.stringify(input),
  })
}

export function deleteDictionaryEntry(entryId: string): Promise<{ id: string }> {
  return request<{ id: string }>(`/api/v1/dictionary/${encodeURIComponent(entryId)}`, {
    method: 'DELETE',
  })
}
