export type MobileQuickSlot = {
  label: string
  href: string
}

const mobileQuickSlotStorageKey = 'caseclosed.mobileQuickSlot'

function normalizeHref(value: string) {
  const href = value.trim()
  if (href === '') return ''
  if (/^(https?:|mailto:|tel:)/i.test(href)) return href
  if (href === '/' || href.toLowerCase() === 'top') return '/m'
  const absolutePath = href.startsWith('/') ? href : `/${href}`
  if (absolutePath === '/mail') return '/m/mail'
  if (absolutePath === '/tasks') return '/m/tasks'
  if (absolutePath === '/calendar') return '/m/calendar'
  if (absolutePath === '/mobile') return '/m'
  if (absolutePath === '/mobile/settings') return '/m/settings'
  return absolutePath
}

function normalizeSlot(value: unknown): MobileQuickSlot | null {
  if (typeof value !== 'object' || value === null) return null
  const candidate = value as Partial<Record<keyof MobileQuickSlot, unknown>>
  const label = typeof candidate.label === 'string' ? candidate.label.trim() : ''
  const href = typeof candidate.href === 'string' ? normalizeHref(candidate.href) : ''
  if (label === '' || href === '') return null
  return { label, href }
}

export function readMobileQuickSlot(): MobileQuickSlot | null {
  try {
    const rawValue = window.localStorage.getItem(mobileQuickSlotStorageKey)
    if (rawValue === null) return null
    return normalizeSlot(JSON.parse(rawValue))
  } catch {
    return null
  }
}

export function writeMobileQuickSlot(slot: MobileQuickSlot | null) {
  try {
    if (slot === null) {
      window.localStorage.removeItem(mobileQuickSlotStorageKey)
      return
    }
    const normalizedSlot = normalizeSlot(slot)
    if (normalizedSlot === null) {
      window.localStorage.removeItem(mobileQuickSlotStorageKey)
      return
    }
    window.localStorage.setItem(mobileQuickSlotStorageKey, JSON.stringify(normalizedSlot))
  } catch {
    // Ignore localStorage failures on restricted browsers.
  }
}
