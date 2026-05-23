export const themeIds = ['warm-default', 'compact-work', 'high-contrast'] as const

export type ThemeId = (typeof themeIds)[number]

export const defaultThemeId: ThemeId = 'warm-default'

declare global {
  interface Window {
    CASECLOSED_THEME?: string
  }
}

function isThemeId(value: string | null | undefined): value is ThemeId {
  return themeIds.includes(value as ThemeId)
}

export function loadTheme(): ThemeId {
  const windowTheme = window.CASECLOSED_THEME
  if (isThemeId(windowTheme)) {
    return windowTheme
  }

  const storedTheme = window.localStorage.getItem('caseclosed.theme')
  if (isThemeId(storedTheme)) {
    return storedTheme
  }

  return defaultThemeId
}

export function applyTheme(themeId: string | null | undefined) {
  document.documentElement.dataset.theme = isThemeId(themeId)
    ? themeId
    : defaultThemeId
}

export function resetTheme() {
  applyTheme(loadTheme())
}

resetTheme()
