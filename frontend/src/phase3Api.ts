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
  memo: string | null
  status: string
  kind?: 'person' | 'mailing_list'
  sender_resolution_mode?: 'self' | 'reply_to'
  mailing_list_recipient_expression?: string | null
  tags: string[]
  email_addresses: ContactEmailAddress[]
  created_at: string
  updated_at: string
  version: number
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

export type ContactCreatePayload = {
  display_name: string
  avatar_url?: string | null
  memo: string
  status: 'active' | 'skipped'
  kind: 'person' | 'mailing_list'
  sender_resolution_mode: 'self' | 'reply_to'
  mailing_list_recipient_expression?: string | null
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
  memo: string
  status: 'active' | 'skipped' | 'archived'
  kind: 'person' | 'mailing_list'
  sender_resolution_mode: 'self' | 'reply_to'
  mailing_list_recipient_expression?: string | null
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
