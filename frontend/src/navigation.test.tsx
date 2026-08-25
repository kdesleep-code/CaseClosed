import { afterEach, describe, expect, it } from 'vitest'

import { navigateTo, resolveTopNavHref } from './navigation'

afterEach(() => {
  window.history.replaceState({}, '', '/')
})

describe('resolveTopNavHref', () => {
  it('uses the standard Task list and restores the related Mail origin', () => {
    const mailOrigin = '/mail/mail_1?focus=mail_2&return_to=%2Fmail%3Ftab%3Dprocessed'
    window.history.replaceState(
      {},
      '',
      `/tasks/task_1?return_to=${encodeURIComponent(mailOrigin)}`,
    )

    expect(resolveTopNavHref('/tasks')).toBe('/tasks')
    expect(resolveTopNavHref('/mail')).toBe(mailOrigin)
  })

  it('keeps a restored detail URL exact instead of replacing its origin', () => {
    const mailOrigin = '/mail/mail_1?focus=mail_2'
    window.history.replaceState(
      {},
      '',
      `/tasks/task_1?return_to=${encodeURIComponent(mailOrigin)}`,
    )

    navigateTo(resolveTopNavHref('/mail'), false, false)

    expect(window.location.pathname + window.location.search).toBe(mailOrigin)
  })

  it('restores Mail search results', () => {
    window.history.replaceState(
      {},
      '',
      '/tasks/task_1?return_to=%2Fmail%3Fq%3Dquarterly%2520report%26tab%3Dprocessed',
    )

    expect(resolveTopNavHref('/mail')).toBe('/mail?q=quarterly%20report&tab=processed')
  })

  it('does not use the compose screen as the Mail button destination', () => {
    window.history.replaceState(
      {},
      '',
      '/tasks/task_1?return_to=%2Fmail%2Fcompose%3Fto%3Duser%2540example.com',
    )

    expect(resolveTopNavHref('/mail')).toBe('/mail')
  })

  it('restores Task list filters for the related Task button', () => {
    window.history.replaceState(
      {},
      '',
      '/tasks/task_1?return_to=%2Ftasks%3Fcase_id%3Dcase_1%26status%3Dnot_started',
    )

    expect(resolveTopNavHref('/tasks')).toBe('/tasks?case_id=case_1&status=not_started')
    expect(resolveTopNavHref('/mail')).toBe('/mail')
  })

  it('restores Calendar view state from an event page', () => {
    window.history.replaceState(
      {},
      '',
      '/calendar/events/event_1?return_to=%2Fcalendar%3Fdate%3D2026-07-21%26view%3Dweek',
    )

    expect(resolveTopNavHref('/calendar')).toBe('/calendar?date=2026-07-21&view=week')
    expect(resolveTopNavHref('/cases')).toBe('/cases')
  })

  it('restores same-path Contact list state when the detail is query based', () => {
    window.history.replaceState(
      {},
      '',
      '/contacts?contact_id=contact_1&return_to=%2Fcontacts%3Ftab%3Dorganization%26tag%3Dimportant',
    )

    expect(resolveTopNavHref('/contacts')).toBe('/contacts?tab=organization&tag=important')
  })

  it('restores Files list state from a file detail page', () => {
    window.history.replaceState(
      {},
      '',
      '/files/object_1?return_to=%2Ffiles%3Fcase_id%3Dcase_1',
    )

    expect(resolveTopNavHref('/files')).toBe('/files?case_id=case_1')
  })

  it('does not rewrite a detail or editor button', () => {
    window.history.replaceState(
      {},
      '',
      '/calendar/events/event_1/edit?return_to=%2Fcalendar%3Fdate%3D2026-07-21',
    )

    expect(resolveTopNavHref('/calendar/events/event_1')).toBe('/calendar/events/event_1')
  })

  it('uses the original href when there is no return_to', () => {
    window.history.replaceState({}, '', '/tasks/task_1')
    expect(resolveTopNavHref('/tasks')).toBe('/tasks')
  })

  it('restores a dictionary detail for the related dictionary button', () => {
    window.history.replaceState(
      {},
      '',
      '/settings?return_to=%2Fdictionary%2Fentry_1',
    )

    expect(resolveTopNavHref('/dictionary')).toBe('/dictionary/entry_1')
  })
})
