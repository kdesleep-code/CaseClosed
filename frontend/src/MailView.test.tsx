import { StrictMode } from 'react'
import { render, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import MailView from './MailView'

function apiResponse(data: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify({ ok: true, data }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  window.history.pushState({}, '', '/')
})

it('does not reload prepared mail data when StrictMode reruns effects', async () => {
  const fetchMock = vi.fn((input: string | URL | Request) => {
    const path = input.toString()
    if (path === '/api/v1/google/gmail/status') {
      return apiResponse({
        auto_import: {
          last_success_at: null,
          last_run_at: null,
          last_error: null,
          unloaded_dates: [],
          last_imported_count: 0,
        },
      })
    }
    throw new Error(`Unexpected request: ${path}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  window.history.pushState({}, '', '/mail?date=2026-07-29')

  render(
    <StrictMode>
      <MailView
        initialData={{
          mails: [],
          mailDates: [],
          mailDayStats: {
            date: '2026-07-29',
            total_count: 0,
            received_count: 0,
            sent_count: 0,
          },
          nextCursor: null,
          activeTab: 'unprocessed',
          selectedDate: '2026-07-29',
          calendarMonth: '2026-07-29',
        }}
      />
    </StrictMode>,
  )

  await waitFor(() => expect(fetchMock).toHaveBeenCalled())
  const paths = fetchMock.mock.calls.map(([input]) => input.toString())
  expect(paths.some((path) => path.startsWith('/api/v1/mails?'))).toBe(false)
  expect(paths.some((path) => path.startsWith('/api/v1/mails/dates'))).toBe(false)
  expect(paths.some((path) => path.startsWith('/api/v1/mails/day-stats'))).toBe(false)
})
