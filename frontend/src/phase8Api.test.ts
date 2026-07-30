import { afterEach, describe, expect, it, vi } from 'vitest'
import { freezeTask, unfreezeTask } from './phase8Api'

afterEach(() => {
  vi.unstubAllGlobals()
})

function taskResponse(status: string) {
  return new Response(
    JSON.stringify({ ok: true, data: { task: { id: 'task-freeze', status } } }),
    { status: 200, headers: { 'Content-Type': 'application/json' } },
  )
}

describe('Task freeze API', () => {
  it('calls the dedicated freeze endpoint', async () => {
    const fetchMock = vi.fn(() => Promise.resolve(taskResponse('frozen')))
    vi.stubGlobal('fetch', fetchMock)

    await expect(freezeTask('task-freeze')).resolves.toMatchObject({ status: 'frozen' })
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/tasks/task-freeze/freeze', {
      credentials: 'include',
      method: 'POST',
    })
  })

  it('calls the dedicated unfreeze endpoint', async () => {
    const fetchMock = vi.fn(() => Promise.resolve(taskResponse('in_progress')))
    vi.stubGlobal('fetch', fetchMock)

    await expect(unfreezeTask('task-freeze')).resolves.toMatchObject({ status: 'in_progress' })
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/tasks/task-freeze/unfreeze', {
      credentials: 'include',
      method: 'POST',
    })
  })
})
