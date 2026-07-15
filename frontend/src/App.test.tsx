import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { fireEvent, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import { applyLanguagePatch, resetLanguagePatch } from './i18n'
import { navigateTo } from './navigation'

function apiResponse(status: number, body: object) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

function activeSessionResponse() {
  return apiResponse(200, {
    ok: true,
    data: {
      authenticated: true,
      session_expires_at: '2026-05-23T01:00:00Z',
      client_certificate_id: 'cert_test',
      device_name: 'Bootstrap device',
      ip_address: '127.0.0.1',
      access_mode: 'full',
    },
  })
}

function expectRecipientToken(address: string) {
  expect(screen.getByRole('button', { name: `Remove ${address}` })).toBeInTheDocument()
}

afterEach(() => {
  resetLanguagePatch()
  window.history.pushState({}, '', '/')
})

describe('Phase 1 login screen', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        apiResponse(401, {
          ok: false,
          error: { code: 'UNAUTHORIZED', message: 'No active session.' },
        }),
      ),
    )
  })

  it('offers the app password login controls', async () => {
    render(<App />)

    expect(
      await screen.findByRole('heading', { level: 1, name: 'CaseClosed' }),
    ).toBeInTheDocument()
    expect(screen.getByAltText('CaseClosed mascot')).toBeInTheDocument()
    expect(screen.getByLabelText('Password')).toHaveAttribute('type', 'password')
    expect(screen.getByRole('button', { name: 'Log in' })).toBeInTheDocument()
  })

  it('uses a runtime language patch for visible login labels', async () => {
    applyLanguagePatch({
      'login.password.label': 'Secret phrase',
      'login.submit': 'Enter',
      'login.mascot.alt': 'CaseClosed mascot patched',
    })

    render(<App />)

    expect(await screen.findByLabelText('Secret phrase')).toHaveAttribute('type', 'password')
    expect(screen.getByRole('button', { name: 'Enter' })).toBeInTheDocument()
    expect(screen.getByAltText('CaseClosed mascot patched')).toBeInTheDocument()
  })

  it('keeps the default login screen focused on authentication', async () => {
    render(<App />)

    await screen.findByRole('heading', { level: 1, name: 'CaseClosed' })
    expect(screen.queryByText('Device')).not.toBeInTheDocument()
    expect(screen.queryByText('Certificate')).not.toBeInTheDocument()
    expect(screen.queryByText('Failed attempts')).not.toBeInTheDocument()
    expect(screen.queryByText('Locked')).not.toBeInTheDocument()
  })

  it('allows the password to be entered', async () => {
    const user = userEvent.setup()
    render(<App />)

    const password = await screen.findByLabelText('Password')
    await user.type(password, 'phase-one-password')

    expect(password).toHaveValue('phase-one-password')
  })

  it('does not flash the login controls while the session check is pending', () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})))

    render(<App />)

    expect(screen.getByLabelText('Checking session')).toBeInTheDocument()
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument()
  })

  it('submits the app password and enters the authenticated shell', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.mocked(fetch)
    fetchMock
      .mockImplementationOnce(() =>
        apiResponse(401, {
          ok: false,
          error: { code: 'UNAUTHORIZED', message: 'No active session.' },
        }),
      )
      .mockImplementationOnce(() =>
        apiResponse(200, {
          ok: true,
          data: {
            session_expires_at: '2026-05-23T01:00:00Z',
            device_name: null,
            ip_address: '127.0.0.1',
          },
        }),
      )
      .mockImplementationOnce(() =>
        apiResponse(200, { ok: true, data: { items: [] } }),
      )

    render(<App />)
    await user.type(await screen.findByLabelText('Password'), 'phase-one-password')
    await user.click(screen.getByRole('button', { name: 'Log in' }))

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/auth/login',
      expect.objectContaining({
        credentials: 'include',
        method: 'POST',
        body: JSON.stringify({ password: 'phase-one-password' }),
      }),
    )
    expect(
      await screen.findByRole('heading', { name: 'Top' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'Main pages' })).toHaveTextContent(
      'Mail',
    )
    expect(screen.getByRole('navigation', { name: 'Main pages' })).toHaveTextContent(
      'Profile',
    )
    expect(
      screen.queryByRole('navigation', { name: 'Main work' }),
    ).not.toBeInTheDocument()
    expect(screen.getByLabelText('Current session')).toHaveTextContent(
      'IP 127.0.0.1',
    )
    expect(screen.getByLabelText('Current session')).toHaveTextContent(
      '2026/05/23 10:00 JST',
    )
  })

  it('shows a login error returned by the API', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.mocked(fetch)
    fetchMock
      .mockImplementationOnce(() =>
        apiResponse(401, {
          ok: false,
          error: { code: 'UNAUTHORIZED', message: 'No active session.' },
        }),
      )
      .mockImplementationOnce(() =>
        apiResponse(401, {
          ok: false,
          error: { code: 'INVALID_CREDENTIALS', message: 'Invalid password.' },
        }),
      )

    render(<App />)
    await user.type(await screen.findByLabelText('Password'), 'wrong password')
    await user.click(screen.getByRole('button', { name: 'Log in' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Invalid password.',
    )
  })

  it('shows a locked login state returned by the API', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.mocked(fetch)
    fetchMock
      .mockImplementationOnce(() =>
        apiResponse(401, {
          ok: false,
          error: { code: 'UNAUTHORIZED', message: 'No active session.' },
        }),
      )
      .mockImplementationOnce(() =>
        apiResponse(423, {
          ok: false,
          error: { code: 'LOGIN_LOCKED', message: 'Login is locked.' },
        }),
      )

    render(<App />)
    await user.type(await screen.findByLabelText('Password'), 'phase-one-password')
    await user.click(screen.getByRole('button', { name: 'Log in' }))

    expect(await screen.findByText('Locked')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('Login is locked.')
  })

  it('enters the authenticated shell when an active session exists', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: string | URL | Request) => {
        const path = input.toString()
        if (path === '/api/v1/auth/session') {
          return activeSessionResponse()
        }
        if (path === '/api/v1/contacts/unresolved-from-addresses') {
          return apiResponse(200, { ok: true, data: { items: [] } })
        }
        throw new Error(`Unexpected request: ${path}`)
      }),
    )

    render(<App />)

    expect(
      await screen.findByRole('heading', { name: 'Top' }),
    ).toBeInTheDocument()
    expect(screen.getByLabelText('Current session')).toHaveTextContent(
      'Bootstrap device',
    )
  })

  it('locks the top page except pending contacts when pending contacts exist', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: string | URL | Request) => {
        const path = input.toString()
        if (path === '/api/v1/auth/session') {
          return activeSessionResponse()
        }
        if (path === '/api/v1/contacts/unresolved-from-addresses') {
          return apiResponse(200, {
            ok: true,
            data: {
              items: [
                {
                  email_address_id: 'email_pending_top',
                  email_address: 'pending.top@example.com',
                  normalized_email_address: 'pending.top@example.com',
                  message_count: 1,
                  latest_message_id: 'mail_pending_top',
                  latest_subject: 'Pending top',
                  suggestion_status: 'not_started',
                  suggestion: null,
                },
              ],
            },
          })
        }
        throw new Error(`Unexpected request: ${path}`)
      }),
    )

    render(<App />)

    expect(
      await screen.findByRole('heading', {
        name: 'Pending contacts are blocking the workspace',
      }),
    ).toBeInTheDocument()
    expect(screen.getByText('Pending contacts: 1')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Mail' })).not.toBeInTheDocument()
    expect(screen.getByText('Mail')).toHaveAttribute('aria-disabled', 'true')
    expect(screen.getByRole('link', { name: 'Open Pending Contacts' })).toHaveAttribute(
      'href',
      '/contacts/pending',
    )
  })
})

describe('Phase 4 mail screen', () => {
  it('opens the compose mail view with a two-column drafting surface', async () => {
    const user = userEvent.setup()
    window.history.pushState({}, '', '/mail/compose')
    let sentPayload: unknown = null
    vi.stubGlobal(
      'fetch',
      vi.fn((input: string | URL | Request, init?: RequestInit) => {
        const path = input.toString()
        if (path === '/api/v1/auth/session') {
          return activeSessionResponse()
        }
        if (path === '/api/v1/mails/send') {
          sentPayload = JSON.parse(String(init?.body ?? '{}'))
          return Promise.resolve(
            new Response(
              JSON.stringify({
                ok: true,
                data: {
                  id: 'mail_send_test',
                  status: 'scheduled_mock',
                  to_addresses: ['receiver@example.com'],
                  cc_addresses: [],
                  bcc_addresses: [],
                  subject: 'Draft subject',
                  body_text: 'Draft body',
                  attachment_names: [],
                  reply_to_message_id: null,
                  sent_message_id: null,
                  scheduled_at: '2026-05-25T10:01:00+09:00',
                  created_at: '2026-05-25T10:00:00+09:00',
                  updated_at: '2026-05-25T10:00:00+09:00',
                  version: 1,
                },
              }),
              { status: 200, headers: { 'Content-Type': 'application/json' } },
            ),
          )
        }
        if (path === '/api/v1/mails/mail_send_test') {
          return apiResponse(200, {
            ok: true,
            data: {
              message: {
                id: 'mail_send_test',
                gmail_message_id: 'provisional:mail_send_test',
                gmail_thread_id: 'provisional_thread_mail_send_test',
                thread_id: 'provisional_thread_mail_send_test',
                received_at: '2026-05-25T10:01:00+09:00',
                received_date: '2026-05-25',
                subject: 'Draft subject',
                from_address: 'caseclosed.me@example.local',
                from_name: 'CaseClosed',
                from_contact: null,
                sender_contact: null,
                sender_address: null,
                reply_to_address: null,
                to_addresses: ['receiver@example.com'],
                cc_addresses: [],
                bcc_addresses: [],
                to_recipients: [{ email_address: 'receiver@example.com', contact: null }],
                cc_recipients: [],
                bcc_recipients: [],
                message_id_header: null,
                in_reply_to_header: null,
                references_header: null,
                list_id: null,
                snippet: 'Draft body',
                gmail_link: null,
                external_starred: false,
                gmail_labels: ['SENT'],
                body_text: 'Draft body',
                body_html: null,
                processed_status: 'processed',
                read_status: 'read',
                read_at: '2026-05-25T10:00:00+09:00',
                user_importance: null,
                effective_importance: 'sent',
                importance_rank: 7,
                external_importance: null,
                suggested_importance: null,
                llm_run_id: null,
                pending_reason: null,
                created_at: '2026-05-25T10:00:00+09:00',
                updated_at: '2026-05-25T10:00:00+09:00',
                version: 1,
              },
              thread_messages: [],
              scheduled_send_requests: [
                {
                  id: 'mail_send_test',
                  status: 'scheduled_mock',
                  to_addresses: ['receiver@example.com'],
                  cc_addresses: [],
                  bcc_addresses: [],
                  subject: 'Draft subject',
                  body_text: 'Draft body',
                  attachment_names: [],
                  reply_to_message_id: null,
                  sent_message_id: null,
                  scheduled_at: '2026-05-25T10:01:00+09:00',
                  created_at: '2026-05-25T10:00:00+09:00',
                  updated_at: '2026-05-25T10:00:00+09:00',
                  version: 1,
                },
              ],
              user_state: {
                user_importance: null,
                processed_status: 'processed',
                processed_at: '2026-05-25T10:00:00+09:00',
                read_status: 'read',
                read_at: '2026-05-25T10:00:00+09:00',
                version: 1,
              },
              auto_state: {
                external_importance: null,
                suggested_importance: null,
                llm_run_id: null,
                effective_importance: 'sent',
                pending_reason: null,
              },
              summary: null,
              available_actions: [],
            },
          })
        }

        throw new Error(`Unexpected request: ${path}`)
      }),
    )

    render(<App />)

    expect(
      await screen.findByRole('heading', { level: 1, name: 'Compose Mail' }),
    ).toBeInTheDocument()
    expect(screen.getByLabelText('To')).toBeInTheDocument()
    expect(screen.queryByLabelText('Cc')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Bcc')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'CC/BCC' }))
    expect(screen.getByLabelText('Cc')).toBeInTheDocument()
    expect(screen.getByLabelText('Bcc')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'CC/BCC' }))
    expect(screen.queryByLabelText('Cc')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Bcc')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Subject')).toBeInTheDocument()
    expect(screen.getByLabelText('Body')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Attachments' })).toBeInTheDocument()
    const dropZone = screen.getByText('Drop files here')
    const attachment = new File(['hello'], 'review-note.txt', { type: 'text/plain' })
    fireEvent.drop(dropZone, { dataTransfer: { files: [attachment] } })
    expect(screen.getByText('review-note.txt')).toBeInTheDocument()
    fireEvent.drop(dropZone, { dataTransfer: { files: [attachment] } })
    expect(screen.getAllByText('review-note.txt')).toHaveLength(1)
    await user.click(screen.getByRole('button', { name: 'Remove review-note.txt' }))
    expect(screen.queryByText('review-note.txt')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Compose tools')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Schedule send' })).toBeDisabled()

    await user.type(screen.getByLabelText('To'), 'receiver@example.com')
    await user.type(screen.getByLabelText('Subject'), 'Draft subject')
    await user.type(screen.getByLabelText('Body'), 'Draft body')

    expect(screen.getByLabelText('To')).toHaveValue('receiver@example.com')
    expect(screen.getByLabelText('Subject')).toHaveValue('Draft subject')
    expect(screen.getByLabelText('Body')).toHaveValue('Draft body')
    expect(screen.getByRole('button', { name: 'Send' })).toBeEnabled()

    await user.click(screen.getByLabelText('To'))
    await user.keyboard('{Enter}')
    expect(sentPayload).toBeNull()

    await user.click(screen.getByRole('button', { name: 'Send' }))

    expect(
      await screen.findByRole('heading', { level: 1, name: 'Draft subject' }),
    ).toBeInTheDocument()
    expect(screen.getByText('Scheduled send')).toBeInTheDocument()
    expect(sentPayload).toEqual({
      to_addresses: ['receiver@example.com'],
      cc_addresses: [],
      bcc_addresses: [],
      subject: 'Draft subject',
      body_text: 'Draft body',
      attachment_names: [],
      attachments: [],
      reply_to_message_id: null,
      scheduled_at: null,
    })
  })

  it('combines editable body and auto body before sending', async () => {
    const user = userEvent.setup()
    window.history.pushState(
      {},
      '',
      '/mail/compose?to=receiver%40example.com&subject=Combined&manual_body=Manual%20line&auto_body=Auto%20line',
    )
    let sentPayload: unknown = null
    vi.stubGlobal(
      'fetch',
      vi.fn((input: string | URL | Request, init?: RequestInit) => {
        const path = input.toString()
        if (path === '/api/v1/auth/session') {
          return activeSessionResponse()
        }
        if (path === '/api/v1/mails/send') {
          sentPayload = JSON.parse(String(init?.body ?? '{}'))
          return apiResponse(200, {
            ok: true,
            data: {
              id: 'mail_send_combined',
              status: 'scheduled_mock',
              to_addresses: ['receiver@example.com'],
              cc_addresses: [],
              bcc_addresses: [],
              subject: 'Combined',
              body_text: 'Manual line\n\nAuto line',
              attachment_names: [],
              reply_to_message_id: null,
              sent_message_id: null,
              scheduled_at: '2026-05-25T10:01:00+09:00',
              created_at: '2026-05-25T10:00:00+09:00',
              updated_at: '2026-05-25T10:00:00+09:00',
              version: 1,
            },
          })
        }
        if (path === '/api/v1/mails/mail_send_combined') {
          return apiResponse(200, {
            ok: true,
            data: {
              message: {
                id: 'mail_send_combined',
                gmail_message_id: 'provisional:mail_send_combined',
                gmail_thread_id: 'provisional_thread_mail_send_combined',
                thread_id: 'provisional_thread_mail_send_combined',
                received_at: '2026-05-25T10:01:00+09:00',
                received_date: '2026-05-25',
                subject: 'Combined',
                from_address: 'caseclosed.me@example.local',
                from_name: 'CaseClosed',
                from_contact: null,
                sender_contact: null,
                sender_address: null,
                reply_to_address: null,
                to_addresses: ['receiver@example.com'],
                cc_addresses: [],
                bcc_addresses: [],
                to_recipients: [{ email_address: 'receiver@example.com', contact: null }],
                cc_recipients: [],
                bcc_recipients: [],
                message_id_header: null,
                in_reply_to_header: null,
                references_header: null,
                list_id: null,
                snippet: 'Manual line',
                gmail_link: null,
                external_starred: false,
                gmail_labels: ['SENT'],
                body_text: 'Manual line\n\nAuto line',
                body_html: null,
                processed_status: 'processed',
                read_status: 'read',
                read_at: '2026-05-25T10:00:00+09:00',
                user_importance: null,
                effective_importance: 'sent',
                importance_rank: 7,
                external_importance: null,
                suggested_importance: null,
                llm_run_id: null,
                pending_reason: null,
                created_at: '2026-05-25T10:00:00+09:00',
                updated_at: '2026-05-25T10:00:00+09:00',
                version: 1,
              },
              thread_messages: [],
              scheduled_send_requests: [],
              user_state: {
                user_importance: null,
                processed_status: 'processed',
                processed_at: '2026-05-25T10:00:00+09:00',
                read_status: 'read',
                read_at: '2026-05-25T10:00:00+09:00',
                version: 1,
              },
              auto_state: {
                external_importance: null,
                suggested_importance: null,
                llm_run_id: null,
                effective_importance: 'sent',
                pending_reason: null,
              },
              summary: null,
              available_actions: [],
            },
          })
        }
        throw new Error(`Unexpected request: ${path}`)
      }),
    )

    render(<App />)

    expect(
      await screen.findByRole('heading', { level: 1, name: 'Compose Mail' }),
    ).toBeInTheDocument()
    expect(screen.getByLabelText('Body')).toHaveValue('Manual line')
    await user.click(screen.getByRole('button', { name: 'Auto body' }))
    expect(screen.getByLabelText('Auto body preview').textContent).toBe('Auto line')

    await user.click(screen.getByRole('button', { name: 'Send' }))

    expect(
      await screen.findByRole('heading', { level: 1, name: 'Combined' }),
    ).toBeInTheDocument()
    expect(sentPayload).toEqual(
      expect.objectContaining({
        body_text: 'Manual line\n\nAuto line',
      }),
    )
  })

  it('warns before sending when the body mentions attachments without files', async () => {
    const user = userEvent.setup()
    window.history.pushState({}, '', '/mail/compose')
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    let sendRequested = false
    vi.stubGlobal(
      'fetch',
      vi.fn((input: string | URL | Request) => {
        const path = input.toString()
        if (path === '/api/v1/auth/session') {
          return activeSessionResponse()
        }
        if (path === '/api/v1/mails/send') {
          sendRequested = true
          return apiResponse(500, {
            ok: false,
            error: { code: 'UNEXPECTED_SEND', message: 'Unexpected send.' },
          })
        }
        throw new Error(`Unexpected request: ${path}`)
      }),
    )

    render(<App />)

    expect(
      await screen.findByRole('heading', { level: 1, name: 'Compose Mail' }),
    ).toBeInTheDocument()
    await user.type(screen.getByLabelText('To'), 'receiver@example.com')
    await user.type(screen.getByLabelText('Body'), '資料を添付します。')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    expect(confirmSpy).toHaveBeenCalledWith(
      'This message mentions an attachment, but no files are attached. Send anyway?',
    )
    expect(sendRequested).toBe(false)
    confirmSpy.mockRestore()
  })

  it('does not warn when only the quoted auto body mentions attachments', async () => {
    const user = userEvent.setup()
    window.history.pushState(
      {},
      '',
      '/mail/compose?to=receiver%40example.com&subject=Quoted&manual_body=確認しました&auto_body=以前のメールで資料を添付しますと書かれていました',
    )
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    let sentPayload: Record<string, unknown> | null = null
    vi.stubGlobal(
      'fetch',
      vi.fn((input: string | URL | Request, init?: RequestInit) => {
        const path = input.toString()
        if (path === '/api/v1/auth/session') {
          return activeSessionResponse()
        }
        if (path === '/api/v1/mails/send') {
          sentPayload = JSON.parse(String(init?.body ?? '{}'))
          return apiResponse(200, {
            ok: true,
            data: {
              id: 'mail_send_quoted_attachment',
              status: 'scheduled_mock',
              to_addresses: ['receiver@example.com'],
              cc_addresses: [],
              bcc_addresses: [],
              subject: 'Quoted',
              body_text: '確認しました\n\n以前のメールで資料を添付しますと書かれていました',
              attachment_names: [],
              reply_to_message_id: null,
              sent_message_id: null,
              scheduled_at: null,
              created_at: '2026-05-25T10:00:00+09:00',
              updated_at: '2026-05-25T10:00:00+09:00',
              version: 1,
            },
          })
        }
        if (path === '/api/v1/mails/mail_send_quoted_attachment') {
          return apiResponse(200, {
            ok: true,
            data: {
              message: {
                id: 'mail_send_quoted_attachment',
                gmail_message_id: 'provisional:mail_send_quoted_attachment',
                gmail_thread_id: 'provisional_thread_mail_send_quoted_attachment',
                thread_id: 'provisional_thread_mail_send_quoted_attachment',
                received_at: '2026-05-25T10:01:00+09:00',
                received_date: '2026-05-25',
                subject: 'Quoted',
                from_address: 'caseclosed.me@example.local',
                from_name: 'CaseClosed',
                from_contact: null,
                sender_contact: null,
                sender_address: null,
                reply_to_address: null,
                to_addresses: ['receiver@example.com'],
                cc_addresses: [],
                bcc_addresses: [],
                to_recipients: [{ email_address: 'receiver@example.com', contact: null }],
                cc_recipients: [],
                bcc_recipients: [],
                message_id_header: null,
                in_reply_to_header: null,
                references_header: null,
                list_id: null,
                snippet: '確認しました',
                gmail_link: null,
                external_starred: false,
                gmail_labels: ['SENT'],
                body_text: '確認しました\n\n以前のメールで資料を添付しますと書かれていました',
                body_html: null,
                processed_status: 'processed',
                read_status: 'read',
                read_at: '2026-05-25T10:00:00+09:00',
                user_importance: null,
                effective_importance: 'sent',
                importance_rank: 7,
                external_importance: null,
                suggested_importance: null,
                llm_run_id: null,
                pending_reason: null,
                created_at: '2026-05-25T10:00:00+09:00',
                updated_at: '2026-05-25T10:00:00+09:00',
                version: 1,
              },
              thread_messages: [],
              scheduled_send_requests: [],
              user_state: {
                user_importance: null,
                processed_status: 'processed',
                processed_at: '2026-05-25T10:00:00+09:00',
                read_status: 'read',
                read_at: '2026-05-25T10:00:00+09:00',
                version: 1,
              },
              auto_state: {
                external_importance: null,
                suggested_importance: null,
                llm_run_id: null,
                effective_importance: 'sent',
                pending_reason: null,
              },
              summary: null,
              available_actions: [],
            },
          })
        }
        throw new Error(`Unexpected request: ${path}`)
      }),
    )

    render(<App />)

    expect(
      await screen.findByRole('heading', { level: 1, name: 'Compose Mail' }),
    ).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Send' }))

    expect(confirmSpy).not.toHaveBeenCalled()
    expect(sentPayload).toEqual(
      expect.objectContaining({
        body_text: '確認しました\n\n以前のメールで資料を添付しますと書かれていました',
      }),
    )
    confirmSpy.mockRestore()
  })

  it('ingests a mock mail and opens the detail view', async () => {
    const user = userEvent.setup()
    const originalScrollIntoView = Element.prototype.scrollIntoView
    const scrollIntoView = vi.fn()
    Element.prototype.scrollIntoView = scrollIntoView
    const createdMail = {
      id: 'mail_new',
      gmail_message_id: 'mock_created',
      gmail_thread_id: 'mock_thread_created',
      thread_id: 'thread_db',
      received_at: '2026-05-23T13:00:00+09:00',
      received_date: '2026-05-23',
      subject: 'Review mock mail',
      from_address: 'review.mock.sender@example.com',
      from_name: null,
      reply_to_address: null,
      list_id: null,
      processed_status: 'unprocessed',
      read_status: 'unread',
      read_at: null,
      user_importance: null,
      effective_importance: 'pending',
      importance_rank: 5,
      external_importance: null,
      suggested_importance: null,
      llm_run_id: null,
      pending_reason: 'unresolved_from_contact',
    }
    const createdMailDetail = {
      ...createdMail,
      thread_id: 'thread_db',
      from_name: null,
      sender_address: null,
      to_addresses: ['recipient.one@example.com', 'recipient.two@example.com'],
      cc_addresses: ['team@example.com'],
      bcc_addresses: [],
      to_recipients: [
        { email_address: 'recipient.one@example.com', contact: null },
        { email_address: 'recipient.two@example.com', contact: null },
      ],
      cc_recipients: [{ email_address: 'team@example.com', contact: null }],
      message_id_header: '<mock@test>',
      in_reply_to_header: null,
      references_header: null,
      snippet: null,
      gmail_link: 'https://mail.google.com/mail/u/0/#inbox/mock_created',
      external_starred: false,
      body_text: 'This is a mock mail for review. https://example.com/review',
      body_html: null,
      created_at: '2026-05-23T13:00:00+09:00',
      updated_at: '2026-05-23T13:00:00+09:00',
      version: 1,
    }
    const sentMailDetail = {
      ...createdMailDetail,
      id: 'mail_sent_new',
      gmail_message_id: 'mock_sent_created',
      received_at: '2026-05-23T13:10:00+09:00',
      received_date: '2026-05-23',
      from_address: 'caseclosed.me@example.local',
      to_addresses: ['review.mock.sender@example.com'],
      cc_addresses: ['team@example.com'],
      bcc_addresses: [],
      to_recipients: [
        {
          email_address: 'review.mock.sender@example.com',
          contact: null,
        },
      ],
      cc_recipients: [{ email_address: 'team@example.com', contact: null }],
      bcc_recipients: [],
      gmail_labels: ['SENT'],
      body_text: 'Sent body for resend.',
      processed_status: 'processed',
      read_status: 'read',
      read_at: '2026-05-23T13:10:00+09:00',
    }
    const scheduledSendRequest = {
      id: 'mail_send_scheduled',
      status: 'scheduled_mock',
      to_addresses: ['review.mock.sender@example.com'],
      cc_addresses: ['team@example.com'],
      bcc_addresses: [],
      subject: 'Review mock mail',
      body_text: 'Scheduled reply body.',
      attachment_names: [],
      reply_to_message_id: 'mail_new',
      sent_message_id: null,
      scheduled_at: '2026-05-23T13:30:00+09:00',
      created_at: '2026-05-23T13:05:00+09:00',
      updated_at: '2026-05-23T13:05:00+09:00',
      version: 1,
    }
    const ingested = true
    let processed = false
    let scheduledCanceled = false
    let summaryRequested = false
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = input.toString()
      if (path === '/api/v1/auth/session') {
        return activeSessionResponse()
      }
      if (path === '/api/v1/profile') {
        return apiResponse(200, {
          ok: true,
          data: {
            display_name: 'Kazumasa Horie',
            primary_email: 'recipient.two@example.com',
            email_aliases: ['team@example.com'],
            affiliation: '',
            academic_title: '',
            lab_or_group: '',
            research_fields: '',
            teaching_responsibilities: '',
            committee_roles: '',
            administrative_roles: '',
            supervised_people: '',
            collaborators: '',
            important_projects: '',
            priority_keywords: '',
            low_priority_keywords: '',
            important_senders_or_domains: '',
            expected_response_policy: '',
            unavailable_times: '',
            default_reply_language: 'japanese',
            llm_self_description: '',
            mail_importance_notes: '',
            updated_at: '2026-06-03T19:30:00+09:00',
          },
        })
      }
      if (path === '/api/v1/contacts/unresolved-from-addresses') {
        return apiResponse(200, { ok: true, data: { items: [] } })
      }
      if (path.startsWith('/api/v1/mails/dates') && init?.method === undefined) {
        return apiResponse(200, {
          ok: true,
          data: { items: ingested ? [{ date: '2026-05-23', count: 1 }] : [] },
        })
      }
      if (path.startsWith('/api/v1/mails?') && init?.method === undefined) {
        return apiResponse(200, {
          ok: true,
          data: { items: ingested ? [createdMail] : [], next_cursor: null, limit: 25 },
        })
      }
      if (path === '/api/v1/mails/mail_new') {
        return apiResponse(200, {
          ok: true,
          data: {
            message: {
              ...createdMailDetail,
              processed_status: processed ? 'processed' : 'unprocessed',
            },
            thread_messages: [
              sentMailDetail,
              {
                ...createdMailDetail,
                processed_status: processed ? 'processed' : 'unprocessed',
              },
            ],
            scheduled_send_requests: scheduledCanceled ? [] : [scheduledSendRequest],
            user_state: {
              user_importance: null,
              processed_status: processed ? 'processed' : 'unprocessed',
              processed_at: processed ? '2026-05-23T13:02:00+09:00' : null,
              read_status: 'unread',
              read_at: null,
              version: 1,
            },
            auto_state: {
              external_importance: null,
              suggested_importance: null,
              llm_run_id: null,
              effective_importance: 'pending',
              pending_reason: 'unresolved_from_contact',
            },
            summary: summaryRequested
              ? {
                  summary_text: 'Thread summary after manual request.',
                  items: [
                    {
                      id: 'summary_mail_new',
                      message_id: 'mail_new',
                      summary_text:
                        'Mail summary after manual request. https://example.com/summary',
                      action_required: true,
                      deadline_text: null,
                      next_action: 'Review it.',
                      key_points: ['Review requested'],
                      translation_text: 'メール要約後の和訳。https://example.com/translation',
                      language: 'ja',
                      llm_run_id: 'llm_run_summary',
                      updated_at: '2026-05-23T13:03:00+09:00',
                      version: 1,
                    },
                  ],
                }
              : null,
            available_actions: ['resolve_contact'],
          },
        })
      }
      if (path === '/api/v1/mails/mail_new/read' && init?.method === 'POST') {
        return apiResponse(200, {
          ok: true,
          data: {
            message: {
              ...createdMailDetail,
              processed_status: processed ? 'processed' : 'unprocessed',
              read_status: 'read',
              read_at: '2026-05-23T13:01:00+09:00',
            },
            thread_messages: [
              sentMailDetail,
              {
                ...createdMailDetail,
                processed_status: processed ? 'processed' : 'unprocessed',
                read_status: 'read',
                read_at: '2026-05-23T13:01:00+09:00',
              },
            ],
            scheduled_send_requests: scheduledCanceled ? [] : [scheduledSendRequest],
            user_state: {
              user_importance: null,
              processed_status: processed ? 'processed' : 'unprocessed',
              processed_at: processed ? '2026-05-23T13:02:00+09:00' : null,
              read_status: 'read',
              read_at: '2026-05-23T13:01:00+09:00',
              version: 2,
            },
            auto_state: {
              external_importance: null,
              suggested_importance: null,
              llm_run_id: null,
              effective_importance: 'pending',
              pending_reason: 'unresolved_from_contact',
            },
            summary: null,
            available_actions: ['resolve_contact'],
          },
        })
      }
      if (path === '/api/v1/mails/mail_new/summary' && init?.method === 'POST') {
        summaryRequested = true
        return apiResponse(200, {
          ok: true,
          data: { job_id: 'job_mail_summary_manual' },
        })
      }
      if (path === '/api/v1/mails/mail_new/process' && init?.method === 'POST') {
        processed = true
        return apiResponse(200, {
          ok: true,
          data: {
            message: {
              ...createdMailDetail,
              processed_status: 'processed',
              read_status: 'read',
              read_at: '2026-05-23T13:01:00+09:00',
            },
            thread_messages: [
              sentMailDetail,
              {
                ...createdMailDetail,
                processed_status: 'processed',
                read_status: 'read',
                read_at: '2026-05-23T13:01:00+09:00',
              },
            ],
            scheduled_send_requests: scheduledCanceled ? [] : [scheduledSendRequest],
            user_state: {
              user_importance: null,
              processed_status: 'processed',
              processed_at: '2026-05-23T13:02:00+09:00',
              read_status: 'read',
              read_at: '2026-05-23T13:01:00+09:00',
              version: 3,
            },
            auto_state: {
              external_importance: null,
              suggested_importance: null,
              llm_run_id: null,
              effective_importance: 'pending',
              pending_reason: 'unresolved_from_contact',
            },
            summary: summaryRequested
              ? {
                  summary_text: 'Thread summary after manual request.',
                  items: [
                    {
                      id: 'summary_mail_new',
                      message_id: 'mail_new',
                      summary_text:
                        'Mail summary after manual request. https://example.com/summary',
                      action_required: true,
                      deadline_text: null,
                      next_action: 'Review it.',
                      key_points: ['Review requested'],
                      translation_text: 'メール要約後の和訳。https://example.com/translation',
                      language: 'ja',
                      llm_run_id: 'llm_run_summary',
                      updated_at: '2026-05-23T13:03:00+09:00',
                      version: 1,
                    },
                  ],
                }
              : null,
            available_actions: ['resolve_contact'],
          },
        })
      }
      if (
        path === '/api/v1/mails/send-requests/mail_send_scheduled/send-now' &&
        init?.method === 'POST'
      ) {
        return apiResponse(200, {
          ok: true,
          data: {
            ...scheduledSendRequest,
            status: 'queued_mock',
            scheduled_at: null,
            updated_at: '2026-05-23T13:06:00+09:00',
            version: 2,
          },
        })
      }
      if (
        path === '/api/v1/mails/send-requests/mail_send_scheduled/schedule' &&
        init?.method === 'PATCH'
      ) {
        return apiResponse(200, {
          ok: true,
          data: {
            ...scheduledSendRequest,
            scheduled_at: '2026-05-23T14:00:00+09:00',
            updated_at: '2026-05-23T13:07:00+09:00',
            version: 2,
          },
        })
      }
      if (
        path === '/api/v1/mails/send-requests/mail_send_scheduled/cancel' &&
        init?.method === 'POST'
      ) {
        scheduledCanceled = true
        return apiResponse(200, {
          ok: true,
          data: {
            ...scheduledSendRequest,
            status: 'canceled',
            updated_at: '2026-05-23T13:08:00+09:00',
            version: 2,
          },
        })
      }

      throw new Error(`Unexpected request: ${path} ${init?.method ?? 'GET'}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    window.history.pushState({}, '', '/mail')

    render(<App />)

    expect(screen.queryByText('Debug tools')).not.toBeInTheDocument()
    expect(await screen.findByText('Review mock mail')).toBeInTheDocument()
    expect(screen.getByText('No case')).toBeInTheDocument()
    await user.click(screen.getByRole('link', { name: /Review mock mail/ }))

    expect(
      await screen.findByRole('heading', { level: 1, name: 'Review mock mail' }),
    ).toBeInTheDocument()
    await waitFor(() => {
      expect(scrollIntoView).toHaveBeenCalledWith({
        block: 'start',
        inline: 'nearest',
      })
    })
    scrollIntoView.mockClear()
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/mails/mail_new/read',
      expect.objectContaining({
        credentials: 'include',
        method: 'POST',
      }),
    )
    expect(screen.getByRole('link', { name: 'Mail' })).toHaveAttribute(
      'href',
      '/mail?tab=unprocessed&date=2026-05-23',
    )
    expect(screen.getByRole('link', { name: 'Open in Gmail' })).toHaveAttribute(
      'href',
      'https://mail.google.com/mail/u/0/#inbox/mock_created',
    )
    expect(screen.getByText(/This is a mock mail for review/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'https://example.com/review' })).toHaveAttribute(
      'href',
      'https://example.com/review',
    )
    expect(screen.getAllByText('Head').length).toBeGreaterThan(0)
    expect(screen.getAllByRole('heading', { name: 'Body' }).length).toBeGreaterThan(0)
    expect(screen.getByText('Scheduled send')).toBeInTheDocument()
    expect(screen.getByText('Scheduled reply body.')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Summary' }))
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/mails/mail_new/summary',
      expect.objectContaining({
        credentials: 'include',
        method: 'POST',
      }),
    )
    expect(await screen.findByText(/Mail summary after manual request/)).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: 'https://example.com/summary' }),
    ).toHaveAttribute('href', 'https://example.com/summary')
    expect(screen.queryByText(/メール要約後の和訳/)).not.toBeInTheDocument()
    expect(
      screen.queryByRole('link', { name: 'https://example.com/translatio...' }),
    ).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Cancel send' }))
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/mails/send-requests/mail_send_scheduled/cancel',
      expect.objectContaining({
        credentials: 'include',
        method: 'POST',
      }),
    )
    expect(await screen.findByText('Scheduled send canceled.')).toBeInTheDocument()
    expect(screen.queryByText('Scheduled reply body.')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Complete' }))
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/mails/mail_new/process',
      expect.objectContaining({
        credentials: 'include',
        method: 'POST',
      }),
    )
    await waitFor(
      () => {
        expect(`${window.location.pathname}${window.location.search}`).toBe(
          '/mail?tab=unprocessed&date=2026-05-23',
        )
      },
      { timeout: 2500 },
    )

    navigateTo('/mail/mail_new')
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Review mock mail' }),
    ).toBeInTheDocument()
    expect(scrollIntoView).not.toHaveBeenCalled()
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/profile',
        expect.objectContaining({ credentials: 'include' }),
      )
    })
    await user.click(screen.getByRole('button', { name: 'Reply' }))
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Compose Mail' }),
    ).toBeInTheDocument()
    expectRecipientToken('review.mock.sender@example.com')
    expectRecipientToken('recipient.one@example.com')
    expect(screen.getByLabelText('Subject')).toHaveValue('Review mock mail')
    expect(screen.getByLabelText('Body')).toHaveValue('')
    expect(screen.getByRole('button', { name: 'Auto body' })).toHaveAttribute(
      'aria-expanded',
      'false',
    )
    await user.click(screen.getByRole('button', { name: 'Auto body' }))
    expect(screen.getByLabelText('Auto body preview').textContent).toBe(
      'On 2026-05-23 13:00:00 JST, review.mock.sender@example.com wrote:\n> This is a mock mail for review. https://example.com/review',
    )

    navigateTo('/mail/mail_new')
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Review mock mail' }),
    ).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Resend' }))
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Compose Mail' }),
    ).toBeInTheDocument()
    expectRecipientToken('review.mock.sender@example.com')
    expectRecipientToken('team@example.com')
    expect(screen.getByLabelText('Subject')).toHaveValue('Review mock mail')
    expect(screen.getByLabelText('Body')).toHaveValue('Sent body for resend.')
    expect(screen.queryByRole('button', { name: 'Auto body' })).not.toBeInTheDocument()

    navigateTo('/mail/mail_new')
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Review mock mail' }),
    ).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Follow-up' }))
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Compose Mail' }),
    ).toBeInTheDocument()
    expectRecipientToken('review.mock.sender@example.com')
    expectRecipientToken('team@example.com')
    expect(screen.getByLabelText('Subject')).toHaveValue('Review mock mail')
    expect(screen.getByLabelText('Body')).toHaveValue('')
    await user.click(screen.getByRole('button', { name: 'Auto body' }))
    expect(screen.getByLabelText('Auto body preview').textContent).toBe(
      'On 2026-05-23 13:10:00 JST, I wrote:\n> Sent body for resend.',
    )

    window.history.pushState({}, '', '/')
    Element.prototype.scrollIntoView = originalScrollIntoView
  })

  it('returns to the originating date list when the same thread still has another incomplete day', async () => {
    const user = userEvent.setup()
    const baseMail = {
      id: 'mail_low',
      gmail_message_id: 'gmail_mail_low',
      gmail_thread_id: 'thread_mail_low',
      thread_id: 'thread_mail_low',
      received_at: '2026-05-24T09:00:00+09:00',
      received_date: '2026-05-24',
      subject: 'Low priority note',
      from_address: 'low.sender@example.com',
      from_name: null,
      sender_address: null,
      reply_to_address: null,
      list_id: null,
      processed_status: 'unprocessed',
      read_status: 'unread',
      read_at: null,
      user_importance: null,
      effective_importance: 'low',
      importance_rank: 3,
      external_importance: null,
      suggested_importance: null,
      llm_run_id: null,
      pending_reason: null,
      to_addresses: ['me@example.com'],
      cc_addresses: [],
      bcc_addresses: [],
      to_recipients: [{ email_address: 'me@example.com', contact: null }],
      cc_recipients: [],
      bcc_recipients: [],
      message_id_header: '<mail-low@test>',
      in_reply_to_header: null,
      references_header: null,
      snippet: null,
      gmail_link: 'https://mail.google.com/mail/u/0/#inbox/gmail_mail_low',
      external_starred: false,
      body_text: 'This is a low priority note.',
      body_html: null,
      gmail_labels: [],
      attachments: [],
      created_at: '2026-05-24T09:00:00+09:00',
      updated_at: '2026-05-24T09:00:00+09:00',
      version: 1,
    }
    const otherDateMail = {
      ...baseMail,
      id: 'mail_other_day',
      gmail_message_id: 'gmail_mail_other_day',
      received_at: '2026-05-23T09:00:00+09:00',
      received_date: '2026-05-23',
      subject: 'Earlier action note',
      effective_importance: 'high',
    }
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = input.toString()
      if (path === '/api/v1/auth/session') {
        return activeSessionResponse()
      }
      if (path === '/api/v1/contacts/unresolved-from-addresses') {
        return apiResponse(200, { ok: true, data: { items: [] } })
      }
      if (path === '/api/v1/profile') {
        return apiResponse(200, {
          ok: true,
          data: {
            display_name: '',
            primary_email: 'me@example.com',
            email_aliases: [],
            affiliation: '',
            academic_title: '',
            lab_or_group: '',
            research_fields: '',
            teaching_responsibilities: '',
            committee_roles: '',
            administrative_roles: '',
            supervised_people: '',
            collaborators: '',
            important_projects: '',
            priority_keywords: '',
            low_priority_keywords: '',
            important_senders_or_domains: '',
            expected_response_policy: '',
            unavailable_times: '',
            default_reply_language: 'japanese',
            llm_self_description: '',
            mail_importance_notes: '',
            updated_at: null,
          },
        })
      }
      if (path.startsWith('/api/v1/mails/dates') && init?.method === undefined) {
        return apiResponse(200, {
          ok: true,
          data: { items: [{ date: '2026-05-24', count: 0 }] },
        })
      }
      if (path.startsWith('/api/v1/mails?') && init?.method === undefined) {
        return apiResponse(200, {
          ok: true,
          data: { items: [], next_cursor: null, limit: 25 },
        })
      }
      if (path === '/api/v1/mails/mail_low') {
        return apiResponse(200, {
          ok: true,
          data: {
            message: baseMail,
            thread_messages: [otherDateMail, baseMail],
            scheduled_send_requests: [],
            user_state: {
              user_importance: null,
              processed_status: 'unprocessed',
              processed_at: null,
              read_status: 'unread',
              read_at: null,
              version: 1,
            },
            auto_state: {
              external_importance: null,
              suggested_importance: null,
              llm_run_id: null,
              effective_importance: 'low',
              pending_reason: null,
            },
            summary: null,
            available_actions: [],
          },
        })
      }
      if (path === '/api/v1/mails/mail_low/read' && init?.method === 'POST') {
        return apiResponse(200, {
          ok: true,
          data: {
            message: { ...baseMail, read_status: 'read' },
            thread_messages: [
              { ...otherDateMail, read_status: 'read' },
              { ...baseMail, read_status: 'read' },
            ],
            scheduled_send_requests: [],
            user_state: {
              user_importance: null,
              processed_status: 'unprocessed',
              processed_at: null,
              read_status: 'read',
              read_at: '2026-05-24T09:01:00+09:00',
              version: 2,
            },
            auto_state: {
              external_importance: null,
              suggested_importance: null,
              llm_run_id: null,
              effective_importance: 'low',
              pending_reason: null,
            },
            summary: null,
            available_actions: [],
          },
        })
      }
      if (path === '/api/v1/mails/mail_low/process' && init?.method === 'POST') {
        return apiResponse(200, {
          ok: true,
          data: {
            message: {
              ...baseMail,
              processed_status: 'processed',
              read_status: 'read',
            },
            thread_messages: [
              {
                ...otherDateMail,
                read_status: 'read',
              },
              {
                ...baseMail,
                processed_status: 'processed',
                read_status: 'read',
              },
            ],
            scheduled_send_requests: [],
            user_state: {
              user_importance: null,
              processed_status: 'processed',
              processed_at: '2026-05-24T09:02:00+09:00',
              read_status: 'read',
              read_at: '2026-05-24T09:01:00+09:00',
              version: 3,
            },
            auto_state: {
              external_importance: null,
              suggested_importance: null,
              llm_run_id: null,
              effective_importance: 'low',
              pending_reason: null,
            },
            summary: null,
            available_actions: [],
          },
        })
      }
      throw new Error(`Unexpected request: ${path} ${init?.method ?? 'GET'}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    window.history.pushState(
      {},
      '',
      '/mail/mail_low?return_to=%2Fmail%3Ftab%3Dunprocessed%26date%3D2026-05-24',
    )

    render(<App />)

    expect(
      await screen.findByRole('heading', { level: 1, name: 'Low priority note' }),
    ).toBeInTheDocument()
    await user.click(screen.getAllByRole('button', { name: 'Complete' })[0])
    fireEvent.pointerDown(window)

    await waitFor(
      () => {
        expect(`${window.location.pathname}${window.location.search}`).toBe(
          '/mail?tab=unprocessed&date=2026-05-24',
        )
      },
      { timeout: 2500 },
    )
  })

  it('cancels the pending return navigation when the completed mail is reopened', async () => {
    const user = userEvent.setup()
    const baseMail = {
      id: 'mail_reopen',
      gmail_message_id: 'gmail_mail_reopen',
      gmail_thread_id: 'thread_mail_reopen',
      thread_id: 'thread_mail_reopen',
      received_at: '2026-05-24T10:00:00+09:00',
      received_date: '2026-05-24',
      subject: 'Reopen check',
      from_address: 'reopen.sender@example.com',
      from_name: null,
      sender_address: null,
      reply_to_address: null,
      list_id: null,
      processed_status: 'unprocessed',
      read_status: 'read',
      read_at: '2026-05-24T10:01:00+09:00',
      user_importance: null,
      effective_importance: 'high',
      importance_rank: 1,
      external_importance: null,
      suggested_importance: null,
      llm_run_id: null,
      pending_reason: null,
      to_addresses: ['me@example.com'],
      cc_addresses: [],
      bcc_addresses: [],
      to_recipients: [{ email_address: 'me@example.com', contact: null }],
      cc_recipients: [],
      bcc_recipients: [],
      message_id_header: '<mail-reopen@test>',
      in_reply_to_header: null,
      references_header: null,
      snippet: null,
      gmail_link: 'https://mail.google.com/mail/u/0/#inbox/gmail_mail_reopen',
      external_starred: false,
      body_text: 'This mail checks reopen navigation.',
      body_html: null,
      gmail_labels: [],
      attachments: [],
      created_at: '2026-05-24T10:00:00+09:00',
      updated_at: '2026-05-24T10:00:00+09:00',
      version: 1,
    }
    let processed = false
    const detailResponse = () => ({
      ok: true,
      data: {
        message: {
          ...baseMail,
          processed_status: processed ? 'processed' : 'unprocessed',
        },
        thread_messages: [
          {
            ...baseMail,
            processed_status: processed ? 'processed' : 'unprocessed',
          },
        ],
        scheduled_send_requests: [],
        user_state: {
          user_importance: null,
          processed_status: processed ? 'processed' : 'unprocessed',
          processed_at: processed ? '2026-05-24T10:02:00+09:00' : null,
          read_status: 'read',
          read_at: '2026-05-24T10:01:00+09:00',
          version: processed ? 2 : 1,
        },
        auto_state: {
          external_importance: null,
          suggested_importance: null,
          llm_run_id: null,
          effective_importance: 'high',
          pending_reason: null,
        },
        summary: null,
        available_actions: [],
      },
    })
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = input.toString()
      if (path === '/api/v1/auth/session') {
        return activeSessionResponse()
      }
      if (path === '/api/v1/contacts/unresolved-from-addresses') {
        return apiResponse(200, { ok: true, data: { items: [] } })
      }
      if (path === '/api/v1/profile') {
        return apiResponse(200, {
          ok: true,
          data: {
            display_name: '',
            primary_email: 'me@example.com',
            email_aliases: [],
            affiliation: '',
            academic_title: '',
            lab_or_group: '',
            research_fields: '',
            teaching_responsibilities: '',
            committee_roles: '',
            administrative_roles: '',
            supervised_people: '',
            collaborators: '',
            important_projects: '',
            priority_keywords: '',
            low_priority_keywords: '',
            important_senders_or_domains: '',
            expected_response_policy: '',
            unavailable_times: '',
            default_reply_language: 'japanese',
            llm_self_description: '',
            mail_importance_notes: '',
            updated_at: null,
          },
        })
      }
      if (path === '/api/v1/mails/mail_reopen') {
        return apiResponse(200, detailResponse())
      }
      if (path === '/api/v1/mails/mail_reopen/process' && init?.method === 'POST') {
        processed = true
        return apiResponse(200, detailResponse())
      }
      if (path === '/api/v1/mails/mail_reopen/unprocess' && init?.method === 'POST') {
        processed = false
        return apiResponse(200, detailResponse())
      }
      throw new Error(`Unexpected request: ${path} ${init?.method ?? 'GET'}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    window.history.pushState(
      {},
      '',
      '/mail/mail_reopen?return_to=%2Fmail%3Ftab%3Dunprocessed%26date%3D2026-05-24',
    )

    render(<App />)

    expect(
      await screen.findByRole('heading', { level: 1, name: 'Reopen check' }),
    ).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Complete' }))
    expect(await screen.findByRole('button', { name: 'Reopen' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Reopen' }))

    await new Promise((resolve) => window.setTimeout(resolve, 1600))
    expect(`${window.location.pathname}${window.location.search}`).toBe(
      '/mail/mail_reopen?return_to=%2Fmail%3Ftab%3Dunprocessed%26date%3D2026-05-24',
    )
  })

  it('collapses Japanese Gmail quoted reply sections in sent mail bodies', async () => {
    const sentBody = [
      '下記確認しました。',
      '1時半ごろにこちらからお電話する形でよろしいですか？',
      '',
      'よろしくお願い申し上げます。',
      '',
      '堀江',
      '',
      '2026年5月28日(木) 10:27 SHUYAN HAN <yuimachineheart@gmail.com>:',
      '堀江さん',
      '',
      '下記よろしくお願いします．',
      '',
      '> -----Original Message-----',
      '> From: horie@bipl-sdnn.org <horie@bipl-sdnn.org>',
    ].join('\n')
    const sentMail = {
      id: 'mail_sent_japanese_quote',
      gmail_message_id: 'gmail_sent_japanese_quote',
      gmail_thread_id: 'thread_japanese_quote',
      thread_id: 'thread_japanese_quote',
      received_at: '2026-05-28T12:45:00+09:00',
      received_date: '2026-05-28',
      subject: 'Japanese quote',
      from_address: 'me@example.com',
      from_name: 'Me',
      sender_address: null,
      reply_to_address: null,
      list_id: null,
      processed_status: 'processed',
      read_status: 'read',
      read_at: '2026-05-28T12:45:00+09:00',
      user_importance: null,
      effective_importance: 'sent',
      importance_rank: 6,
      external_importance: null,
      suggested_importance: null,
      llm_run_id: null,
      pending_reason: null,
      to_addresses: ['kitagawa@cs.tsukuba.ac.jp'],
      cc_addresses: [],
      bcc_addresses: [],
      message_id_header: '<sent-japanese-quote@example.com>',
      in_reply_to_header: '<source@example.com>',
      references_header: null,
      snippet: null,
      gmail_link: null,
      external_starred: false,
      gmail_labels: ['SENT'],
      body_text: sentBody,
      body_html: `<div>${sentBody.replaceAll('\n', '<br>')}</div>`,
      created_at: '2026-05-28T12:45:00+09:00',
      updated_at: '2026-05-28T12:45:00+09:00',
      version: 1,
    }
    const detailPayload = {
      message: sentMail,
      thread_messages: [sentMail],
      scheduled_send_requests: [],
      user_state: {
        user_importance: null,
        processed_status: 'processed',
        processed_at: '2026-05-28T12:45:00+09:00',
        read_status: 'read',
        read_at: '2026-05-28T12:45:00+09:00',
        version: 1,
      },
      auto_state: {
        external_importance: null,
        suggested_importance: null,
        llm_run_id: null,
        effective_importance: 'sent',
        pending_reason: null,
      },
      summary: null,
      available_actions: [],
    }
    vi.stubGlobal(
      'fetch',
      vi.fn((input: string | URL | Request, init?: RequestInit) => {
        const path = input.toString()
        if (path === '/api/v1/auth/session') {
          return activeSessionResponse()
        }
        if (path === '/api/v1/mails/mail_sent_japanese_quote') {
          return apiResponse(200, { ok: true, data: detailPayload })
        }
        if (path === '/api/v1/mails/mail_sent_japanese_quote/read' && init?.method === 'POST') {
          return apiResponse(200, { ok: true, data: detailPayload })
        }
        throw new Error(`Unexpected request: ${path} ${init?.method ?? 'GET'}`)
      }),
    )
    window.history.pushState({}, '', '/mail/mail_sent_japanese_quote')

    render(<App />)

    expect(await screen.findByText(/1時半ごろにこちらから/)).toBeInTheDocument()
    const quotedSummary = screen.getByText('Quoted reply')
    expect(quotedSummary.closest('details')).not.toHaveAttribute('open')
    await userEvent.click(quotedSummary)
    expect(quotedSummary.closest('details')).toHaveAttribute('open')
    expect(await screen.findByText(/堀江さん/)).toBeInTheDocument()
  })

  it('renders newsletter HTML when the plain text part uses markdown links', async () => {
    const newsletterMail = {
      id: 'mail_ieee_newsletter',
      gmail_message_id: 'gmail_ieee_newsletter',
      gmail_thread_id: 'thread_ieee_newsletter',
      thread_id: 'thread_ieee_newsletter',
      received_at: '2026-05-30T08:00:00+09:00',
      received_date: '2026-05-30',
      subject: 'Get Published in the New IEEE Open Journal of Engineering in Medicine and Biology',
      from_address: 'ieee@example.com',
      from_name: 'IEEE',
      sender_address: null,
      reply_to_address: null,
      list_id: null,
      processed_status: 'unprocessed',
      read_status: 'unread',
      read_at: null,
      user_importance: null,
      effective_importance: 'middle',
      importance_rank: 2,
      external_importance: null,
      suggested_importance: null,
      llm_run_id: null,
      pending_reason: null,
      to_addresses: ['me@example.com'],
      cc_addresses: [],
      bcc_addresses: [],
      message_id_header: '<ieee-newsletter@example.com>',
      in_reply_to_header: null,
      references_header: null,
      snippet: 'Highlights of April 2026',
      gmail_link: null,
      external_starred: false,
      gmail_labels: ['INBOX'],
      body_text: [
        'To view this email as a webpage, [click here](https://example.com/view).',
        '',
        'Highlights of April 2026',
        '',
        '[Stain Consistency Learning: Handling Stain Variation for Automatic Digital Pathology Segmentation](https://example.com/paper)',
        '',
        'Author resources and submission guidance are available now.',
        '',
        'Submit your work to the open journal.',
      ].join('\n'),
      body_html: [
        '<!doctype html><html><body>',
        '<p>To view this email as a webpage, <a href="https://example.com/view">click here</a>.</p>',
        '<h1>Highlights of April 2026</h1>',
        '<a href="https://example.com/paper">Stain Consistency Learning: Handling Stain Variation for Automatic Digital Pathology Segmentation</a>',
        '<p>Author resources and submission guidance are available now.</p>',
        '<p>Submit your work to the open journal.</p>',
        '</body></html>',
      ].join(''),
      created_at: '2026-05-30T08:00:00+09:00',
      updated_at: '2026-05-30T08:00:00+09:00',
      version: 1,
    }
    const detailPayload = {
      message: newsletterMail,
      thread_messages: [newsletterMail],
      scheduled_send_requests: [],
      user_state: {
        user_importance: null,
        processed_status: 'unprocessed',
        processed_at: null,
        read_status: 'unread',
        read_at: null,
        version: 1,
      },
      auto_state: {
        external_importance: null,
        suggested_importance: null,
        llm_run_id: null,
        effective_importance: 'middle',
        pending_reason: null,
      },
      summary: null,
      available_actions: [],
    }
    vi.stubGlobal(
      'fetch',
      vi.fn((input: string | URL | Request, init?: RequestInit) => {
        const path = input.toString()
        if (path === '/api/v1/auth/session') {
          return activeSessionResponse()
        }
        if (path === '/api/v1/mails/mail_ieee_newsletter') {
          return apiResponse(200, { ok: true, data: detailPayload })
        }
        if (path === '/api/v1/mails/mail_ieee_newsletter/read' && init?.method === 'POST') {
          return apiResponse(200, { ok: true, data: detailPayload })
        }
        throw new Error(`Unexpected request: ${path} ${init?.method ?? 'GET'}`)
      }),
    )
    window.history.pushState({}, '', '/mail/mail_ieee_newsletter')

    render(<App />)

    expect(
      await screen.findByTitle('HTML mail body'),
    ).toHaveClass('mail-thread-html-body')
    expect(
      screen.queryByText(/\[click here\]\(https:\/\/example\.com\/view\)/),
    ).not.toBeInTheDocument()
  })

  it('renders markdown table mail bodies as tables without using heading-only markdown detection', async () => {
    const joblistMail = {
      id: 'mail_joblist_markdown',
      gmail_message_id: 'gmail_joblist_markdown',
      gmail_thread_id: 'thread_joblist_markdown',
      thread_id: 'thread_joblist_markdown',
      received_at: '2026-05-29T08:00:00+09:00',
      received_date: '2026-05-29',
      subject: '[Joblist] @kdesleep-code - 2026-05-29 JST',
      from_address: 'joblist@example.com',
      from_name: 'Joblist',
      sender_address: null,
      reply_to_address: null,
      list_id: null,
      processed_status: 'unprocessed',
      read_status: 'unread',
      read_at: null,
      user_importance: null,
      effective_importance: 'middle',
      importance_rank: 2,
      external_importance: null,
      suggested_importance: null,
      llm_run_id: null,
      pending_reason: null,
      to_addresses: ['me@example.com'],
      cc_addresses: [],
      bcc_addresses: [],
      message_id_header: '<joblist@example.com>',
      in_reply_to_header: null,
      references_header: null,
      snippet: 'Joblist',
      gmail_link: null,
      external_starred: false,
      gmail_labels: ['INBOX'],
      body_text: [
        '@kdesleep-code さんの Joblist（2026-05-29 JST 自動生成）',
        '',
        '# Joblist for @kdesleep-code',
        '_Generated: 2026-05-29 JST_',
        '',
        '| # | Title | Due | Link |',
        '|---|-------|-----|------|',
        '| 59 | [To-do] 居室の掃除 | 2025-06-15 | [link](https://github.com/KDE-Sleep/To-do/issues/59) |',
        '| 6 | [To-do] いい加減にEnsembleの論文を書く | 2025-10-14 | [link](https://github.com/KDE-Sleep/To-do/issues/6) |',
        '',
        '> 期日は Issue フォームの「期日 / Due Date」に YYYY-MM-DD で入力してください。',
      ].join('\n'),
      body_html: '<html><body><p>Server generated HTML exists.</p></body></html>',
      created_at: '2026-05-29T08:00:00+09:00',
      updated_at: '2026-05-29T08:00:00+09:00',
      version: 1,
    }
    const detailPayload = {
      message: joblistMail,
      thread_messages: [joblistMail],
      scheduled_send_requests: [],
      user_state: {
        user_importance: null,
        processed_status: 'unprocessed',
        processed_at: null,
        read_status: 'unread',
        read_at: null,
        version: 1,
      },
      auto_state: {
        external_importance: null,
        suggested_importance: null,
        llm_run_id: null,
        effective_importance: 'middle',
        pending_reason: null,
      },
      summary: null,
      available_actions: [],
    }
    vi.stubGlobal(
      'fetch',
      vi.fn((input: string | URL | Request, init?: RequestInit) => {
        const path = input.toString()
        if (path === '/api/v1/auth/session') {
          return activeSessionResponse()
        }
        if (path === '/api/v1/mails/mail_joblist_markdown') {
          return apiResponse(200, { ok: true, data: detailPayload })
        }
        if (path === '/api/v1/mails/mail_joblist_markdown/read' && init?.method === 'POST') {
          return apiResponse(200, { ok: true, data: detailPayload })
        }
        throw new Error(`Unexpected request: ${path} ${init?.method ?? 'GET'}`)
      }),
    )
    window.history.pushState({}, '', '/mail/mail_joblist_markdown')

    render(<App />)

    expect(await screen.findByRole('table')).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Title' })).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: '[To-do] 居室の掃除' })).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: 'link' })[0]).toHaveAttribute(
      'href',
      'https://github.com/KDE-Sleep/To-do/issues/59',
    )
    expect(screen.queryByTitle('HTML mail body')).not.toBeInTheDocument()
  })

  it('blocks the mail list when pending contacts remain', async () => {
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const path = input.toString()
      if (path === '/api/v1/auth/session') {
        return activeSessionResponse()
      }
      if (path === '/api/v1/contacts/unresolved-from-addresses') {
        return apiResponse(200, {
          ok: true,
          data: {
            items: [
              {
                email_address_id: 'email_pending',
                email_address: 'pending@example.com',
                normalized_email_address: 'pending@example.com',
                message_count: 1,
                latest_message_id: 'mail_pending',
                latest_subject: 'Pending mail',
                suggestion_status: 'not_started',
                suggestion: null,
              },
            ],
          },
        })
      }
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    window.history.pushState({}, '', '/mail')

    render(<App />)

    expect(
      await screen.findByRole('heading', {
        name: 'Pending contacts must be resolved first',
      }),
    ).toBeInTheDocument()
    expect(screen.getByText('Pending contacts: 1')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open Pending Contacts' })).toHaveAttribute(
      'href',
      '/contacts/pending',
    )
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringMatching(/^\/api\/v1\/mails/),
      expect.anything(),
    )

    window.history.pushState({}, '', '/')
  })
})

describe('Phase 2 maintenance screen', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/maintenance')
  })

  it('shows jobs and external operations that need maintenance attention', async () => {
    const user = userEvent.setup()
    vi.stubGlobal(
      'fetch',
      vi.fn((input: string | URL | Request) => {
        const path = input.toString()
        if (path === '/api/v1/auth/session') {
          return activeSessionResponse()
        }
        if (path === '/api/v1/maintenance/status') {
          return apiResponse(200, {
            ok: true,
            data: {
              job_accepting: true,
              running_jobs: 1,
              pending_write_requests: 2,
              external_unknown_count: 1,
              backup_status: 'not_configured',
            },
          })
        }
        if (path === '/api/v1/jobs') {
          return apiResponse(200, {
            ok: true,
            data: {
              items: [
                {
                  id: 'job_failed',
                  job_type: 'gmail_sync',
                  priority: 10,
                  status: 'failed',
                  retry_count: 1,
                  max_retries: 3,
                  error_type: 'ReviewFailure',
                  error_message: 'Review sample failure.',
                  created_at: '2026-05-23T09:00:00+09:00',
                  updated_at: '2026-05-23T09:02:00+09:00',
                  related_mail: {
                    context_type: 'message',
                    message_id: 'mail_failed_source',
                    thread_id: 'thread_failed_source',
                    gmail_message_id: 'gmail_failed_source',
                    gmail_thread_id: 'gmail_thread_failed_source',
                    subject: 'Failed summary source',
                    received_at: '2026-05-23T08:55:00+09:00',
                    from_address: 'sender@example.com',
                    mail_url: '/mail/mail_failed_source',
                  },
                },
                {
                  id: 'job_succeeded',
                  job_type: 'mail_import',
                  priority: 1,
                  status: 'succeeded',
                  retry_count: 0,
                  max_retries: 3,
                  error_type: null,
                  error_message: null,
                  created_at: '2026-05-23T09:00:00+09:00',
                  updated_at: '2026-05-23T09:02:00+09:00',
                  related_mail: null,
                },
              ],
            },
          })
        }
        if (path === '/api/v1/external-operations') {
          return apiResponse(200, {
            ok: true,
            data: {
              items: [
                {
                  id: 'op_unknown',
                  operation_type: 'gmail_send',
                  status: 'unknown',
                  external_service: 'gmail',
                  external_id: null,
                  manual_resolution_required: true,
                  unknown_reason: 'Network response was lost.',
                  created_at: '2026-05-23T09:03:00+09:00',
                  updated_at: '2026-05-23T09:04:00+09:00',
                },
              ],
            },
          })
        }
        if (path === '/api/v1/mails?tab=pending&limit=50') {
          return apiResponse(200, {
            ok: true,
            data: {
              items: [
                {
                  id: 'mail_pending_review',
                  received_at: '2026-05-24T09:00:00+09:00',
                  subject: 'Pending review: normal person',
                  from_address: 'pending.review@example.com',
                  pending_reason: 'unresolved_from_contact',
                },
              ],
            },
          })
        }

        throw new Error(`Unexpected request: ${path}`)
      }),
    )

    render(<App />)

    expect(
      await screen.findByRole('heading', { name: 'Maintenance' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Usage' })).toBeInTheDocument()
    expect(
      screen.getByRole('tab', { name: /Needs Action/ }),
    ).toHaveAttribute('aria-selected', 'false')
    expect(screen.getByRole('tab', { name: 'Usage' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(
      await screen.findByRole('button', { name: /Running jobs 1/ }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /Pending write requests 2/ }),
    ).toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: /Needs Action/ }))
    expect(await screen.findByLabelText('2 actions required')).toHaveTextContent('2')
    expect(await screen.findByRole('row', { name: /job_failed/ })).toHaveTextContent(
      'gmail_sync',
    )
    expect(screen.queryByRole('row', { name: /job_succeeded/ })).not.toBeInTheDocument()
    expect(
      screen.getByText(
        'The job failed. Reason: ReviewFailure - Review sample failure.',
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('link', {
        name: /Related mail: 2026-05-23T08:55:00\+09:00 \/ sender@example.com \/ Failed summary source/,
      }),
    ).toHaveAttribute('href', '/mail/mail_failed_source')
    expect(screen.getByRole('button', { name: 'Retry job_failed' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry job_failed' })).toHaveAttribute(
      'title',
      'Move this failed job back to pending so a worker can run it again.',
    )
    expect(await screen.findByRole('row', { name: /op_unknown/ })).toHaveTextContent(
      'gmail_send',
    )
    expect(
      screen.getByText(
        'The external operation result could not be confirmed automatically. Reason: Network response was lost.',
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Mark op_unknown succeeded' }),
    ).toHaveAttribute(
      'title',
      'Record that the external service operation succeeded. This does not run it again.',
    )
    expect(
      screen.getByRole('button', { name: 'Mark op_unknown failed' }),
    ).toHaveAttribute(
      'title',
      'Record that manual confirmation found this external operation failed.',
    )
    expect(screen.getByRole('button', { name: 'Cancel op_unknown' })).toHaveAttribute(
      'title',
      'Record that this external operation should be treated as canceled after manual confirmation.',
    )
    expect(
      await screen.findByRole('row', { name: /mail_pending_review/ }),
    ).toHaveTextContent('Pending review: normal person')
    expect(
      screen.getByText(
        'This mail still has an unresolved sender. Resolve or create the contact from Pending Contacts.',
      ),
    ).toBeInTheDocument()
  })

  it('retries failed jobs and resolves unknown external operations', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = input.toString()
      if (path === '/api/v1/auth/session') {
        return activeSessionResponse()
      }
      if (path === '/api/v1/maintenance/status') {
        return apiResponse(200, {
          ok: true,
          data: {
            job_accepting: true,
            running_jobs: 0,
            pending_write_requests: 0,
            external_unknown_count: 1,
            backup_status: 'not_configured',
          },
        })
      }
      if (path === '/api/v1/jobs' || path === '/api/v1/jobs/job_failed/retry') {
        return apiResponse(200, {
          ok: true,
          data:
            path === '/api/v1/jobs'
              ? {
                  items: [
                    {
                      id: 'job_failed',
                      job_type: 'gmail_sync',
                      priority: 10,
                      status: 'failed',
                      retry_count: 1,
                      max_retries: 3,
                      created_at: '2026-05-23T09:00:00+09:00',
                      updated_at: '2026-05-23T09:02:00+09:00',
                      related_mail: null,
                    },
                  ],
                }
              : {
                  id: 'job_failed',
                  job_type: 'gmail_sync',
                  priority: 10,
                  status: 'pending',
                  retry_count: 2,
                  max_retries: 3,
                  created_at: '2026-05-23T09:00:00+09:00',
                  updated_at: '2026-05-23T09:05:00+09:00',
                  related_mail: null,
                },
        })
      }
      if (
        path === '/api/v1/external-operations' ||
        path === '/api/v1/external-operations/op_unknown/resolve'
      ) {
        return apiResponse(200, {
          ok: true,
          data:
            path === '/api/v1/external-operations'
              ? {
                  items: [
                    {
                      id: 'op_unknown',
                      operation_type: 'gmail_send',
                      status: 'unknown',
                      external_service: 'gmail',
                      external_id: null,
                      manual_resolution_required: true,
                      created_at: '2026-05-23T09:03:00+09:00',
                      updated_at: '2026-05-23T09:04:00+09:00',
                    },
                  ],
                }
              : {
                  id: 'op_unknown',
                  operation_type: 'gmail_send',
                  status: 'succeeded',
                  external_service: 'gmail',
                  external_id: null,
                  manual_resolution_required: false,
                  created_at: '2026-05-23T09:03:00+09:00',
                  updated_at: '2026-05-23T09:06:00+09:00',
                },
        })
      }
      if (path === '/api/v1/mails?tab=pending&limit=50') {
        return apiResponse(200, { ok: true, data: { items: [] } })
      }

      throw new Error(`Unexpected request: ${path} ${init?.method ?? 'GET'}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    await user.click(
      await screen.findByRole('tab', { name: /Needs Action/ }),
    )
    await user.click(await screen.findByRole('button', { name: 'Retry job_failed' }))
    await user.click(
      screen.getByRole('button', { name: 'Mark op_unknown succeeded' }),
    )

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/jobs/job_failed/retry',
      expect.objectContaining({ credentials: 'include', method: 'POST' }),
    )
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/external-operations/op_unknown/resolve',
      expect.objectContaining({
        credentials: 'include',
        method: 'POST',
        body: JSON.stringify({ resolution: 'mark_succeeded' }),
      }),
    )
    expect(screen.queryByRole('row', { name: /job_failed/ })).not.toBeInTheDocument()
    expect(screen.getByText('No jobs requiring action.')).toBeInTheDocument()
    expect(screen.getByRole('row', { name: /op_unknown/ })).toHaveTextContent(
      'succeeded',
    )
  })

  it('opens the Usage maintenance tab without the recovery tables', async () => {
    const user = userEvent.setup()
    vi.stubGlobal(
      'fetch',
      vi.fn((input: string | URL | Request) => {
        const path = input.toString()
        if (path === '/api/v1/auth/session') {
          return activeSessionResponse()
        }
        if (path === '/api/v1/maintenance/status') {
          return apiResponse(200, {
            ok: true,
            data: {
              job_accepting: true,
              running_jobs: 0,
              pending_write_requests: 0,
              external_unknown_count: 0,
              backup_status: 'not_configured',
            },
          })
        }
        if (path === '/api/v1/jobs') {
          return apiResponse(200, { ok: true, data: { items: [] } })
        }
        if (path === '/api/v1/external-operations') {
          return apiResponse(200, { ok: true, data: { items: [] } })
        }
        if (path === '/api/v1/mails?tab=pending&limit=50') {
          return apiResponse(200, { ok: true, data: { items: [] } })
        }

        throw new Error(`Unexpected request: ${path}`)
      }),
    )

    render(<App />)
    await user.click(await screen.findByRole('tab', { name: 'Usage' }))

    expect(screen.getByRole('heading', { name: 'Usage' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Database/ })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(screen.getByRole('button', { name: /Storage/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /LLM cost/ })).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /Not available/ })).toHaveLength(6)
    expect(screen.getByRole('button', { name: /Running jobs 0/ })).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /Pending write requests 0/ }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /External unknown 0/ }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('heading', { name: 'Database history' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'History range' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '24h' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(screen.getByText('24h ago')).toBeInTheDocument()
    expect(screen.getByText('Now')).toBeInTheDocument()
    expect(screen.getByLabelText('History value scale')).toHaveTextContent('High')
    expect(screen.getByLabelText('History value scale')).toHaveTextContent('0')
    expect(screen.getByText('No history yet.')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /Storage/ }))
    await user.click(screen.getByRole('button', { name: '7d' }))

    expect(screen.getByRole('button', { name: /Storage/ })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(screen.getByRole('button', { name: '7d' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(
      screen.getByRole('heading', { name: 'Storage history' }),
    ).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Running jobs 0/ }))
    expect(
      screen.getByRole('heading', { name: 'Running jobs history' }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Jobs' })).not.toBeInTheDocument()
    expect(
      screen.queryByRole('heading', { name: 'External Confirmations' }),
    ).not.toBeInTheDocument()
  })

  it('shows send request logs in the Logs page', async () => {
    window.history.pushState({}, '', '/logs')
    vi.stubGlobal(
      'fetch',
      vi.fn((input: string | URL | Request) => {
        const path = input.toString()
        if (path === '/api/v1/auth/session') {
          return activeSessionResponse()
        }
        if (path === '/api/v1/contacts/unresolved-from-addresses') {
          return apiResponse(200, { ok: true, data: { items: [] } })
        }
        if (path.startsWith('/api/v1/logs?')) {
          return apiResponse(200, {
            ok: true,
            data: {
              page: 1,
              page_size: 100,
              total: 2,
              total_pages: 1,
              types: [
                { type: 'audit', count: 0 },
                { type: 'system', count: 0 },
                { type: 'auth', count: 0 },
                { type: 'job', count: 0 },
                { type: 'write', count: 0 },
                { type: 'external', count: 0 },
                { type: 'storage', count: 0 },
                { type: 'llm', count: 0 },
                { type: 'mail_send', count: 1 },
              ],
              items: [
                {
                  id: 'mail_send_review',
                  source_type: 'mail_send',
                  occurred_at: '2026-05-25T02:30:00+09:00',
                  level: 'warning',
                  category: 'mail_send_request',
                  summary: 'Review send request scheduled_mock',
                  detail: 'Hello.',
                  status: 'scheduled_mock',
                  target_type: 'mail_send_request',
                  target_id: 'mail_send_review',
                  metadata: {
                    to: ['review@example.com'],
                    cc: ['team@example.com'],
                    reply_to_message_id: 'mail_reply_source',
                  },
                },
                {
                  id: 'llm_review',
                  source_type: 'llm',
                  updated_at: '2026-05-25T02:30:00+09:00',
                  occurred_at: '2026-05-25T02:29:00+09:00',
                  level: 'info',
                  category: 'mail_summary',
                  summary: 'mail_summary mock succeeded',
                  detail: null,
                  status: 'succeeded',
                  target_type: 'llm_run',
                  target_id: 'llm_review',
                  metadata: null,
                },
              ],
            },
          })
        }
        throw new Error(`Unexpected request: ${path}`)
      }),
    )

    render(<App />)

    expect(await screen.findByRole('heading', { name: 'Logs' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Filters' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Export CSV' })).toHaveAttribute(
      'href',
      expect.stringContaining('/api/v1/logs/export'),
    )
    expect(await screen.findByRole('row', { name: /mail_send_review/ })).toHaveTextContent(
      'Review send request',
    )
    expect(screen.getByRole('row', { name: /mail_send_review/ })).toHaveTextContent(
      'scheduled_mock',
    )
    expect(screen.getByText('Page 1 / 1, 2 log(s)')).toBeInTheDocument()
  })

  it('caps the Jobs and Operations action badge at 9+', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: string | URL | Request) => {
        const path = input.toString()
        if (path === '/api/v1/auth/session') {
          return activeSessionResponse()
        }
        if (path === '/api/v1/maintenance/status') {
          return apiResponse(200, {
            ok: true,
            data: {
              job_accepting: true,
              running_jobs: 0,
              pending_write_requests: 0,
              external_unknown_count: 4,
              backup_status: 'not_configured',
            },
          })
        }
        if (path === '/api/v1/jobs') {
          return apiResponse(200, {
            ok: true,
            data: {
              items: Array.from({ length: 6 }, (_, index) => ({
                id: `job_failed_${index}`,
                job_type: 'gmail_sync',
                priority: 10,
                status: 'failed',
                retry_count: 1,
                max_retries: 3,
                created_at: '2026-05-23T09:00:00+09:00',
                updated_at: '2026-05-23T09:02:00+09:00',
                related_mail: null,
              })),
            },
          })
        }
        if (path === '/api/v1/external-operations') {
          return apiResponse(200, {
            ok: true,
            data: {
              items: Array.from({ length: 4 }, (_, index) => ({
                id: `op_unknown_${index}`,
                operation_type: 'gmail_send',
                status: 'unknown',
                external_service: 'gmail',
                external_id: null,
                manual_resolution_required: true,
                created_at: '2026-05-23T09:03:00+09:00',
                updated_at: '2026-05-23T09:04:00+09:00',
              })),
            },
          })
        }
        if (path === '/api/v1/mails?tab=pending&limit=50') {
          return apiResponse(200, { ok: true, data: { items: [] } })
        }

        throw new Error(`Unexpected request: ${path}`)
      }),
    )

    render(<App />)

    expect(await screen.findByLabelText('10 actions required')).toHaveTextContent(
      '9+',
    )
  })

  it('shows a stable error when a Phase 2 endpoint is unavailable', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: string | URL | Request) => {
        const path = input.toString()
        if (path === '/api/v1/auth/session') {
          return activeSessionResponse()
        }
        if (path === '/api/v1/maintenance/status') {
          return apiResponse(200, {
            ok: true,
            data: {
              job_accepting: true,
              running_jobs: 0,
              pending_write_requests: 0,
              external_unknown_count: 0,
              backup_status: 'not_configured',
            },
          })
        }
        if (path === '/api/v1/jobs') {
          return apiResponse(404, { detail: 'Not Found' })
        }
        if (path === '/api/v1/external-operations') {
          return apiResponse(200, { ok: true, data: { items: [] } })
        }
        if (path === '/api/v1/mails?tab=pending&limit=50') {
          return apiResponse(200, { ok: true, data: { items: [] } })
        }

        throw new Error(`Unexpected request: ${path}`)
      }),
    )

    render(<App />)

    expect(await screen.findByRole('alert')).toHaveTextContent('Request failed.')
  })
})

describe('Profile screen', () => {
  it('shows supervised people and collaborators from contact tags', async () => {
    const user = userEvent.setup()
    navigateTo('/profile')
    vi.stubGlobal(
      'fetch',
      vi.fn((input: string | URL | Request) => {
        const path = input.toString()
        if (path === '/api/v1/auth/session') {
          return activeSessionResponse()
        }
        if (path === '/api/v1/profile') {
          return apiResponse(200, {
            ok: true,
            data: {
              display_name: 'Kazumasa Horie',
              primary_email: 'horie@example.edu',
              email_aliases: [],
              affiliation: 'University',
              academic_title: 'Faculty',
              lab_or_group: 'Lab',
              research_fields: 'Sleep AI',
              teaching_responsibilities: '',
              committee_roles: '',
              administrative_roles: '',
              supervised_people: '',
              collaborators: '',
              important_projects: '',
              priority_keywords: '',
              low_priority_keywords: '',
              important_senders_or_domains: '',
              expected_response_policy: '',
              unavailable_times: '',
              default_reply_language: 'japanese',
              llm_self_description: '',
              mail_importance_notes: '',
              updated_at: '2026-06-03T18:00:00+09:00',
            },
          })
        }
        if (path === '/api/v1/contacts') {
          return apiResponse(200, {
            ok: true,
            data: {
              items: [
                {
                  id: 'contact_student',
                  display_name: 'Supervised Student',
                  avatar_url: 'data:image/png;base64,student',
                  user_memo: null,
                  ai_memo: null,
                  status: 'active',
                  tags: ['supervised-student'],
                  email_addresses: [],
                  latest_received_at: null,
                  inbound_message_count: 0,
                  created_at: '2026-06-03T18:00:00+09:00',
                  updated_at: '2026-06-03T18:00:00+09:00',
                  version: 1,
                },
                {
                  id: 'contact_collaborator',
                  display_name: 'Clinical Collaborator',
                  avatar_url: null,
                  user_memo: null,
                  ai_memo: null,
                  status: 'active',
                  tags: ['collaborator'],
                  email_addresses: [],
                  latest_received_at: null,
                  inbound_message_count: 0,
                  created_at: '2026-06-03T18:00:00+09:00',
                  updated_at: '2026-06-03T18:00:00+09:00',
                  version: 1,
                },
              ],
            },
          })
        }
        throw new Error(`Unexpected request: ${path}`)
      }),
    )

    render(<App />)

    expect(await screen.findByText('Supervised People')).toBeInTheDocument()
    expect(screen.getByText('Collaborators')).toBeInTheDocument()
    await user.click(screen.getByText('Supervised People'))
    expect(screen.getByText('Supervised Student')).toBeVisible()
    await user.click(screen.getByText('Collaborators'))
    expect(screen.getByText('Clinical Collaborator')).toBeVisible()
  })
})

describe('Phase 3 contacts screen', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/contacts')
  })

  it('shows the contact list without pending contact controls', async () => {
    const user = userEvent.setup()
    vi.stubGlobal(
      'fetch',
      vi.fn((input: string | URL | Request, init?: RequestInit) => {
        const path = input.toString()
        if (path === '/api/v1/auth/session') {
          return activeSessionResponse()
        }
        if (path === '/api/v1/contacts/custom-tabs') {
          if (init?.method === 'PUT') {
            return apiResponse(200, {
              ok: true,
              data: JSON.parse(String(init.body ?? '{}')),
            })
          }
          return apiResponse(200, {
            ok: true,
            data: { items: [] },
          })
        }
        if (path === '/api/v1/contacts') {
          return apiResponse(200, {
            ok: true,
            data: {
              items: [
                {
                  id: 'contact_student',
                  display_name: 'Example Student',
                  avatar_url: 'https://example.com/student.png',
                  user_memo: 'Phase 3 dummy contact.',
                  status: 'active',
                  tags: ['student', 'lab', '遲第ｳ｢螟ｧ蟄ｦ'],
                  email_addresses: [
                    {
                      id: 'email_student',
                      email_address: 'student@example.com',
                      normalized_email_address: 'student@example.com',
                      resolution_status: 'linked',
                      is_primary: true,
                      source: 'manual',
                      first_seen_at: null,
                      last_seen_at: null,
                    },
                  ],
                  created_at: '2026-05-23T09:00:00+09:00',
                  updated_at: '2026-05-23T09:00:00+09:00',
                  version: 1,
                },
                {
                  id: 'contact_mailing_list',
                  display_name: 'Example List',
                  avatar_url: null,
                  user_memo: 'Mailing list dummy contact.',
                  status: 'skipped',
                  kind: 'mailing_list',
                  sender_resolution_mode: 'reply_to',
                  mailing_list_recipient_expression: '{faculty&public-relations}',
                  tags: [],
                  email_addresses: [
                    {
                      id: 'email_list',
                      email_address: 'list@example.com',
                      normalized_email_address: 'list@example.com',
                      resolution_status: 'linked',
                      is_primary: true,
                      source: 'manual',
                      first_seen_at: null,
                      last_seen_at: null,
                    },
                  ],
                  created_at: '2026-05-23T08:00:00+09:00',
                  updated_at: '2026-05-23T08:00:00+09:00',
                  version: 1,
                },
              ],
            },
          })
        }

        throw new Error(`Unexpected request: ${path}`)
      }),
    )

    render(<App />)

    expect(
      await screen.findByRole('heading', { name: 'Contacts' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('search', { name: 'Contact search' })).toBeInTheDocument()
    expect(screen.getByLabelText('Search contacts')).toHaveAttribute(
      'placeholder',
      'Search contacts',
    )
    expect(screen.queryByRole('link', { name: 'Pending' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'New Contact' })).toBeInTheDocument()
    expect(screen.getByLabelText('Sort contacts')).toHaveValue('name')
    expect(screen.getByRole('option', { name: 'Latest mail' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Most mail received' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Status' })).not.toBeInTheDocument()
    expect(screen.getByRole('tablist', { name: 'Contact List views' })).toBeInTheDocument()
    expect(screen.getByRole('tablist', { name: 'Contact kind' })).toBeInTheDocument()
    expect(
      within(screen.getByRole('tablist', { name: 'Contact kind' }))
        .getAllByRole('tab')
        .map((tab) => tab.textContent),
    ).toEqual(['Person', 'Mailing list', 'Service'])
    const tabList = screen.getByRole('tablist', { name: 'Contact List views' })
    expect(within(tabList).getAllByRole('tab').map((tab) => tab.textContent)).toEqual([
      'All',
      'active',
      '+',
      'archived',
      'Skip',
      'SPAM',
    ])
    expect(screen.getByRole('tab', { name: 'active' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(screen.getByRole('tab', { name: 'All' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Mailing list' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Skip' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Custom tab name')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Tag expression')).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'New Contact' })).not.toBeInTheDocument()
    expect(screen.getByRole('tabpanel', { name: 'active Contact List' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Contact List' })).toBeInTheDocument()
    expect(await screen.findByText('Example Student')).toBeInTheDocument()
    expect(screen.getByAltText('Example Student avatar')).toHaveAttribute(
      'src',
      'https://example.com/student.png',
    )
    expect(screen.queryByText('Example List')).not.toBeInTheDocument()
    expect(screen.getByText('student@example.com')).toBeInTheDocument()
    expect(screen.getAllByText('student').length).toBeGreaterThan(0)
    await user.click(screen.getByRole('button', { name: 'Other tags (3)' }))
    expect(screen.getByRole('button', { name: '遲第ｳ｢螟ｧ蟄ｦ 1' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'mailing-list 1' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'student 1' })).toBeInTheDocument()
    await user.type(screen.getByLabelText('Search contacts'), 'Example lab')
    expect(screen.getByText('Example Student')).toBeInTheDocument()
    expect(screen.queryByText('Example List')).not.toBeInTheDocument()
    await user.clear(screen.getByLabelText('Search contacts'))
    await user.click(screen.getByRole('tab', { name: 'Skip' }))
    expect(screen.queryByText('Example List')).not.toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: 'Mailing list' }))
    expect(screen.getByText('Example List')).toBeInTheDocument()
    expect(screen.getByText('sender:Reply-To')).toBeInTheDocument()
    expect(screen.getByText('{faculty&public-relations}')).toBeInTheDocument()
    expect(screen.queryByText('Example Student')).not.toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: 'Person' }))
    await user.click(screen.getByRole('tab', { name: 'active' }))
    await user.type(screen.getByLabelText('Search contacts'), 'Example missing')
    expect(screen.queryByText('Example Student')).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Pending Contacts' })).not.toBeInTheDocument()
  })

  it('shows the reference value used by contact sort modes', async () => {
    const user = userEvent.setup()
    vi.stubGlobal(
      'fetch',
      vi.fn((input: string | URL | Request, init?: RequestInit) => {
        const path = input.toString()
        if (path === '/api/v1/auth/session') {
          return activeSessionResponse()
        }
        if (path === '/api/v1/contacts/custom-tabs') {
          if (init?.method === 'PUT') {
            const payload = JSON.parse(String(init.body)) as {
              items: Array<{ id: string; label: string; expression: string }>
            }
            return apiResponse(200, {
              ok: true,
              data: { items: payload.items },
            })
          }
          return apiResponse(200, {
            ok: true,
            data: { items: [] },
          })
        }
        if (path === '/api/v1/contacts') {
          return apiResponse(200, {
            ok: true,
            data: {
              items: [
                {
                  id: 'contact_old',
                  display_name: 'Old Mail',
                  avatar_url: null,
                  user_memo: null,
                  status: 'active',
                  tags: [],
                  email_addresses: [],
                  latest_received_at: '2026-05-20T09:00:00+09:00',
                  inbound_message_count: 12,
                  created_at: '2026-05-23T09:00:00+09:00',
                  updated_at: '2026-05-23T09:00:00+09:00',
                  version: 1,
                },
                {
                  id: 'contact_new',
                  display_name: 'New Mail',
                  avatar_url: null,
                  user_memo: null,
                  status: 'active',
                  tags: [],
                  email_addresses: [],
                  latest_received_at: '2026-05-29T09:00:00+09:00',
                  inbound_message_count: 4,
                  created_at: '2026-05-23T09:00:00+09:00',
                  updated_at: '2026-05-23T09:00:00+09:00',
                  version: 1,
                },
                {
                  id: 'contact_quiet',
                  display_name: 'Quiet Contact',
                  avatar_url: null,
                  user_memo: null,
                  status: 'active',
                  tags: [],
                  email_addresses: [],
                  latest_received_at: null,
                  inbound_message_count: 0,
                  created_at: '2026-05-23T09:00:00+09:00',
                  updated_at: '2026-05-23T09:00:00+09:00',
                  version: 1,
                },
              ],
            },
          })
        }

        throw new Error(`Unexpected request: ${path}`)
      }),
    )

    render(<App />)

    expect(await screen.findByText('New Mail')).toBeInTheDocument()

    await user.selectOptions(screen.getByLabelText('Sort contacts'), 'latest_mail')
    expect(screen.getByText('Latest mail: 2026-05-29')).toBeInTheDocument()
    expect(screen.getByText('Latest mail: 2026-05-20')).toBeInTheDocument()
    expect(screen.getByText('Latest mail: -')).toBeInTheDocument()
    expect(
      within(screen.getByRole('tabpanel', { name: 'active Contact List' }))
        .getAllByRole('heading', { level: 3 })
        .map((heading) => heading.textContent),
    ).toEqual(['New Mail', 'Old Mail', 'Quiet Contact'])

    await user.selectOptions(screen.getByLabelText('Sort contacts'), 'mail_count')
    expect(screen.getByText('12 received')).toBeInTheDocument()
    expect(screen.getByText('4 received')).toBeInTheDocument()
    expect(screen.getByText('0 received')).toBeInTheDocument()
    expect(
      within(screen.getByRole('tabpanel', { name: 'active Contact List' }))
        .getAllByRole('heading', { level: 3 })
        .map((heading) => heading.textContent),
    ).toEqual(['Old Mail', 'New Mail', 'Quiet Contact'])
  })

  it('filters contacts by status tabs and custom tag tabs', async () => {
    const user = userEvent.setup()
    vi.stubGlobal(
      'fetch',
      vi.fn((input: string | URL | Request, init?: RequestInit) => {
        const path = input.toString()
        if (path === '/api/v1/auth/session') {
          return activeSessionResponse()
        }
        if (path === '/api/v1/contacts/custom-tabs') {
          if (init?.method === 'PUT') {
            const payload = JSON.parse(String(init.body)) as {
              items: Array<{ id: string; label: string; expression: string }>
            }
            return apiResponse(200, {
              ok: true,
              data: { items: payload.items },
            })
          }
          return apiResponse(200, {
            ok: true,
            data: { items: [] },
          })
        }
        if (path === '/api/v1/contacts') {
          return apiResponse(200, {
            ok: true,
            data: {
              items: [
                {
                id: 'contact_student',
                display_name: 'Example Student',
                avatar_url: null,
                user_memo: null,
                  status: 'active',
                  tags: ['tsukuba', 'student'],
                  email_addresses: [],
                  created_at: '2026-05-23T09:00:00+09:00',
                  updated_at: '2026-05-23T09:00:00+09:00',
                  version: 1,
                },
                {
                id: 'contact_kde',
                display_name: 'KDE Student',
                avatar_url: null,
                user_memo: null,
                  status: 'active',
                  tags: ['tsukuba', 'student', 'lab-member'],
                  email_addresses: [],
                  created_at: '2026-05-23T09:00:00+09:00',
                  updated_at: '2026-05-23T09:00:00+09:00',
                  version: 1,
                },
                {
                id: 'contact_quiet',
                display_name: 'Quiet Contact',
                avatar_url: null,
                user_memo: null,
                  status: 'active',
                  tags: [],
                  email_addresses: [],
                  created_at: '2026-05-23T09:00:00+09:00',
                  updated_at: '2026-05-23T09:00:00+09:00',
                  version: 1,
                },
                {
                id: 'contact_spam',
                display_name: 'Spam Contact',
                avatar_url: null,
                user_memo: null,
                  status: 'spam',
                  tags: [],
                  email_addresses: [],
                  created_at: '2026-05-23T09:00:00+09:00',
                  updated_at: '2026-05-23T09:00:00+09:00',
                  version: 1,
                },
                {
                id: 'contact_list',
                display_name: 'Example List',
                avatar_url: null,
                user_memo: null,
                  status: 'skipped',
                  kind: 'mailing_list',
                  sender_resolution_mode: 'self',
                  mailing_list_recipient_expression: '{list-targets}',
                  tags: [],
                  email_addresses: [],
                  created_at: '2026-05-23T09:00:00+09:00',
                  updated_at: '2026-05-23T09:00:00+09:00',
                  version: 1,
                },
              ],
            },
          })
        }

        throw new Error(`Unexpected request: ${path}`)
      }),
    )

    render(<App />)

    expect(await screen.findByText('Example Student')).toBeInTheDocument()
    const tagFilterButtons = within(screen.getByLabelText('Contact tag filters')).getAllByRole('button')
    expect(tagFilterButtons[0]).toHaveAccessibleName('No tag 1')
    expect(tagFilterButtons[0]).toHaveClass('is-reserved-contact-tag')
    await user.click(screen.getByRole('button', { name: 'No tag 1' }))
    expect(screen.queryByText('Example Student')).not.toBeInTheDocument()
    expect(screen.queryByText('KDE Student')).not.toBeInTheDocument()
    expect(screen.getByText('Quiet Contact')).toBeInTheDocument()
    expect(screen.queryByText('Spam Contact')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'No tag 1' }))
    await user.click(screen.getByRole('button', { name: 'Other tags (3)' }))
    await user.click(screen.getByRole('button', { name: 'lab-member 1' }))

    expect(screen.queryByText('Example Student')).not.toBeInTheDocument()
    expect(screen.getByText('KDE Student')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'lab-member 1' }))
    await user.click(screen.getByRole('tab', { name: 'Skip' }))

    expect(screen.queryByText('Example Student')).not.toBeInTheDocument()
    expect(screen.queryByText('Example List')).not.toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: 'Mailing list' }))
    expect(screen.getByText('Example List')).toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: 'Person' }))

    await user.click(screen.getByRole('tab', { name: '+' }))
    expect(screen.getByRole('tabpanel', { name: '+ Contact List' })).toBeInTheDocument()
    expect(screen.getByLabelText('Custom tab name')).toHaveAttribute('maxlength', '12')
    expect(screen.getByText('Example Student')).toBeInTheDocument()
    expect(screen.getByText('KDE Student')).toBeInTheDocument()
    await user.type(screen.getByLabelText('Custom tab name'), 'TsukubaLab')
    await user.type(screen.getByLabelText('Tag expression'), 'tsukuba&student&!lab-member')
    expect(screen.getByText('Example Student')).toBeInTheDocument()
    expect(screen.queryByText('KDE Student')).not.toBeInTheDocument()
    expect(screen.queryByText('Example List')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'OK' }))
    await user.click(await screen.findByRole('tab', { name: 'TsukubaLab' }))

    await waitFor(() => {
      expect(screen.getByText('Example Student')).toBeInTheDocument()
      expect(screen.queryByText('KDE Student')).not.toBeInTheDocument()
    })
    expect(screen.queryByText('Example List')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Delete tab' })).toBeInTheDocument()
    expect(within(screen.getByRole('tablist', { name: 'Contact List views' })).getAllByRole('tab').map((tab) => tab.textContent)).toEqual([
      'All',
      'active',
      'TsukubaLab',
      '+',
      'archived',
      'Skip',
      'SPAM',
    ])

    await user.click(screen.getByRole('button', { name: 'Delete tab' }))

    expect(screen.queryByRole('tab', { name: 'TsukubaLab' })).not.toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'All' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
  })

  it('opens a contact detail panel and updates the contact', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = input.toString()
      if (path === '/api/v1/auth/session') {
        return activeSessionResponse()
      }
      if (path === '/api/v1/contacts' && init?.method === undefined) {
        return apiResponse(200, {
          ok: true,
          data: {
            items: [
              {
                id: 'contact_student',
                display_name: 'Example Student',
                avatar_url: null,
                user_memo: 'Phase 3 dummy contact.',
                status: 'active',
                tags: ['student', 'lab'],
                email_addresses: [
                  {
                    id: 'email_student',
                    email_address: 'student@example.com',
                    normalized_email_address: 'student@example.com',
                    resolution_status: 'linked',
                    status: 'active',
                    has_inbound_message_history: true,
                    is_primary: true,
                    source: 'manual',
                    first_seen_at: null,
                    last_seen_at: null,
                  },
                  {
                    id: 'email_alt',
                    email_address: 'student.alt@example.com',
                    normalized_email_address: 'student.alt@example.com',
                    resolution_status: 'linked',
                    status: 'active',
                    has_inbound_message_history: false,
                    is_primary: false,
                    source: 'manual',
                    first_seen_at: null,
                    last_seen_at: null,
                  },
                ],
                created_at: '2026-05-23T09:00:00+09:00',
                updated_at: '2026-05-23T09:00:00+09:00',
                version: 1,
              },
              {
                id: 'contact_teacher',
                display_name: 'Example Teacher',
                avatar_url: null,
                user_memo: 'Another dummy contact.',
                status: 'active',
                tags: ['teacher'],
                email_addresses: [
                  {
                    id: 'email_teacher',
                    email_address: 'teacher@example.com',
                    normalized_email_address: 'teacher@example.com',
                    resolution_status: 'linked',
                    is_primary: true,
                    source: 'manual',
                    first_seen_at: null,
                    last_seen_at: null,
                  },
                ],
                created_at: '2026-05-23T09:30:00+09:00',
                updated_at: '2026-05-23T09:30:00+09:00',
                version: 1,
              },
            ],
          },
        })
      }
      if (path === '/api/v1/contacts/contact_student' && init?.method === 'PATCH') {
        return apiResponse(200, {
          ok: true,
          data: {
            id: 'contact_student',
            display_name: 'Example Researcher',
            avatar_url: null,
            user_memo: 'Updated memo.',
            status: 'active',
            tags: ['lab', 'student', 'updated'],
            email_addresses: [
              {
                id: 'email_student',
                email_address: 'student@example.com',
                normalized_email_address: 'student@example.com',
                resolution_status: 'linked',
                status: 'active',
                has_inbound_message_history: true,
                is_primary: true,
                source: 'manual',
                first_seen_at: null,
                last_seen_at: null,
              },
              {
                id: 'email_alt',
                email_address: 'student.alt@example.com',
                normalized_email_address: 'student.alt@example.com',
                resolution_status: 'linked',
                status: 'active',
                has_inbound_message_history: false,
                is_primary: false,
                source: 'manual',
                first_seen_at: null,
                last_seen_at: null,
              },
            ],
            created_at: '2026-05-23T09:00:00+09:00',
            updated_at: '2026-05-23T10:00:00+09:00',
            version: 2,
          },
        })
      }
      if (
        path === '/api/v1/contacts/contact_student/email-addresses' &&
        init?.method === 'POST'
      ) {
        return apiResponse(200, {
          ok: true,
          data: {
            id: 'contact_student',
            display_name: 'Example Researcher',
            avatar_url: null,
            user_memo: 'Updated memo.',
            status: 'active',
            tags: ['lab', 'student', 'updated'],
            email_addresses: [
              {
                id: 'email_student',
                email_address: 'student@example.com',
                normalized_email_address: 'student@example.com',
                resolution_status: 'linked',
                status: 'active',
                has_inbound_message_history: true,
                is_primary: true,
                source: 'manual',
                first_seen_at: null,
                last_seen_at: null,
              },
              {
                id: 'email_alt',
                email_address: 'student.alt@example.com',
                normalized_email_address: 'student.alt@example.com',
                resolution_status: 'linked',
                status: 'active',
                has_inbound_message_history: false,
                is_primary: false,
                source: 'manual',
                first_seen_at: null,
                last_seen_at: null,
              },
              {
                id: 'email_new_alt',
                email_address: 'student.new@example.com',
                normalized_email_address: 'student.new@example.com',
                resolution_status: 'linked',
                status: 'active',
                has_inbound_message_history: false,
                is_primary: false,
                source: 'manual',
                first_seen_at: null,
                last_seen_at: null,
              },
            ],
            created_at: '2026-05-23T09:00:00+09:00',
            updated_at: '2026-05-23T10:05:00+09:00',
            version: 3,
          },
        })
      }
      if (
        path === '/api/v1/contacts/contact_student/email-addresses/email_alt/primary' &&
        init?.method === 'POST'
      ) {
        return apiResponse(200, {
          ok: true,
          data: {
            id: 'contact_student',
            display_name: 'Example Researcher',
            avatar_url: null,
            user_memo: 'Updated memo.',
            status: 'active',
            tags: ['lab', 'student', 'updated'],
            email_addresses: [
              {
                id: 'email_alt',
                email_address: 'student.alt@example.com',
                normalized_email_address: 'student.alt@example.com',
                resolution_status: 'linked',
                status: 'active',
                has_inbound_message_history: false,
                is_primary: true,
                source: 'manual',
                first_seen_at: null,
                last_seen_at: null,
              },
              {
                id: 'email_student',
                email_address: 'student@example.com',
                normalized_email_address: 'student@example.com',
                resolution_status: 'linked',
                status: 'active',
                has_inbound_message_history: true,
                is_primary: false,
                source: 'manual',
                first_seen_at: null,
                last_seen_at: null,
              },
            ],
            created_at: '2026-05-23T09:00:00+09:00',
            updated_at: '2026-05-23T10:10:00+09:00',
            version: 4,
          },
        })
      }
      if (
        path === '/api/v1/contacts/contact_student/email-addresses/email_student' &&
        init?.method === 'DELETE'
      ) {
        return apiResponse(200, {
          ok: true,
          data: {
            id: 'contact_student',
            display_name: 'Example Researcher',
            avatar_url: null,
            user_memo: 'Updated memo.',
            status: 'active',
            tags: ['lab', 'student', 'updated'],
            email_addresses: [
              {
                id: 'email_student',
                email_address: 'student@example.com',
                normalized_email_address: 'student@example.com',
                resolution_status: 'linked',
                status: 'inactive',
                has_inbound_message_history: true,
                is_primary: false,
                source: 'manual',
                first_seen_at: null,
                last_seen_at: null,
              },
              {
                id: 'email_alt',
                email_address: 'student.alt@example.com',
                normalized_email_address: 'student.alt@example.com',
                resolution_status: 'linked',
                status: 'active',
                has_inbound_message_history: false,
                is_primary: true,
                source: 'manual',
                first_seen_at: null,
                last_seen_at: null,
              },
            ],
            created_at: '2026-05-23T09:00:00+09:00',
            updated_at: '2026-05-23T10:15:00+09:00',
            version: 5,
          },
        })
      }
      if (
        path === '/api/v1/contacts/contact_student/email-addresses/email_student/activate' &&
        init?.method === 'POST'
      ) {
        return apiResponse(200, {
          ok: true,
          data: {
            id: 'contact_student',
            display_name: 'Example Researcher',
            avatar_url: null,
            user_memo: 'Updated memo.',
            status: 'active',
            tags: ['lab', 'student', 'updated'],
            email_addresses: [
              {
                id: 'email_alt',
                email_address: 'student.alt@example.com',
                normalized_email_address: 'student.alt@example.com',
                resolution_status: 'linked',
                status: 'active',
                has_inbound_message_history: false,
                is_primary: true,
                source: 'manual',
                first_seen_at: null,
                last_seen_at: null,
              },
              {
                id: 'email_student',
                email_address: 'student@example.com',
                normalized_email_address: 'student@example.com',
                resolution_status: 'linked',
                status: 'active',
                has_inbound_message_history: true,
                is_primary: false,
                source: 'manual',
                first_seen_at: null,
                last_seen_at: null,
              },
            ],
            created_at: '2026-05-23T09:00:00+09:00',
            updated_at: '2026-05-23T10:18:00+09:00',
            version: 6,
          },
        })
      }
      if (
        path === '/api/v1/contacts/contact_student/email-addresses/email_alt/move' &&
        init?.method === 'POST'
      ) {
        return apiResponse(200, {
          ok: true,
          data: {
            source_contact: {
              id: 'contact_student',
              display_name: 'Example Researcher',
              avatar_url: null,
              user_memo: 'Updated memo.',
              status: 'active',
              tags: ['lab', 'student', 'updated'],
              email_addresses: [
                {
                  id: 'email_student',
                  email_address: 'student@example.com',
                  normalized_email_address: 'student@example.com',
                  resolution_status: 'linked',
                  status: 'inactive',
                  has_inbound_message_history: true,
                  is_primary: false,
                  source: 'manual',
                  first_seen_at: null,
                  last_seen_at: null,
                },
              ],
              created_at: '2026-05-23T09:00:00+09:00',
              updated_at: '2026-05-23T10:20:00+09:00',
              version: 6,
            },
            target_contact: {
              id: 'contact_teacher',
              display_name: 'Example Teacher',
              avatar_url: null,
              user_memo: 'Another dummy contact.',
              status: 'active',
              tags: ['teacher'],
              email_addresses: [
                {
                  id: 'email_teacher',
                  email_address: 'teacher@example.com',
                  normalized_email_address: 'teacher@example.com',
                  resolution_status: 'linked',
                  status: 'active',
                  has_inbound_message_history: false,
                  is_primary: true,
                  source: 'manual',
                  first_seen_at: null,
                  last_seen_at: null,
                },
                {
                  id: 'email_alt',
                  email_address: 'student.alt@example.com',
                  normalized_email_address: 'student.alt@example.com',
                  resolution_status: 'linked',
                  status: 'active',
                  has_inbound_message_history: false,
                  is_primary: false,
                  source: 'manual',
                  first_seen_at: null,
                  last_seen_at: null,
                },
              ],
              created_at: '2026-05-23T09:30:00+09:00',
              updated_at: '2026-05-23T10:20:00+09:00',
              version: 2,
            },
          },
        })
      }

      throw new Error(`Unexpected request: ${path} ${init?.method ?? 'GET'}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    expect(await screen.findByText('Example Student')).toBeInTheDocument()
    await user.click(screen.getByRole('heading', { name: 'Example Student' }))

    expect(screen.getByRole('heading', { name: 'Contact Detail' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Contact Detail' }).closest('.contact-detail-card')).toHaveClass(
      'contact-detail-card',
    )
    expect(screen.getByText('Phase 3 dummy contact.')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Related cases' })).toBeInTheDocument()
    expect(screen.getByText('No related cases yet.')).toBeInTheDocument()
    expect(screen.queryByLabelText('Contact display name')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('New email address')).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Set student.alt@example.com as primary' }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Remove student@example.com' }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Deactivate student@example.com' }),
    ).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Collapse Example Student' }))
    expect(screen.queryByRole('heading', { name: 'Contact Detail' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('heading', { name: 'Example Student' }))
    await user.click(screen.getByRole('button', { name: 'Edit contact' }))
    expect(screen.getByRole('button', { name: 'Update avatar' })).toBeEnabled()
    expect(screen.getByLabelText('Contact image file')).toHaveAttribute(
      'type',
      'file',
    )
    expect(screen.queryByLabelText('Contact type')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Clear contact display name' }))
    expect(screen.getByLabelText('Contact display name')).toHaveValue('')
    await user.type(screen.getByLabelText('Contact display name'), 'Example Researcher')
    await user.clear(screen.getByLabelText('Contact user memo'))
    await user.type(screen.getByLabelText('Contact user memo'), 'Updated memo.')
    await user.clear(screen.getByLabelText('Contact tags'))
    await user.type(screen.getByLabelText('Contact tags'), 'lab, student, updated')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/contacts/contact_student',
      expect.objectContaining({
        credentials: 'include',
        method: 'PATCH',
        body: JSON.stringify({
          display_name: 'Example Researcher',
          avatar_url: null,
          user_memo: 'Updated memo.',
          status: 'active',
          kind: 'person',
          sender_resolution_mode: 'self',
          mailing_list_recipient_expression: null,
          mail_importance_rule_action: 'llm',
          mail_importance_rule_importance: null,
          mail_importance_rule_instruction: null,
          tags: ['lab', 'student', 'updated'],
        }),
      }),
    )
    expect(await screen.findByText('Contact updated.')).toBeInTheDocument()
    expect(screen.getAllByText('Example Researcher').length).toBeGreaterThan(0)

    await user.click(screen.getByRole('button', { name: 'Edit contact' }))
    await user.type(screen.getByLabelText('New email address'), 'typo@example.com')
    await user.click(screen.getByRole('button', { name: 'Clear new email address' }))
    expect(screen.getByLabelText('New email address')).toHaveValue('')
    await user.type(screen.getByLabelText('New email address'), 'student.new@example.com')
    await user.click(screen.getByRole('button', { name: 'Add email address' }))

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/contacts/contact_student/email-addresses',
      expect.objectContaining({
        credentials: 'include',
        method: 'POST',
        body: JSON.stringify({
          email_address: 'student.new@example.com',
          is_primary: false,
        }),
      }),
    )
    expect(await screen.findByText('Email address added.')).toBeInTheDocument()
    expect(
      screen.getByRole('heading', { name: 'Contact Detail' }).closest('.contact-detail-card'),
    ).toContainElement(screen.getByText('Email address added.'))
    expect(screen.getByText('student.alt@example.com')).toBeInTheDocument()

    await user.click(screen.getByRole('heading', { name: 'Example Teacher' }))
    expect(screen.getByText('Another dummy contact.')).toBeInTheDocument()
    expect(screen.queryByText('Email address added.')).not.toBeInTheDocument()
    await user.click(screen.getByRole('heading', { name: 'Example Researcher' }))

    await user.click(screen.getByRole('button', { name: 'Edit contact' }))
    await user.click(screen.getByRole('button', { name: 'Set student.alt@example.com as primary' }))
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/contacts/contact_student/email-addresses/email_alt/primary',
      expect.objectContaining({
        credentials: 'include',
        method: 'POST',
      }),
    )
    expect(await screen.findByText('Primary email updated.')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Edit contact' }))
    await user.click(screen.getByRole('button', { name: 'Deactivate student@example.com' }))
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/contacts/contact_student/email-addresses/email_student',
      expect.objectContaining({
        credentials: 'include',
        method: 'DELETE',
      }),
    )
    expect(await screen.findByText('Email address deactivated.')).toBeInTheDocument()
    expect(screen.getByText('student@example.com')).toBeInTheDocument()
    expect(screen.getByText('inactive')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Deactivate student@example.com' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Edit contact' }))
    await user.click(screen.getByRole('button', { name: 'Activate student@example.com' }))
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/contacts/contact_student/email-addresses/email_student/activate',
      expect.objectContaining({
        credentials: 'include',
        method: 'POST',
      }),
    )
    expect(await screen.findByText('Email address activated.')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Edit contact' }))
    await user.selectOptions(
      screen.getByLabelText('Move student.alt@example.com to contact'),
      'contact_teacher',
    )
    const altEmailRow = screen
      .getAllByText('student.alt@example.com')
      .find((element) => element.tagName.toLowerCase() === 'span')
      ?.closest('li')
    expect(altEmailRow).not.toBeNull()
    await user.click(within(altEmailRow as HTMLElement).getByRole('button', { name: 'Move' }))
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/contacts/contact_student/email-addresses/email_alt/move',
      expect.objectContaining({
        credentials: 'include',
        method: 'POST',
        body: JSON.stringify({ target_contact_id: 'contact_teacher' }),
      }),
    )
    expect(await screen.findByText('Email address moved.')).toBeInTheDocument()
    expect(screen.queryByText('student.alt@example.com')).not.toBeInTheDocument()
  })

  it('shows unresolved From addresses and can resolve them', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = input.toString()
      if (path === '/api/v1/auth/session') {
        return activeSessionResponse()
      }
      if (path === '/api/v1/contacts' && init?.method === undefined) {
        return apiResponse(200, {
          ok: true,
          data: {
            items: [
              {
                id: 'contact_existing',
                display_name: 'Existing Contact',
                avatar_url: null,
                user_memo: null,
                status: 'active',
                tags: [],
                email_addresses: [
                  {
                    id: 'email_existing',
                    email_address: 'existing@example.com',
                    normalized_email_address: 'existing@example.com',
                    resolution_status: 'linked',
                    is_primary: true,
                    source: 'manual',
                    first_seen_at: null,
                    last_seen_at: null,
                  },
                ],
                created_at: '2026-05-23T09:00:00+09:00',
                updated_at: '2026-05-23T09:00:00+09:00',
                version: 1,
              },
            ],
          },
        })
      }
      if (path === '/api/v1/contacts/unresolved-from-addresses') {
        return apiResponse(200, {
          ok: true,
          data: {
            items: [
              {
                email_address_id: 'email_unknown',
                email_address: 'unknown.sender@example.com',
                normalized_email_address: 'unknown.sender@example.com',
                message_count: 0,
                latest_message_id: null,
                latest_subject: null,
                latest_from_name: null,
                latest_from_address: null,
                latest_reply_to_address: null,
                latest_received_at: null,
                latest_body_preview: null,
                inferred_display_name: 'Unknown Sender',
                inferred_kind: 'person',
                inferred_sender_resolution: 'self',
                suggestion_status: 'not_started',
                suggestion: null,
              },
              {
                email_address_id: 'email_list_sender',
                email_address: 'list.sender@example.com',
                normalized_email_address: 'list.sender@example.com',
                message_count: 0,
                latest_message_id: null,
                latest_subject: null,
                latest_from_name: null,
                latest_from_address: null,
                latest_reply_to_address: null,
                latest_received_at: null,
                latest_body_preview: null,
                inferred_display_name: 'List Sender',
                inferred_kind: 'mailing_list',
                inferred_sender_resolution: 'reply_to',
                suggestion_status: 'not_started',
                suggestion: null,
              },
              {
                email_address_id: 'email_existing_sender',
                email_address: 'existing.sender@example.com',
                normalized_email_address: 'existing.sender@example.com',
                message_count: 0,
                latest_message_id: null,
                latest_subject: null,
                latest_from_name: null,
                latest_from_address: null,
                latest_reply_to_address: null,
                latest_received_at: null,
                latest_body_preview: null,
                inferred_display_name: 'Existing Sender',
                inferred_kind: 'person',
                inferred_sender_resolution: 'self',
                suggestion_status: 'not_started',
                suggestion: null,
              },
            ],
          },
        })
      }
      if (path === '/api/v1/contacts' && init?.method === 'POST') {
        const body = JSON.parse(init.body as string) as { display_name: string; status: string }
        return apiResponse(200, {
          ok: true,
          data: {
            id: `contact_${body.status}_${body.display_name.replaceAll(' ', '_')}`,
            display_name: body.display_name,
            avatar_url: null,
            user_memo: '',
            status: body.status,
            tags: [],
            email_addresses: [],
            created_at: '2026-05-23T09:00:00+09:00',
            updated_at: '2026-05-23T09:00:00+09:00',
            version: 1,
          },
        })
      }
      if (
        path === '/api/v1/contacts/contact_existing/email-addresses' &&
        init?.method === 'POST'
      ) {
        return apiResponse(200, {
          ok: true,
          data: {
            id: 'contact_existing',
            display_name: 'Existing Contact',
            avatar_url: null,
            user_memo: null,
            status: 'active',
            tags: [],
            email_addresses: [
              {
                id: 'email_existing',
                email_address: 'existing@example.com',
                normalized_email_address: 'existing@example.com',
                resolution_status: 'linked',
                is_primary: true,
                source: 'manual',
                first_seen_at: null,
                last_seen_at: null,
              },
              {
                id: 'email_existing_sender',
                email_address: 'existing.sender@example.com',
                normalized_email_address: 'existing.sender@example.com',
                resolution_status: 'linked',
                is_primary: false,
                source: 'manual',
                first_seen_at: null,
                last_seen_at: null,
              },
            ],
            created_at: '2026-05-23T09:00:00+09:00',
            updated_at: '2026-05-23T09:10:00+09:00',
            version: 2,
          },
        })
      }
      if (
        path ===
        '/api/v1/contacts/unresolved-from-addresses/unknown.sender%40example.com/generate-prefill'
      ) {
        return apiResponse(200, {
          ok: true,
          data: { job_id: 'job_contact_prefill_test' },
        })
      }

      throw new Error(`Unexpected request: ${path} ${init?.method ?? 'GET'}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    window.history.pushState({}, '', '/contacts/pending')

    render(<App />)

    expect(
      await screen.findByRole('heading', { name: 'Pending Contacts' }),
    ).toBeInTheDocument()
    expect(await screen.findByText('unknown.sender@example.com')).toBeInTheDocument()
    expect(await screen.findByText('list.sender@example.com')).toBeInTheDocument()
    expect(await screen.findByText('existing.sender@example.com')).toBeInTheDocument()

    await user.click(screen.getAllByRole('button', { name: 'active' })[0])
    await user.click(
      screen.getByRole('button', { name: 'Create contact for unknown.sender@example.com' }),
    )
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/contacts',
      expect.objectContaining({
        credentials: 'include',
        method: 'POST',
        body: JSON.stringify({
          display_name: 'Unknown Sender',
          user_memo: '',
          status: 'active',
          kind: 'person',
          sender_resolution_mode: 'self',
          mailing_list_recipient_expression: null,
          mail_importance_rule_action: 'llm',
          mail_importance_rule_importance: null,
          mail_importance_rule_instruction: null,
          tags: [],
          email_addresses: [
            { email_address: 'unknown.sender@example.com', is_primary: true },
          ],
          source_suggestion_id: null,
        }),
      }),
    )
    expect(screen.queryByText('unknown.sender@example.com')).not.toBeInTheDocument()

    await user.click(screen.getAllByRole('button', { name: 'skipped' })[0])
    await user.click(
      screen.getByRole('button', { name: 'Create contact for list.sender@example.com' }),
    )
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/contacts',
      expect.objectContaining({
        credentials: 'include',
        method: 'POST',
        body: JSON.stringify({
          display_name: 'List Sender',
          user_memo: '',
          status: 'skipped',
          kind: 'mailing_list',
          sender_resolution_mode: 'reply_to',
          mailing_list_recipient_expression: null,
          mail_importance_rule_action: 'llm',
          mail_importance_rule_importance: null,
          mail_importance_rule_instruction: null,
          tags: [],
          email_addresses: [
            { email_address: 'list.sender@example.com', is_primary: true },
          ],
          source_suggestion_id: null,
        }),
      }),
    )
    expect(screen.queryByText('list.sender@example.com')).not.toBeInTheDocument()
  })

  it('creates a contact from the contact form', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = input.toString()
      if (path === '/api/v1/auth/session') {
        return activeSessionResponse()
      }
      if (path === '/api/v1/contacts' && init?.method !== 'POST') {
        return apiResponse(200, { ok: true, data: { items: [] } })
      }
      if (path === '/api/v1/contacts' && init?.method === 'POST') {
        return apiResponse(200, {
          ok: true,
          data: {
            id: 'contact_new',
            display_name: 'New Example',
            avatar_url: null,
            user_memo: '',
            status: 'active',
            tags: [],
            email_addresses: [
              {
                id: 'email_new',
                email_address: 'new@example.com',
                normalized_email_address: 'new@example.com',
                resolution_status: 'linked',
                is_primary: true,
                source: 'manual',
                first_seen_at: null,
                last_seen_at: null,
              },
            ],
            created_at: '2026-05-23T09:00:00+09:00',
            updated_at: '2026-05-23T09:00:00+09:00',
            version: 1,
          },
        })
      }

      throw new Error(`Unexpected request: ${path} ${init?.method ?? 'GET'}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    expect(
      await screen.findByRole('search', { name: 'Contact search' }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'New Contact' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'New Contact' }))

    expect(screen.getByRole('heading', { name: 'New Contact' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Memo')).not.toBeInTheDocument()
    await user.type(screen.getByLabelText('Display name'), 'New Example')
    await user.type(screen.getByLabelText('Email address'), 'new@example.com')
    await user.click(screen.getByRole('button', { name: 'Create contact' }))

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/contacts',
      expect.objectContaining({
        credentials: 'include',
        method: 'POST',
        body: JSON.stringify({
          display_name: 'New Example',
          user_memo: '',
          status: 'active',
          kind: 'person',
          sender_resolution_mode: 'self',
          mailing_list_recipient_expression: null,
          mail_importance_rule_action: 'llm',
          mail_importance_rule_importance: null,
          mail_importance_rule_instruction: null,
          tags: [],
          email_addresses: [
            { email_address: 'new@example.com', is_primary: true },
          ],
        }),
      }),
    )
    expect((await screen.findAllByText('New Example')).length).toBeGreaterThan(0)
    expect(screen.getAllByText('new@example.com').length).toBeGreaterThan(0)
    expect(screen.getByAltText('New Example avatar')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'All' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(screen.getByLabelText('Contact display name')).toHaveValue('New Example')
    expect(screen.getByLabelText('Contact user memo')).toHaveValue('')
  })
})
