import { afterEach, describe, expect, it } from 'vitest'

import { applyTheme, defaultThemeId, resetTheme } from './theme'

describe('theme presets', () => {
  afterEach(() => {
    window.localStorage.clear()
    delete window.CASECLOSED_THEME
    resetTheme()
  })

  it('uses the warm default theme when no override exists', () => {
    resetTheme()

    expect(document.documentElement.dataset.theme).toBe(defaultThemeId)
  })

  it('applies a supported theme from local storage', () => {
    window.localStorage.setItem('caseclosed.theme', 'compact-work')
    resetTheme()

    expect(document.documentElement.dataset.theme).toBe('compact-work')
  })

  it('ignores unsupported theme ids', () => {
    applyTheme('not-a-theme')

    expect(document.documentElement.dataset.theme).toBe(defaultThemeId)
  })
})
