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

export type UserProfile = {
  display_name: string
  primary_email: string
  email_aliases: string[]
  affiliation: string
  academic_title: string
  lab_or_group: string
  research_fields: string
  teaching_responsibilities: string
  committee_roles: string
  administrative_roles: string
  supervised_people: string
  collaborators: string
  important_projects: string
  priority_keywords: string
  low_priority_keywords: string
  important_senders_or_domains: string
  expected_response_policy: string
  unavailable_times: string
  default_reply_language: 'japanese' | 'english'
  llm_self_description: string
  mail_importance_notes: string
  updated_at: string | null
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: 'include',
    ...init,
    headers: {
      ...(init?.headers ?? {}),
    },
  })
  const payload = (await response.json()) as SuccessResponse<T> | ErrorResponse
  if (!response.ok || !payload.ok) {
    const message = payload.ok ? response.statusText : payload.error.message
    throw new Error(message)
  }
  return payload.data
}

export function getProfile(): Promise<UserProfile> {
  return request('/api/v1/profile')
}

export function updateProfile(profile: UserProfile): Promise<UserProfile> {
  return request('/api/v1/profile', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(profile),
  })
}
