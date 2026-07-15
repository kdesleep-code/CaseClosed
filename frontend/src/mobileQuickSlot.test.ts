import { beforeEach, describe, expect, it, vi } from 'vitest'
import { loadMobileQuickSlot } from './mobileQuickSlot'

describe('mobile quick slot persistence', () => {
  beforeEach(() => {
    window.localStorage.clear()
    vi.restoreAllMocks()
  })

  it('migrates an existing local slot to the backend when the backend is empty', async () => {
    window.localStorage.setItem(
      'caseclosed.mobileQuickSlot',
      JSON.stringify({ label: 'Mail', href: '/mail' }),
    )
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        ok: true,
        data: { slot: null },
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        ok: true,
        data: { slot: { label: 'Mail', href: '/m/mail' } },
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(loadMobileQuickSlot()).resolves.toEqual({
      label: 'Mail',
      href: '/m/mail',
    })
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({
      label: 'Mail',
      href: '/m/mail',
    })
  })
})
