import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import { applyLanguagePatch, resetLanguagePatch } from './i18n'

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
    },
  })
}

afterEach(() => {
  resetLanguagePatch()
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

    render(<App />)
    await user.type(await screen.findByLabelText('Password'), 'phase-one-password')
    await user.click(screen.getByRole('button', { name: 'Log in' }))

    expect(fetchMock).toHaveBeenLastCalledWith(
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
    expect(screen.getByRole('navigation', { name: 'Main work' })).toHaveTextContent(
      'New Case',
    )
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
      vi.fn(() => activeSessionResponse()),
    )

    render(<App />)

    expect(
      await screen.findByRole('heading', { name: 'Top' }),
    ).toBeInTheDocument()
    expect(screen.getByLabelText('Current session')).toHaveTextContent(
      'Bootstrap device',
    )
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
    expect(
      screen.getByText(
        'The job failed. Reason: ReviewFailure - Review sample failure.',
      ),
    ).toBeInTheDocument()
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
    expect(screen.getByRole('row', { name: /job_failed/ })).toHaveTextContent(
      'pending',
    )
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
    expect(screen.getByText('7d ago')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Running jobs 0/ }))
    expect(
      screen.getByRole('heading', { name: 'Running jobs history' }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Jobs' })).not.toBeInTheDocument()
    expect(
      screen.queryByRole('heading', { name: 'External Operations' }),
    ).not.toBeInTheDocument()
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

        throw new Error(`Unexpected request: ${path}`)
      }),
    )

    render(<App />)

    expect(await screen.findByRole('alert')).toHaveTextContent('Request failed.')
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
      vi.fn((input: string | URL | Request) => {
        const path = input.toString()
        if (path === '/api/v1/auth/session') {
          return activeSessionResponse()
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
                  memo: 'Phase 3 dummy contact.',
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
                  memo: 'Mailing list dummy contact.',
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
    expect(screen.getAllByRole('link', { name: 'Pending' })[0]).toHaveAttribute(
      'href',
      '/contacts/pending',
    )
    expect(screen.getByRole('button', { name: 'New Contact' })).toBeInTheDocument()
    expect(screen.getByLabelText('Sort contacts')).toHaveValue('name')
    expect(screen.queryByRole('option', { name: 'Status' })).not.toBeInTheDocument()
    expect(screen.getByRole('tablist', { name: 'Contact List views' })).toBeInTheDocument()
    const tabList = screen.getByRole('tablist', { name: 'Contact List views' })
    expect(within(tabList).getAllByRole('tab').map((tab) => tab.textContent)).toEqual([
      'All',
      'active',
      '+',
      'Mailing list',
      'archived',
      'Skip',
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
    expect(screen.getByRole('button', { name: '遲第ｳ｢螟ｧ蟄ｦ 1' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'mailing-list 1' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'student 1' })).toBeInTheDocument()
    await user.type(screen.getByLabelText('Search contacts'), 'Example lab')
    expect(screen.getByText('Example Student')).toBeInTheDocument()
    expect(screen.queryByText('Example List')).not.toBeInTheDocument()
    await user.clear(screen.getByLabelText('Search contacts'))
    await user.click(screen.getByRole('tab', { name: 'Mailing list' }))
    expect(screen.getByText('Example List')).toBeInTheDocument()
    expect(screen.getByText('sender:Reply-To')).toBeInTheDocument()
    expect(screen.getByText('{faculty&public-relations}')).toBeInTheDocument()
    expect(screen.queryByText('Example Student')).not.toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: 'active' }))
    await user.type(screen.getByLabelText('Search contacts'), 'Example missing')
    expect(screen.queryByText('Example Student')).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Pending Contacts' })).not.toBeInTheDocument()
  })

  it('filters contacts by status tabs and custom tag tabs', async () => {
    const user = userEvent.setup()
    vi.stubGlobal(
      'fetch',
      vi.fn((input: string | URL | Request) => {
        const path = input.toString()
        if (path === '/api/v1/auth/session') {
          return activeSessionResponse()
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
                memo: null,
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
                memo: null,
                  status: 'active',
                  tags: ['tsukuba', 'student', 'KDE'],
                  email_addresses: [],
                  created_at: '2026-05-23T09:00:00+09:00',
                  updated_at: '2026-05-23T09:00:00+09:00',
                  version: 1,
                },
                {
                id: 'contact_list',
                display_name: 'Example List',
                avatar_url: null,
                memo: null,
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
    await user.click(screen.getByRole('button', { name: 'KDE 1' }))

    expect(screen.queryByText('Example Student')).not.toBeInTheDocument()
    expect(screen.getByText('KDE Student')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'KDE 1' }))
    await user.click(screen.getByRole('tab', { name: 'Skip' }))

    expect(screen.queryByText('Example Student')).not.toBeInTheDocument()
    expect(screen.queryByText('Example List')).not.toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: 'Mailing list' }))
    expect(screen.getByText('Example List')).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: '+' }))
    expect(screen.getByRole('tabpanel', { name: '+ Contact List' })).toBeInTheDocument()
    expect(screen.getByLabelText('Custom tab name')).toHaveAttribute('maxlength', '12')
    await user.type(screen.getByLabelText('Custom tab name'), 'TsukubaLab')
    await user.type(screen.getByLabelText('Tag expression'), 'tsukuba&student&!KDE')
    await user.click(screen.getByRole('button', { name: 'OK' }))

    expect(screen.getByText('Example Student')).toBeInTheDocument()
    expect(screen.queryByText('KDE Student')).not.toBeInTheDocument()
    expect(screen.queryByText('Example List')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Delete tab' })).toBeInTheDocument()
    expect(within(screen.getByRole('tablist', { name: 'Contact List views' })).getAllByRole('tab').map((tab) => tab.textContent)).toEqual([
      'All',
      'active',
      'TsukubaLab',
      '+',
      'Mailing list',
      'archived',
      'Skip',
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
                memo: 'Phase 3 dummy contact.',
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
                memo: 'Another dummy contact.',
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
            memo: 'Updated memo.',
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
            memo: 'Updated memo.',
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
            memo: 'Updated memo.',
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
            memo: 'Updated memo.',
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
            memo: 'Updated memo.',
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
              memo: 'Updated memo.',
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
              memo: 'Another dummy contact.',
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
    expect(screen.getByRole('button', { name: 'Update avatar' })).toBeDisabled()
    expect(screen.queryByLabelText('Contact type')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Clear contact display name' }))
    expect(screen.getByLabelText('Contact display name')).toHaveValue('')
    await user.type(screen.getByLabelText('Contact display name'), 'Example Researcher')
    await user.clear(screen.getByLabelText('Contact memo'))
    await user.type(screen.getByLabelText('Contact memo'), 'Updated memo.')
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
          memo: 'Updated memo.',
          status: 'active',
          kind: 'person',
          sender_resolution_mode: 'self',
          mailing_list_recipient_expression: null,
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

  it('shows unresolved From addresses and can request a prefill job', async () => {
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
                memo: null,
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
            memo: '',
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
            memo: null,
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
    expect(screen.getAllByText('not_started')).toHaveLength(3)

    await user.click(screen.getAllByRole('button', { name: 'Generate prefill' })[0])

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/contacts/unresolved-from-addresses/unknown.sender%40example.com/generate-prefill',
      expect.objectContaining({
        credentials: 'include',
        method: 'POST',
        body: JSON.stringify({ message_id: null }),
      }),
    )
    expect(await screen.findByText('Prefill job queued: job_contact_prefill_test')).toBeInTheDocument()

    await user.type(
      screen.getByLabelText('Display name for unknown.sender@example.com'),
      'Unknown Sender',
    )
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
          memo: '',
          status: 'active',
          kind: 'person',
          sender_resolution_mode: 'self',
          mailing_list_recipient_expression: null,
          tags: [],
          email_addresses: [
            { email_address: 'unknown.sender@example.com', is_primary: true },
          ],
        }),
      }),
    )
    expect(screen.queryByText('unknown.sender@example.com')).not.toBeInTheDocument()

    await user.type(
      screen.getByLabelText('Display name for list.sender@example.com'),
      'List Sender',
    )
    await user.click(
      screen.getByRole('button', { name: 'Create skipped contact for list.sender@example.com' }),
    )
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/contacts',
      expect.objectContaining({
        credentials: 'include',
        method: 'POST',
        body: JSON.stringify({
          display_name: 'List Sender',
          memo: '',
          status: 'skipped',
          kind: 'person',
          sender_resolution_mode: 'self',
          mailing_list_recipient_expression: null,
          tags: [],
          email_addresses: [
            { email_address: 'list.sender@example.com', is_primary: true },
          ],
        }),
      }),
    )
    expect(screen.queryByText('list.sender@example.com')).not.toBeInTheDocument()

    await user.selectOptions(
      screen.getByLabelText('Existing contact for existing.sender@example.com'),
      'contact_existing',
    )
    await user.click(
      screen.getByRole('button', {
        name: 'Add existing.sender@example.com to existing contact',
      }),
    )
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/contacts/contact_existing/email-addresses',
      expect.objectContaining({
        credentials: 'include',
        method: 'POST',
        body: JSON.stringify({
          email_address: 'existing.sender@example.com',
          is_primary: false,
        }),
      }),
    )
    expect(screen.queryByText('existing.sender@example.com')).not.toBeInTheDocument()
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
            memo: '',
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
          memo: '',
          status: 'active',
          kind: 'person',
          sender_resolution_mode: 'self',
          mailing_list_recipient_expression: null,
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
    expect(screen.getByLabelText('Contact memo')).toHaveValue('')
  })
})
