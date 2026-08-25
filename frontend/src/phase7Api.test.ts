import { describe, expect, it } from 'vitest'

import { isCaseAvailableForMailAssignment } from './phase7Api'
import type { CaseItem } from './phase7Api'

function caseItem(overrides: Partial<CaseItem> = {}): CaseItem {
  return {
    id: 'case_1',
    genre_id: null,
    name: 'Future Case',
    description: null,
    open_when_date: '2099-01-01',
    open_when_text: null,
    closed_when_text: null,
    progress_status: 'not_started',
    ball_status: 'date_wait',
    closed_at: null,
    archived_at: null,
    is_system_case: false,
    system_case_key: null,
    tags: [],
    mail_count: 0,
    open_task_count: 0,
    overdue_task_count: 0,
    file_count: 0,
    storage_directory_id: 'directory_1',
    handover_storage_directory_id: 'directory_handover_1',
    next_task: null,
    next_calendar_event: null,
    created_at: '2026-08-24T00:00:00+09:00',
    updated_at: '2026-08-24T00:00:00+09:00',
    version: 1,
    ...overrides,
  }
}

describe('isCaseAvailableForMailAssignment', () => {
  it('includes a Case whose start date has not arrived', () => {
    expect(isCaseAvailableForMailAssignment(caseItem())).toBe(true)
  })

  it('continues to exclude completed and archived Cases', () => {
    expect(
      isCaseAvailableForMailAssignment(
        caseItem({ closed_at: '2026-08-24T01:00:00+09:00' }),
      ),
    ).toBe(false)
    expect(
      isCaseAvailableForMailAssignment(
        caseItem({ archived_at: '2026-08-24T01:00:00+09:00' }),
      ),
    ).toBe(false)
  })
})
