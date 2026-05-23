import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'

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
    expect(screen.getByRole('button', { name: /Running jobs 1/ })).toBeInTheDocument()
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
        'ジョブの実行に失敗しました。理由: ReviewFailure - Review sample failure.',
      ),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry job_failed' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry job_failed' })).toHaveAttribute(
      'title',
      'この failed job を pending に戻し、Worker が再実行できる状態にします。',
    )
    expect(await screen.findByRole('row', { name: /op_unknown/ })).toHaveTextContent(
      'gmail_send',
    )
    expect(
      screen.getByText(
        '外部操作の成否を自動では確定できませんでした。理由: Network response was lost.',
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Mark op_unknown succeeded' }),
    ).toHaveAttribute(
      'title',
      '外部サービス側で成功済みと確認した結果を記録します。この操作は再実行しません。',
    )
    expect(
      screen.getByRole('button', { name: 'Mark op_unknown failed' }),
    ).toHaveAttribute(
      'title',
      '手動確認で失敗と判断した結果を記録します。',
    )
    expect(screen.getByRole('button', { name: 'Cancel op_unknown' })).toHaveAttribute(
      'title',
      '手動確認後、この外部操作をキャンセル扱いにします。',
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
