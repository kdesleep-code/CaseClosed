import type { StorageObject } from './phase3Api'

export type CaseItem = {
  id: string
  genre_id: string | null
  name: string
  description: string | null
  open_when_date: string | null
  open_when_text: string | null
  closed_when_text: string | null
  progress_status: string
  ball_status: string
  closed_at: string | null
  archived_at: string | null
  is_system_case: boolean
  system_case_key: string | null
  tags: string[]
  mail_count: number
  open_task_count: number
  overdue_task_count: number
  file_count: number
  storage_directory_id: string
  next_task: CaseTaskSummary | null
  next_calendar_event: {
    id: string
    title: string
    starts_at: string | null
    ends_at: string | null
    all_day: boolean
    location: string | null
  } | null
  created_at: string
  updated_at: string
  version: number
}

export type CaseTaskSummary = {
  id: string
  case_id: string
  title: string
  description: string | null
  done_when_text: string | null
  status: string
  priority: string
  due_at: string | null
  estimate_minutes: number | null
  created_at: string
  updated_at: string
}

export type CaseCalendarSummary = {
  id: string
  title: string
  starts_at: string | null
  ends_at: string | null
  all_day: boolean
  location: string | null
}

export type CaseGenre = {
  id: string
  title: string
  color_hex: string
  sort_order: number
  created_at: string
  updated_at: string
  version: number
}

export type CaseEventItem = {
  id: string
  case_id: string
  event_type: string
  title: string
  summary: string | null
  source_type: string | null
  source_id: string | null
  occurred_at: string
  created_at: string
  metadata: Record<string, unknown>
}

export type CaseStakeholder = {
  id: string
  case_id: string
  contact_id: string
  contact_display_name: string
  contact_avatar_url: string | null
  contact_primary_email: string | null
  role: 'owner' | 'collaborator' | 'reviewer' | 'stakeholder' | string
  sort_order: number
  created_at: string
  updated_at: string
  version: number
}

export type CaseToolLink = {
  id: string
  case_id: string
  url: string
  icon_label: string
  icon_setting_id: string | null
  icon_url: string | null
  sort_order: number
  created_at: string
  updated_at: string
  version: number
}

export type CaseToolIconSetting = {
  id: string
  storage_object_id: string | null
  icon_filename: string | null
  icon_content_type: string
  icon_url: string | null
  icon_data_url: string | null
  match_url: string
  created_at: string
  updated_at: string
  version: number
}

export type CaseMailLink = {
  id: string
  case_id: string
  message_id: string
  gmail_message_id: string
  thread_id: string
  received_at: string
  subject: string | null
  from_address: string
  from_name: string | null
  processed_status: string
  read_status: string
  effective_importance: string
  summary: string | null
  mail_url: string
  created_at: string
  updated_at: string
  version: number
}

export type CaseAutoAssignRule = {
  id: string
  case_id: string
  rule_type: string
  rule_value: string
  label: string | null
  is_enabled: boolean
  created_at: string
  updated_at: string
  version: number
}

export type CaseCurrentSituation = {
  id: string
  case_id: string
  version_no: number
  context_markdown: string
  source_event_until_at: string | null
  llm_run_id: string | null
  created_at: string
  created_by: string
}

export type CasePrefill = {
  name: string | null
  description: string | null
  open_when_date: string | null
  closed_when_text: string | null
  tags: string[]
  reasoning_summary: string | null
  warnings: string[]
}

export type CaseDetail = {
  case: CaseItem
  related_mails: CaseMailLink[]
  tasks: CaseTaskSummary[]
  calendar_events: CaseCalendarSummary[]
  contacts: unknown[]
  files: unknown[]
  stakeholders?: CaseStakeholder[]
  tool_links?: CaseToolLink[]
  current_situation?: CaseCurrentSituation | null
  recent_events: CaseEventItem[]
}

export type CaseListStatus = 'user_ball' | 'waiting' | 'not_started' | 'completed' | 'archived'

export function isCaseOpenForSuggestion(item: CaseItem, today = new Date()): boolean {
  if (item.archived_at !== null || item.closed_at !== null) return false
  if (item.open_when_date === null || item.open_when_date.trim() === '') return true
  const localToday = new Date(today.getTime() - today.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 10)
  return item.open_when_date <= localToday
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

export class Phase7ApiError extends Error {
  code: string
  status: number

  constructor(status: number, error: ApiError) {
    super(error.message)
    this.name = 'Phase7ApiError'
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
      : { code: 'PHASE_7_REQUEST_FAILED', message: 'Request failed.' }
    throw new Phase7ApiError(response.status, error)
  }

  return payload.data
}

export async function listCases(status: CaseListStatus | 'all' = 'user_ball'): Promise<CaseItem[]> {
  const params = new URLSearchParams({ status })
  const data = await request<ListResponse<CaseItem>>(`/api/v1/cases?${params.toString()}`)
  return data.items
}

export async function listCaseGenres(): Promise<CaseGenre[]> {
  const data = await request<ListResponse<CaseGenre>>('/api/v1/cases/genres')
  return data.items
}

export function prefillCase(payload: {
  prompt: string
  current_fields?: Record<string, unknown>
}): Promise<{ prefill: CasePrefill; llm_run_id: string }> {
  return request<{ prefill: CasePrefill; llm_run_id: string }>('/api/v1/cases/prefill', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export async function createCaseGenre(payload: {
  title: string
  color_hex: string
}): Promise<CaseGenre> {
  const data = await request<{ genre: CaseGenre }>('/api/v1/cases/genres', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return data.genre
}

export async function updateCaseGenre(
  genreId: string,
  payload: { title?: string; color_hex?: string },
): Promise<CaseGenre> {
  const data = await request<{ genre: CaseGenre }>(
    `/api/v1/cases/genres/${encodeURIComponent(genreId)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  return data.genre
}

export function deleteCaseGenre(genreId: string): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(`/api/v1/cases/genres/${encodeURIComponent(genreId)}`, {
    method: 'DELETE',
  })
}

export async function reorderCaseGenres(genreIds: string[]): Promise<CaseGenre[]> {
  const data = await request<ListResponse<CaseGenre>>('/api/v1/cases/genres/reorder', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ genre_ids: genreIds }),
  })
  return data.items
}

export async function listCaseMailLinks(caseId: string): Promise<CaseMailLink[]> {
  const data = await request<ListResponse<CaseMailLink>>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/mail-links`,
  )
  return data.items
}

export async function listCaseFiles(caseId: string): Promise<StorageObject[]> {
  const data = await request<ListResponse<StorageObject>>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/files`,
  )
  return data.items
}

export async function linkCaseFile(
  caseId: string,
  storageObjectId: string,
  directoryId?: string | null,
): Promise<StorageObject> {
  const data = await request<{ storage_object: StorageObject }>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/files/${encodeURIComponent(
      storageObjectId,
    )}/link`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ directory_id: directoryId ?? null }),
    },
  )
  return data.storage_object
}

export async function unlinkCaseFile(
  caseId: string,
  storageObjectId: string,
): Promise<{ unlinked: boolean; storage_object: StorageObject }> {
  return request<{ unlinked: boolean; storage_object: StorageObject }>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/files/${encodeURIComponent(
      storageObjectId,
    )}/link`,
    { method: 'DELETE' },
  )
}

export async function listCaseAutoAssignRules(
  caseId: string,
): Promise<CaseAutoAssignRule[]> {
  const data = await request<ListResponse<CaseAutoAssignRule>>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/auto-assign-rules`,
  )
  return data.items
}

export async function createCaseAutoAssignRule(
  caseId: string,
  payload: { sender_email: string; label?: string | null },
): Promise<CaseAutoAssignRule> {
  const data = await request<{ rule: CaseAutoAssignRule }>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/auto-assign-rules`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  return data.rule
}

export function deleteCaseAutoAssignRule(
  caseId: string,
  ruleId: string,
): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/auto-assign-rules/${encodeURIComponent(
      ruleId,
    )}`,
    { method: 'DELETE' },
  )
}

export function getCase(caseId: string): Promise<CaseDetail> {
  return request<CaseDetail>(`/api/v1/cases/${encodeURIComponent(caseId)}`)
}

export async function regenerateCaseCurrentSituation(
  caseId: string,
): Promise<CaseCurrentSituation> {
  const data = await request<{ current_situation: CaseCurrentSituation }>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/current-situation`,
    { method: 'POST' },
  )
  return data.current_situation
}

export async function updateCase(
  caseId: string,
  payload: {
    name?: string
    description: string | null
    open_when_date: string | null
    open_when_text: string | null
    closed_when_text: string | null
    genre_id?: string | null
    tags?: string[]
  },
): Promise<CaseItem> {
  const data = await request<{ case: CaseItem }>(
    `/api/v1/cases/${encodeURIComponent(caseId)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  return data.case
}

export async function createCase(payload: {
  name: string
  description: string | null
  open_when_date?: string | null
  open_when_text?: string | null
  closed_when_text?: string | null
  progress_status: string
  ball_status?: string | null
  genre_id?: string | null
  tags?: string[]
}): Promise<CaseItem> {
  const data = await request<{ case: CaseItem }>('/api/v1/cases', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return data.case
}

export async function deleteCase(caseId: string): Promise<void> {
  await request<{ deleted: boolean }>(
    `/api/v1/cases/${encodeURIComponent(caseId)}`,
    { method: 'DELETE' },
  )
}

export async function completeCase(caseId: string): Promise<CaseItem> {
  const data = await request<{ case: CaseItem }>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/complete`,
    { method: 'POST' },
  )
  return data.case
}

export async function reopenCase(caseId: string): Promise<CaseItem> {
  const data = await request<{ case: CaseItem }>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/reopen`,
    { method: 'POST' },
  )
  return data.case
}

export async function archiveCase(caseId: string): Promise<CaseItem> {
  const data = await request<{ case: CaseItem }>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/archive`,
    { method: 'POST' },
  )
  return data.case
}

export async function listCaseStakeholders(caseId: string): Promise<CaseStakeholder[]> {
  const data = await request<ListResponse<CaseStakeholder>>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/stakeholders`,
  )
  return data.items
}

export async function createCaseStakeholder(
  caseId: string,
  payload: { contact_id: string; role: string },
): Promise<CaseStakeholder> {
  const data = await request<{ stakeholder: CaseStakeholder }>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/stakeholders`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  return data.stakeholder
}

export async function updateCaseStakeholder(
  caseId: string,
  stakeholderId: string,
  payload: { role: string },
): Promise<CaseStakeholder> {
  const data = await request<{ stakeholder: CaseStakeholder }>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/stakeholders/${encodeURIComponent(
      stakeholderId,
    )}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  return data.stakeholder
}

export async function reorderCaseStakeholders(
  caseId: string,
  stakeholderIds: string[],
): Promise<CaseStakeholder[]> {
  const data = await request<ListResponse<CaseStakeholder>>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/stakeholders/reorder`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ stakeholder_ids: stakeholderIds }),
    },
  )
  return data.items
}

export async function deleteCaseStakeholder(
  caseId: string,
  stakeholderId: string,
): Promise<void> {
  await request<{ deleted: boolean }>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/stakeholders/${encodeURIComponent(
      stakeholderId,
    )}`,
    { method: 'DELETE' },
  )
}

export async function listCaseToolLinks(caseId: string): Promise<CaseToolLink[]> {
  const data = await request<ListResponse<CaseToolLink>>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/tool-links`,
  )
  return data.items
}

export async function listCaseToolIconSettings(): Promise<CaseToolIconSetting[]> {
  const data = await request<ListResponse<CaseToolIconSetting>>('/api/v1/cases/tool-icons')
  return data.items
}

export async function createCaseToolIconSetting(payload: {
  icon_filename: string | null
  icon_content_type: string
  icon_data_base64: string
  match_url: string
}): Promise<CaseToolIconSetting> {
  const data = await request<{ tool_icon: CaseToolIconSetting }>('/api/v1/cases/tool-icons', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return data.tool_icon
}

export async function updateCaseToolIconSetting(
  toolIconId: string,
  payload: {
    icon_filename?: string | null
    icon_content_type?: string
    icon_data_base64?: string
    match_url?: string
  },
): Promise<CaseToolIconSetting> {
  const data = await request<{ tool_icon: CaseToolIconSetting }>(
    `/api/v1/cases/tool-icons/${encodeURIComponent(toolIconId)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  return data.tool_icon
}

export function deleteCaseToolIconSetting(toolIconId: string): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(
    `/api/v1/cases/tool-icons/${encodeURIComponent(toolIconId)}`,
    { method: 'DELETE' },
  )
}

export async function createCaseToolLink(
  caseId: string,
  payload: { url: string; icon_label?: string | null },
): Promise<CaseToolLink> {
  const data = await request<{ tool_link: CaseToolLink }>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/tool-links`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  return data.tool_link
}

export async function reorderCaseToolLinks(
  caseId: string,
  toolLinkIds: string[],
): Promise<CaseToolLink[]> {
  const data = await request<ListResponse<CaseToolLink>>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/tool-links/reorder`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tool_link_ids: toolLinkIds }),
    },
  )
  return data.items
}

export async function deleteCaseToolLink(
  caseId: string,
  toolLinkId: string,
): Promise<void> {
  await request<{ deleted: boolean }>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/tool-links/${encodeURIComponent(
      toolLinkId,
    )}`,
    { method: 'DELETE' },
  )
}
