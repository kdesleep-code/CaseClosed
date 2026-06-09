import { describe, expect, it } from 'vitest'

import {
  caseRoleSelectorSuggestions,
  resolveContactSelectorList,
  resolveRecipientAddressList,
} from './contactSelectors'
import type { Contact } from './phase3Api'
import type { CaseItem, CaseStakeholder } from './phase7Api'

function contact(
  id: string,
  displayName: string,
  emailAddress: string,
  tags: string[],
): Contact {
  return {
    id,
    display_name: displayName,
    avatar_url: null,
    user_memo: null,
    ai_memo: null,
    status: 'active',
    kind: 'person',
    sender_resolution_mode: 'self',
    mailing_list_recipient_expression: null,
    mail_importance_rule_action: 'llm',
    mail_importance_rule_importance: null,
    mail_importance_rule_instruction: null,
    inbound_message_count: 0,
    latest_received_at: null,
    tags,
    email_addresses: [
      {
        id: `${id}_email`,
        email_address: emailAddress,
        normalized_email_address: emailAddress.toLowerCase(),
        resolution_status: 'linked',
        status: 'active',
        is_primary: true,
        source: 'manual',
        first_seen_at: null,
        last_seen_at: null,
      },
    ],
    created_at: '2026-06-03T10:00:00+09:00',
    updated_at: '2026-06-03T10:00:00+09:00',
    version: 1,
  }
}

describe('contact selector resolution', () => {
  const contacts = [
    contact('contact_student', 'Student One', 'student.one@example.com', [
      'student',
      'lab-member',
    ]),
    contact('contact_alumni', 'Alumni One', 'alumni.one@example.com', [
      'student',
      'lab-alumni',
    ]),
    contact('contact_faculty', 'Faculty One', 'faculty.one@example.com', [
      'faculty',
      'lab-member',
    ]),
  ]

  it('expands contact tag expressions to primary email addresses', () => {
    expect(
      resolveRecipientAddressList('{student&!lab-alumni}, direct@example.com', contacts),
    ).toEqual(['student.one@example.com', 'direct@example.com'])
  })

  it('expands contact tag expressions to stakeholder contacts', () => {
    expect(resolveContactSelectorList('lab-member', contacts).map((item) => item.id)).toEqual([
      'contact_student',
      'contact_faculty',
    ])
  })

  it('expands case role selectors to primary email addresses', () => {
    const caseItem: CaseItem = {
      id: 'case_annual_review',
      genre_id: null,
      name: 'Annual Review',
      description: null,
      open_when_date: null,
      open_when_text: null,
      closed_when_text: null,
      progress_status: 'not_started',
      ball_status: 'user',
      closed_at: null,
      archived_at: null,
      is_system_case: false,
      system_case_key: null,
      tags: [],
      mail_count: 0,
      open_task_count: 0,
      overdue_task_count: 0,
      file_count: 0,
      storage_directory_id: 'directory_case_annual_review',
      next_task: null,
      next_calendar_event: null,
      created_at: '2026-06-03T10:00:00+09:00',
      updated_at: '2026-06-03T10:00:00+09:00',
      version: 1,
    }
    const stakeholders: CaseStakeholder[] = [
      {
        id: 'stakeholder_student',
        case_id: caseItem.id,
        contact_id: 'contact_student',
        contact_display_name: 'Student One',
        contact_avatar_url: null,
        contact_primary_email: 'student.one@example.com',
        role: 'reviewer',
        sort_order: 0,
        created_at: '2026-06-03T10:00:00+09:00',
        updated_at: '2026-06-03T10:00:00+09:00',
        version: 1,
      },
      {
        id: 'stakeholder_faculty',
        case_id: caseItem.id,
        contact_id: 'contact_faculty',
        contact_display_name: 'Faculty One',
        contact_avatar_url: null,
        contact_primary_email: 'faculty.one@example.com',
        role: 'owner',
        sort_order: 1,
        created_at: '2026-06-03T10:00:00+09:00',
        updated_at: '2026-06-03T10:00:00+09:00',
        version: 1,
      },
    ]

    expect(
      resolveRecipientAddressList('Case:Annual Review:reviewer', contacts, [
        { case: caseItem, stakeholders },
      ]),
    ).toEqual(['student.one@example.com'])
    expect(caseRoleSelectorSuggestions('case:', [{ case: caseItem, stakeholders }])).toEqual([
      { label: 'Annual Review', value: 'Case:Annual Review:' },
    ])
    expect(
      caseRoleSelectorSuggestions('Case:Annual Review:', [{ case: caseItem, stakeholders }]),
    ).toEqual([
      { label: 'ALL', value: 'Case:Annual Review:ALL' },
      { label: 'owner', value: 'Case:Annual Review:owner' },
      { label: 'reviewer', value: 'Case:Annual Review:reviewer' },
    ])
    expect(
      resolveRecipientAddressList('Case:Annual Review:ALL', contacts, [
        { case: caseItem, stakeholders },
      ]),
    ).toEqual(['student.one@example.com', 'faculty.one@example.com'])
  })
})
