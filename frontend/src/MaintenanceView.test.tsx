import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import MaintenanceView from './MaintenanceView'
import type { MaintenanceInitialData } from './MaintenanceView'

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
