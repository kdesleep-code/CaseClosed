import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import MaintenanceView from './MaintenanceView'
import type { MaintenanceInitialData } from './MaintenanceView'

function apiResponse(data: unknown) {
  return Promise.resolve({
    ok: true,
    status: 200,
    json: async () => ({ ok: true, data }),
  } as Response)
}

afterEach(() => {
  vi.unstubAllGlobals()
})

const initialData: MaintenanceInitialData = {
  status: {
    job_accepting: true,
    running_jobs: 1,
    pending_write_requests: 0,
    external_unknown_count: 0,
    backup_status: 'not_configured',
    system_health: {
      status: 'healthy',
      checked_at: '2026-07-10T12:00:00+09:00',
      queue: {
        pending: 3,
        scheduled: 2,
        running: 1,
        failed: 0,
        stale: 0,
      },
      worker: {
        enabled: true,
        configured_workers: 2,
        alive_workers: 2,
        status: 'healthy',
        last_job_activity_at: '2026-07-10T11:59:00+09:00',
      },
      gmail_auto_import: {
        enabled: true,
        connected: true,
        status: 'healthy',
        interval_minutes: 10,
        last_run_at: '2026-07-10T11:50:00+09:00',
        last_success_at: '2026-07-10T11:50:00+09:00',
        last_error: null,
      },
      calendar_auto_sync: {
        enabled: true,
        connected: true,
        status: 'healthy',
        interval_minutes: 60,
        last_run_at: '2026-07-10T11:00:00+09:00',
        last_success_at: '2026-07-10T11:00:00+09:00',
        last_error: null,
      },
    },
  },
  jobs: [],
  operations: [],
  pendingMails: [],
}

describe('MaintenanceView system health', () => {
  it('shows worker, queue, and automatic integration health', () => {
    render(<MaintenanceView initialData={initialData} />)

    expect(screen.getByRole('heading', { name: 'System health' })).toBeInTheDocument()
    expect(screen.getAllByText('Healthy')).toHaveLength(4)
    expect(screen.getByText('2 of 2 running')).toBeInTheDocument()
    expect(screen.getByText('Gmail auto import')).toBeInTheDocument()
    expect(screen.getByText('Calendar auto sync')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
  })
})

describe('MaintenanceView password management', () => {
  it('changes both the full login and simple page passwords', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const path = input.toString()
      if (path === '/api/v1/maintenance/usb-backups') {
        return apiResponse({ devices: [] })
      }
      if (path === '/api/v1/auth/password') {
        return apiResponse({ password_type: 'full', invalidated_sessions: 2 })
      }
      if (path === '/api/v1/auth/low-mail-review-password') {
        return apiResponse({
          password_type: 'low_mail_review',
          invalidated_sessions: 1,
        })
      }
      throw new Error()
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<MaintenanceView initialData={initialData} />)

    await user.click(screen.getByRole('tab', { name: 'Security' }))
    const fullForm = screen.getByRole('form', { name: 'Login password' })
    const fullCard = fullForm.closest('article') as HTMLElement
    expect(within(fullForm).getByLabelText('New login password')).toHaveAttribute(
      'minLength',
      '8',
    )
    await user.type(
      within(fullForm).getByLabelText('Current login password'),
      'current-password',
    )
    await user.type(
      within(fullForm).getByLabelText('New login password'),
      'new-login-password',
    )
    await user.type(
      within(fullForm).getByLabelText('Confirm new password'),
      'new-login-password',
    )
    await user.click(within(fullForm).getByRole('button', { name: 'Change password' }))

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/auth/password',
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({
          current_password: 'current-password',
          new_password: 'new-login-password',
        }),
      }),
    )
    expect(
      await within(fullCard).findByText(
        'Password changed. Signed out 2 other session(s).',
      ),
    ).toBeInTheDocument()

    const reviewForm = screen.getByRole('form', { name: 'Simple page password' })
    const reviewCard = reviewForm.closest('article') as HTMLElement
    await user.type(
      within(reviewForm).getByLabelText('Current login password'),
      'current-password',
    )
    await user.type(
      within(reviewForm).getByLabelText('New simple page password'),
      'new-review-password',
    )
    await user.type(
      within(reviewForm).getByLabelText('Confirm new password'),
      'new-review-password',
    )
    await user.click(
      within(reviewForm).getByRole('button', { name: 'Change password' }),
    )

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/auth/low-mail-review-password',
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({
          current_password: 'current-password',
          new_password: 'new-review-password',
        }),
      }),
    )
    expect(
      await within(reviewCard).findByText(
        'Password changed. Signed out 1 other session(s).',
      ),
    ).toBeInTheDocument()
  })

  it('does not submit mismatched confirmation values', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const path = input.toString()
      if (path === '/api/v1/maintenance/usb-backups') {
        return apiResponse({ devices: [] })
      }
      throw new Error()
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<MaintenanceView initialData={initialData} />)

    await user.click(screen.getByRole('tab', { name: 'Security' }))
    const form = screen.getByRole('form', { name: 'Login password' })
    const card = form.closest('article') as HTMLElement
    await user.type(within(form).getByLabelText('Current login password'), 'current-password')
    await user.type(within(form).getByLabelText('New login password'), 'new-login-password')
    await user.type(within(form).getByLabelText('Confirm new password'), 'different-password')
    await user.click(within(form).getByRole('button', { name: 'Change password' }))

    expect(
      within(card).getByRole('alert'),
    ).toHaveTextContent('The new password and confirmation do not match.')
    expect(fetchMock).not.toHaveBeenCalledWith(
      '/api/v1/auth/password',
      expect.anything(),
    )
  })
})
