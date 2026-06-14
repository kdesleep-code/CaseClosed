export type ContactEmailAddress = {
  id: string
  email_address: string
  normalized_email_address: string
  resolution_status: string
  status?: 'active' | 'inactive' | 'deleted'
  is_primary: boolean
  source: string | null
  first_seen_at: string | null
  last_seen_at: string | null
  has_inbound_message_history?: boolean
  deactivated_at?: string | null
}

export type Contact = {
  id: string
  display_name: string
  avatar_url: string | null
  user_memo: string | null
  ai_memo: string | null
  status: string
  kind?: 'person' | 'mailing_list' | 'service'
  sender_resolution_mode?: 'self' | 'reply_to'
  mailing_list_recipient_expression?: string | null
  mail_importance_rule_action?: 'llm' | 'fixed' | 'llm_with_instruction'
  mail_importance_rule_importance?: 'pinned' | 'high' | 'middle' | 'low' | null
  mail_importance_rule_instruction?: string | null
  inbound_message_count: number
  latest_received_at: string | null
  tags: string[]
  email_addresses: ContactEmailAddress[]
  created_at: string
  updated_at: string
  version: number
}

export type StorageSourceMail = {
  id: string
  received_at: string
  subject: string | null
  from_address: string
  from_name: string | null
  effective_importance: string
  read_status: string
  summary: string | null
  has_attachments: boolean
}

export type StorageObject = {
  id: string
  directory_id: string | null
  directory_path?: string[]
  physical_directory_id?: string | null
  physical_directory_path?: string[]
  physical_directory_url?: string
  display_source?: 'physical' | 'link' | string
  location_id: string
  scope: string
  original_filename: string | null
  content_type: string | null
  byte_size: number
  sha256_hex: string
  llm_input_allowed: boolean
  file_icon_setting_id?: string | null
  file_icon_url?: string | null
  source_type: 'direct_upload' | 'mail_attachment' | string | null
  source_message_id: string | null
  source_mail?: StorageSourceMail | null
  url: string
  created_at: string
  updated_at: string
  file_updated_at: string
}

export type StorageObjectVersion = {
  id: string
  storage_object_id: string
  version_number: number
  original_filename: string | null
  content_type: string | null
  byte_size: number
  sha256_hex: string
  url: string
  download_url: string
  created_at: string
}

export type StorageLocation = {
  id: string
  label: string
  kind: string
  root_path: string
  mount_hint: string | null
  marker_id: string | null
  status: string
  object_count: number
  active_byte_size: number
  created_at: string
  updated_at: string
  version: number
}

export type StorageDirectory = {
  id: string
  parent_id: string | null
  directory_kind: 'normal' | 'case' | string
  case_id: string | null
  name: string
  status: string
  created_at: string
  updated_at: string
  version: number
}

export type StorageDirectoryList = {
  items: StorageDirectory[]
  breadcrumbs: StorageDirectory[]
}

export type StorageDirectoryDeleteResult = {
  deleted_directory_id: string
  deleted_directory_count: number
  deleted_object_count: number
  restored_attachment_count: number
}

export type ContactImageUploadResponse = {
  storage_object: StorageObject
  contact: {
    id: string
    avatar_url: string | null
    updated_at: string
    version: number
  }
}

export type TemporaryObjectUploadResponse = {
  storage_object: StorageObject
}

export type StorageObjectDeleteResult = {
  deleted_storage_object_id: string
  restored_storage_object: StorageObject | null
  source_type: string
}

export type StorageObjectLinkedCase = {
  case_id: string
  case_name: string
  source: 'physical' | 'link' | string
  file_link_id: string | null
  created_at: string | null
  updated_at: string
  case_url: string
}

export type StorageArchiveTree = {
  tree_text: string
  entry_count: number
  file_count: number
  directory_count: number
  total_uncompressed_size: number
  truncated: boolean
  max_entries: number
}

export type StorageObjectVersionUploadResponse = {
  storage_object: StorageObject
  version: StorageObjectVersion | null
  skipped: boolean
  skip_reason: 'duplicate_content' | string | null
}

export type StorageObjectOlderVersionsDeleteResult = {
  storage_object: StorageObject
  selected_version_id: string
  deleted_version_ids: string[]
  deleted_version_count: number
}

export type FileSummary = {
  id: string
  storage_object_id: string
  storage_object_version_id: string | null
  source_sha256_hex: string
  source_filename: string | null
  source_content_type: string | null
  source_byte_size: number
  summary_type: string
  file_description: string
  summary_points: string[]
  llm_digest: string
  structured_digest: Record<string, unknown>
  coverage: Record<string, unknown>
  token_estimate: number | null
  llm_run_id: string | null
  created_at: string
  updated_at: string
  version: number
}

export type FileVersionDiff = {
  id: string
  storage_object_id: string
  previous_version_id: string
  previous_sha256_hex: string
  current_sha256_hex: string
  diff_kind: string
  summary_text: string
  added_lines: string[]
  removed_lines: string[]
  display_lines: Array<{ kind: 'context' | 'added' | 'removed' | 'ellipsis'; text: string }>
  coverage: Record<string, unknown>
  created_at: string
  updated_at: string
  version: number
}

export type FileSummaryReadResponse = {
  summary: FileSummary | null
  source_sha256_hex: string
  storage_object_version_id: string | null
  is_stale: boolean
  stale_reason: string | null
  diff: FileVersionDiff | null
}

export type FileSummaryPrepareResponse = {
  summary: FileSummary
  storage_object: StorageObject
  source_sha256_hex: string
  storage_object_version_id: string | null
  is_stale: boolean
  stale_reason: string | null
  diff: FileVersionDiff | null
}

export type StorageEmlPreview = {
  subject: string | null
  from: string | null
  to: string | null
  cc: string | null
  date: string | null
  reply_to: string | null
  message_id: string | null
  body_text: string | null
  body_html: string | null
  sender_contact: {
    id: string
    display_name: string
    avatar_url: string | null
    kind: string
    status: string
  } | null
  attachments: Array<{
    filename: string
    content_type: string
    byte_size: number
  }>
}

export type StorageObjectSearchResult = {
  items: StorageObject[]
  extensions: string[]
}

export type UnresolvedFromAddress = {
  email_address_id: string
  email_address: string
  normalized_email_address: string
  message_count: number
  latest_message_id: string | null
  latest_subject: string | null
  latest_from_name: string | null
  latest_from_address: string | null
  latest_reply_to_address: string | null
  latest_received_at: string | null
  latest_body_preview: string | null
  inferred_display_name: string
  inferred_kind: 'person' | 'mailing_list'
  inferred_sender_resolution: 'self' | 'reply_to'
  suggestion_status: string
  suggestion: {
    id: string
    suggested_display_name: string | null
    suggested_tags: string[]
    confidence: number | null
  } | null
}

export type ContactCustomTab = {
  id: string
  label: string
  expression: string
}

export type FileIconSetting = {
  id: string
  storage_object_id: string | null
  icon_filename: string | null
  icon_content_type: string
  icon_url: string | null
  icon_data_url?: string | null
  extensions: string[]
  created_at: string
  updated_at: string
  version: number
}

export type ContactCreatePayload = {
  display_name: string
  avatar_url?: string | null
  user_memo: string
  ai_memo?: string | null
  status: 'active' | 'archived' | 'skipped' | 'spam'
  kind: 'person' | 'mailing_list' | 'service'
  sender_resolution_mode: 'self' | 'reply_to'
  mailing_list_recipient_expression?: string | null
  mail_importance_rule_action?: 'llm' | 'fixed' | 'llm_with_instruction'
  mail_importance_rule_importance?: 'pinned' | 'high' | 'middle' | 'low' | null
  mail_importance_rule_instruction?: string | null
  tags: string[]
  email_addresses: Array<{
    email_address: string
    is_primary: boolean
  }>
  source_suggestion_id?: string | null
}

export type ContactUpdatePayload = {
  display_name: string
  avatar_url: string | null
  user_memo: string
  ai_memo?: string | null
  status: 'active' | 'skipped' | 'spam' | 'archived'
  kind: 'person' | 'mailing_list' | 'service'
  sender_resolution_mode: 'self' | 'reply_to'
  mailing_list_recipient_expression?: string | null
  mail_importance_rule_action: 'llm' | 'fixed' | 'llm_with_instruction'
  mail_importance_rule_importance: 'pinned' | 'high' | 'middle' | 'low' | null
  mail_importance_rule_instruction: string | null
  tags: string[]
}

type ListResponse<T> = {
  items: T[]
}

type ContactDetailResponse = {
  contact: Contact
  related_cases: []
}

type ContactEmailAddressMoveResponse = {
  source_contact: Contact
  target_contact: Contact
}

type ContactMergeResponse = {
  deleted_contact_id: string
  target_contact: Contact
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

export class Phase3ApiError extends Error {
  code: string
  status: number

  constructor(status: number, error: ApiError) {
    super(error.message)
    this.name = 'Phase3ApiError'
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
      : { code: 'PHASE_3_REQUEST_FAILED', message: 'Request failed.' }
    throw new Phase3ApiError(response.status, error)
  }

  return payload.data
}

export async function listContacts(): Promise<Contact[]> {
  const data = await request<ListResponse<Contact>>('/api/v1/contacts')
  return data.items
}

export async function listContactCustomTabs(): Promise<ContactCustomTab[]> {
  const data = await request<ListResponse<ContactCustomTab>>(
    '/api/v1/contacts/custom-tabs',
  )
  return data.items
}

export async function saveContactCustomTabs(
  items: ContactCustomTab[],
): Promise<ContactCustomTab[]> {
  const data = await request<ListResponse<ContactCustomTab>>(
    '/api/v1/contacts/custom-tabs',
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items }),
    },
  )
  return data.items
}

export async function getContactDetail(contactId: string): Promise<ContactDetailResponse> {
  return request<ContactDetailResponse>(
    `/api/v1/contacts/${encodeURIComponent(contactId)}`,
  )
}

export function createContact(payload: ContactCreatePayload): Promise<Contact> {
  return request<Contact>('/api/v1/contacts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function updateContact(
  contactId: string,
  payload: ContactUpdatePayload,
): Promise<Contact> {
  return request<Contact>(`/api/v1/contacts/${encodeURIComponent(contactId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function uploadContactImage(
  contactId: string,
  payload: {
    filename: string | null
    content_type: string
    data_base64: string
  },
): Promise<ContactImageUploadResponse> {
  return request<ContactImageUploadResponse>(
    `/api/v1/storage/contacts/${encodeURIComponent(contactId)}/image`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export function uploadTemporaryObject(payload: {
  filename: string | null
  content_type: string | null
  data_base64: string
}): Promise<TemporaryObjectUploadResponse> {
  return request<TemporaryObjectUploadResponse>('/api/v1/storage/tmp', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export async function listStorageObjects(params: {
  status?: string
  location_id?: string
  directory_id?: string | null
  limit?: number
} = {}): Promise<StorageObject[]> {
  const query = new URLSearchParams()
  if (params.status !== undefined) query.set('status', params.status)
  if (params.location_id !== undefined) query.set('location_id', params.location_id)
  if (params.directory_id !== undefined) {
    query.set('directory_id', params.directory_id ?? 'root')
  }
  if (params.limit !== undefined) query.set('limit', String(params.limit))
  const suffix = query.toString() === '' ? '' : `?${query.toString()}`
  const data = await request<ListResponse<StorageObject>>(`/api/v1/storage/objects${suffix}`)
  return data.items
}

export function searchStorageObjects(params: {
  query?: string
  directory_id?: string | null
  recursive?: boolean
  sort?: 'name' | 'created_desc' | 'created_asc'
  extension?: string | null
  limit?: number
} = {}): Promise<StorageObjectSearchResult> {
  const query = new URLSearchParams()
  query.set('q', params.query ?? '')
  query.set('directory_id', params.directory_id ?? 'root')
  query.set('recursive', params.recursive === false ? 'false' : 'true')
  query.set('sort', params.sort ?? 'created_desc')
  query.set('extension', params.extension ?? 'all')
  if (params.limit !== undefined) query.set('limit', String(params.limit))
  return request<StorageObjectSearchResult>(
    `/api/v1/storage/search/objects?${query.toString()}`,
  )
}

export function listStorageDirectories(parentId: string | null = null): Promise<StorageDirectoryList> {
  const query = new URLSearchParams()
  query.set('parent_id', parentId ?? 'root')
  return request<StorageDirectoryList>(`/api/v1/storage/directories?${query.toString()}`)
}

export function createStorageDirectory(payload: {
  name: string
  parent_id: string | null
}): Promise<{ directory: StorageDirectory }> {
  return request<{ directory: StorageDirectory }>('/api/v1/storage/directories', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function deleteStorageDirectory(
  directoryId: string,
): Promise<StorageDirectoryDeleteResult> {
  return request<StorageDirectoryDeleteResult>(
    `/api/v1/storage/directories/${encodeURIComponent(directoryId)}`,
    { method: 'DELETE' },
  )
}

export async function moveStorageDirectoryToDirectory(
  directoryId: string,
  parentId: string | null,
): Promise<StorageDirectory> {
  const data = await request<{ directory: StorageDirectory }>(
    `/api/v1/storage/directories/${encodeURIComponent(directoryId)}/parent`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ parent_id: parentId }),
    },
  )
  return data.directory
}

export async function getStorageObject(storageObjectId: string): Promise<StorageObject> {
  const data = await request<{ storage_object: StorageObject }>(
    `/api/v1/storage/objects/${encodeURIComponent(storageObjectId)}`,
  )
  return data.storage_object
}

export function getStorageObjectArchiveTree(
  storageObjectId: string,
): Promise<StorageArchiveTree> {
  return request<StorageArchiveTree>(
    `/api/v1/storage/objects/${encodeURIComponent(storageObjectId)}/archive-tree`,
  )
}

export function getStorageObjectVersionArchiveTree(
  storageObjectId: string,
  versionId: string,
): Promise<StorageArchiveTree> {
  return request<StorageArchiveTree>(
    `/api/v1/storage/objects/${encodeURIComponent(
      storageObjectId,
    )}/versions/${encodeURIComponent(versionId)}/archive-tree`,
  )
}

export function getStorageObjectEmlPreview(
  storageObjectId: string,
): Promise<StorageEmlPreview> {
  return request<StorageEmlPreview>(
    `/api/v1/storage/objects/${encodeURIComponent(storageObjectId)}/eml-preview`,
  )
}

export function getStorageObjectVersionEmlPreview(
  storageObjectId: string,
  versionId: string,
): Promise<StorageEmlPreview> {
  return request<StorageEmlPreview>(
    `/api/v1/storage/objects/${encodeURIComponent(
      storageObjectId,
    )}/versions/${encodeURIComponent(versionId)}/eml-preview`,
  )
}

export async function listStorageObjectVersions(
  storageObjectId: string,
): Promise<StorageObjectVersion[]> {
  const data = await request<ListResponse<StorageObjectVersion>>(
    `/api/v1/storage/objects/${encodeURIComponent(storageObjectId)}/versions`,
  )
  return data.items
}

export function uploadStorageObjectVersion(
  storageObjectId: string,
  file: File,
): Promise<StorageObjectVersionUploadResponse> {
  const formData = new FormData()
  formData.append('file', file, file.name)
  return request<StorageObjectVersionUploadResponse>(
    `/api/v1/storage/objects/${encodeURIComponent(storageObjectId)}/versions/upload`,
    {
      method: 'POST',
      body: formData,
    },
  )
}

export async function updateStorageObjectLlmInput(
  storageObjectId: string,
  llmInputAllowed: boolean,
): Promise<StorageObject> {
  const data = await request<{ storage_object: StorageObject }>(
    `/api/v1/storage/objects/${encodeURIComponent(storageObjectId)}/llm-input`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ llm_input_allowed: llmInputAllowed }),
    },
  )
  return data.storage_object
}

export async function moveStorageObjectToDirectory(
  storageObjectId: string,
  directoryId: string | null,
): Promise<StorageObject> {
  const data = await request<{ storage_object: StorageObject }>(
    `/api/v1/storage/objects/${encodeURIComponent(storageObjectId)}/directory`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ directory_id: directoryId }),
    },
  )
  return data.storage_object
}

export function deleteStorageObject(
  storageObjectId: string,
): Promise<StorageObjectDeleteResult> {
  return request<StorageObjectDeleteResult>(
    `/api/v1/storage/objects/${encodeURIComponent(storageObjectId)}`,
    { method: 'DELETE' },
  )
}

export async function listStorageObjectLinkedCases(
  storageObjectId: string,
): Promise<StorageObjectLinkedCase[]> {
  const data = await request<ListResponse<StorageObjectLinkedCase>>(
    `/api/v1/storage/objects/${encodeURIComponent(storageObjectId)}/linked-cases`,
  )
  return data.items
}

export async function createStorageObjectCaseLink(
  storageObjectId: string,
  caseId: string,
): Promise<StorageObjectLinkedCase[]> {
  const data = await request<ListResponse<StorageObjectLinkedCase>>(
    `/api/v1/storage/objects/${encodeURIComponent(storageObjectId)}/linked-cases`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ case_id: caseId }),
    },
  )
  return data.items
}

export async function deleteStorageObjectCaseLink(
  storageObjectId: string,
  caseId: string,
): Promise<StorageObjectLinkedCase[]> {
  const data = await request<ListResponse<StorageObjectLinkedCase>>(
    `/api/v1/storage/objects/${encodeURIComponent(
      storageObjectId,
    )}/linked-cases/${encodeURIComponent(caseId)}`,
    { method: 'DELETE' },
  )
  return data.items
}

export function deleteOlderStorageObjectVersions(
  storageObjectId: string,
  versionId: string,
): Promise<StorageObjectOlderVersionsDeleteResult> {
  return request<StorageObjectOlderVersionsDeleteResult>(
    `/api/v1/storage/objects/${encodeURIComponent(
      storageObjectId,
    )}/versions/${encodeURIComponent(versionId)}/older`,
    { method: 'DELETE' },
  )
}

export function getStorageObjectLlmDigest(
  storageObjectId: string,
  versionId: string | null = null,
): Promise<FileSummaryReadResponse> {
  const params = new URLSearchParams()
  if (versionId !== null) {
    params.set('version_id', versionId)
  }
  const suffix = params.toString() === '' ? '' : `?${params.toString()}`
  return request<FileSummaryReadResponse>(
    `/api/v1/storage/objects/${encodeURIComponent(storageObjectId)}/llm-digest${suffix}`,
  )
}

export function prepareStorageObjectLlmDigest(
  storageObjectId: string,
  versionId: string | null = null,
): Promise<FileSummaryPrepareResponse> {
  return request<FileSummaryPrepareResponse>(
    `/api/v1/storage/objects/${encodeURIComponent(storageObjectId)}/llm-digest`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ storage_object_version_id: versionId }),
    },
  )
}

export async function listStorageLocations(): Promise<StorageLocation[]> {
  const data = await request<ListResponse<StorageLocation>>('/api/v1/storage/locations')
  return data.items
}

export async function listFileIconSettings(): Promise<FileIconSetting[]> {
  const data = await request<ListResponse<FileIconSetting>>('/api/v1/storage/file-icons')
  return data.items
}

export async function createFileIconSetting(payload: {
  icon_filename: string | null
  icon_content_type: string
  icon_data_base64: string
  extensions: string[]
}): Promise<FileIconSetting> {
  const data = await request<{ file_icon: FileIconSetting }>('/api/v1/storage/file-icons', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return data.file_icon
}

export async function updateFileIconSetting(
  fileIconId: string,
  payload: {
    icon_filename?: string | null
    icon_content_type?: string
    icon_data_base64?: string
    extensions?: string[]
  },
): Promise<FileIconSetting> {
  const data = await request<{ file_icon: FileIconSetting }>(
    `/api/v1/storage/file-icons/${encodeURIComponent(fileIconId)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  return data.file_icon
}

export function deleteFileIconSetting(fileIconId: string): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(
    `/api/v1/storage/file-icons/${encodeURIComponent(fileIconId)}`,
    { method: 'DELETE' },
  )
}

export function uploadManagedStorageObject(payload: {
  filename: string | null
  content_type: string | null
  data_base64: string
}): Promise<TemporaryObjectUploadResponse> {
  return request<TemporaryObjectUploadResponse>('/api/v1/storage/objects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function uploadManagedStorageFile(
  file: File,
  directoryId: string | null = null,
): Promise<TemporaryObjectUploadResponse> {
  const formData = new FormData()
  formData.append('file', file, file.name)
  const query = new URLSearchParams()
  if (directoryId !== null) query.set('directory_id', directoryId)
  const suffix = query.toString() === '' ? '' : `?${query.toString()}`
  return request<TemporaryObjectUploadResponse>(`/api/v1/storage/objects/upload${suffix}`, {
    method: 'POST',
    body: formData,
  })
}

export function deleteContact(contactId: string): Promise<{ deleted_contact_id: string }> {
  return request<{ deleted_contact_id: string }>(
    `/api/v1/contacts/${encodeURIComponent(contactId)}`,
    { method: 'DELETE' },
  )
}

export function addContactEmailAddress(
  contactId: string,
  emailAddress: string,
): Promise<Contact> {
  return request<Contact>(
    `/api/v1/contacts/${encodeURIComponent(contactId)}/email-addresses`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email_address: emailAddress, is_primary: false }),
    },
  )
}

export function setContactPrimaryEmailAddress(
  contactId: string,
  emailAddressId: string,
): Promise<Contact> {
  return request<Contact>(
    `/api/v1/contacts/${encodeURIComponent(
      contactId,
    )}/email-addresses/${encodeURIComponent(emailAddressId)}/primary`,
    { method: 'POST' },
  )
}

export function activateContactEmailAddress(
  contactId: string,
  emailAddressId: string,
): Promise<Contact> {
  return request<Contact>(
    `/api/v1/contacts/${encodeURIComponent(
      contactId,
    )}/email-addresses/${encodeURIComponent(emailAddressId)}/activate`,
    { method: 'POST' },
  )
}

export function deleteContactEmailAddress(
  contactId: string,
  emailAddressId: string,
): Promise<Contact> {
  return request<Contact>(
    `/api/v1/contacts/${encodeURIComponent(
      contactId,
    )}/email-addresses/${encodeURIComponent(emailAddressId)}`,
    { method: 'DELETE' },
  )
}

export function moveContactEmailAddress(
  sourceContactId: string,
  emailAddressId: string,
  targetContactId: string,
): Promise<ContactEmailAddressMoveResponse> {
  return request<ContactEmailAddressMoveResponse>(
    `/api/v1/contacts/${encodeURIComponent(
      sourceContactId,
    )}/email-addresses/${encodeURIComponent(emailAddressId)}/move`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target_contact_id: targetContactId }),
    },
  )
}

export function mergeContact(
  sourceContactId: string,
  targetContactId: string,
): Promise<ContactMergeResponse> {
  return request<ContactMergeResponse>(
    `/api/v1/contacts/${encodeURIComponent(sourceContactId)}/merge`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target_contact_id: targetContactId }),
    },
  )
}

export async function listUnresolvedFromAddresses(): Promise<
  UnresolvedFromAddress[]
> {
  const data = await request<ListResponse<UnresolvedFromAddress>>(
    '/api/v1/contacts/unresolved-from-addresses',
  )
  return data.items
}

export function generateContactPrefill(
  emailAddress: string,
  messageId: string | null,
): Promise<{ job_id: string }> {
  return request<{ job_id: string }>(
    `/api/v1/contacts/unresolved-from-addresses/${encodeURIComponent(
      emailAddress,
    )}/generate-prefill`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message_id: messageId }),
    },
  )
}
