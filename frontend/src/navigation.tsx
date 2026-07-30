import type { AnchorHTMLAttributes, MouseEvent } from 'react'
import { t, type MessageKey } from './i18n'

function currentBrowserPath() {
  return window.location.pathname + window.location.search + window.location.hash
}

function shouldAttachReturnTo(nextUrl: URL) {
  if (nextUrl.origin !== window.location.origin || nextUrl.searchParams.has('return_to')) {
    return false
  }

  const nextPath = `${nextUrl.pathname}${nextUrl.search}${nextUrl.hash}`
  const currentPath = currentBrowserPath()
  if (nextPath === currentPath || currentPath === '/') {
    return false
  }

  if (nextUrl.pathname.startsWith('/mail/review')) return false
  if (nextUrl.pathname === '/mail/compose') return true
  if (nextUrl.pathname.startsWith('/mail/') && nextUrl.pathname !== '/mail/action-needed') {
    return true
  }
  if (nextUrl.pathname === '/calendar/new') return true
  if (nextUrl.pathname.startsWith('/calendar/events/')) return true
  if (nextUrl.pathname === '/tasks/new' || nextUrl.pathname.startsWith('/tasks/')) return true
  if (nextUrl.pathname === '/cases/new' || nextUrl.pathname.startsWith('/cases/')) return true
  if (nextUrl.pathname.startsWith('/files/')) return true
  if (
    nextUrl.pathname === '/contacts' &&
    (nextUrl.searchParams.has('contact_id') || nextUrl.searchParams.has('new_email'))
  ) {
    return true
  }
  return false
}

function withImplicitReturnTo(nextUrl: URL) {
  if (!shouldAttachReturnTo(nextUrl)) {
    return nextUrl
  }
  const withReturnTo = new URL(nextUrl.toString())
  withReturnTo.searchParams.set('return_to', currentBrowserPath())
  return withReturnTo
}

export function navigateTo(href: string, replace = false, attachImplicitReturnTo = true) {
  const requestedUrl = new URL(href, window.location.origin)
  const nextUrl = attachImplicitReturnTo ? withImplicitReturnTo(requestedUrl) : requestedUrl
  if (nextUrl.origin !== window.location.origin) {
    window.location.href = href
    return
  }

  const nextPath = `${nextUrl.pathname}${nextUrl.search}${nextUrl.hash}`
  const currentPath = currentBrowserPath()
  if (nextPath === currentPath) {
    return
  }

  const navigationEvent = new CustomEvent('caseclosed:navigate', {
    cancelable: true,
    detail: { path: nextPath, replace },
  })
  if (!window.dispatchEvent(navigationEvent)) {
    return
  }

  if (replace) {
    window.history.replaceState({}, '', nextPath)
  } else {
    window.history.pushState({}, '', nextPath)
  }
  window.dispatchEvent(new Event('popstate'))
}

export function returnToFromLocation() {
  const returnTo = new URLSearchParams(window.location.search).get('return_to')
  if (returnTo === null || returnTo.trim() === '') {
    return null
  }
  try {
    const destination = new URL(returnTo, window.location.origin)
    const destinationPath = destination.pathname + destination.search + destination.hash
    if (
      destination.origin !== window.location.origin ||
      destinationPath === currentBrowserPath()
    ) {
      return null
    }
    return destinationPath
  } catch {
    return null
  }
}

export function naturalReturnTargetFromLocation() {
  const pathname = window.location.pathname
  if (pathname === '/mail/compose' || (pathname.startsWith('/mail/') && pathname !== '/mail/action-needed')) {
    return '/mail'
  }
  if (pathname === '/calendar/new' || pathname.startsWith('/calendar/events/')) {
    return '/calendar'
  }
  if (pathname === '/tasks/new' || pathname.startsWith('/tasks/')) {
    return '/tasks'
  }
  if (pathname === '/cases/new' || pathname.startsWith('/cases/')) {
    return '/cases'
  }
  if (pathname.startsWith('/files/')) {
    return '/files'
  }
  return null
}

export function returnToOrFallback(fallback: string) {
  const returnTo = new URLSearchParams(window.location.search).get('return_to')
  if (returnTo === null || returnTo.trim() === '') {
    return fallback
  }
  try {
    const destination = new URL(returnTo, window.location.origin)
    const destinationPath = destination.pathname + destination.search + destination.hash
    if (
      destination.origin !== window.location.origin ||
      destinationPath === currentBrowserPath()
    ) {
      return fallback
    }
    return destinationPath
  } catch {
    return fallback
  }
}

const standardNavigationAreas: Record<string, string> = {
  '/': 'top',
  '/academic-calendar': 'academic-calendar',
  '/bookshelf': 'bookshelf',
  '/calendar': 'calendar',
  '/cases': 'cases',
  '/case-auto-assign-rules': 'cases',
  '/contacts': 'contacts',
  '/contact-auto-tag-rules': 'contacts',
  '/extensions': 'extensions',
  '/external-tools': 'external-tools',
  '/files': 'files',
  '/follow-ups': 'follow-ups',
  '/logs': 'logs',
  '/mail': 'mail',
  '/maintenance': 'maintenance',
  '/manual': 'manual',
  '/papers': 'papers',
  '/pomodoro': 'pomodoro',
  '/profile': 'profile',
  '/settings': 'settings',
  '/tasks': 'tasks',
  '/today': 'today',
  '/tomorrow': 'tomorrow',
}

function navigationAreaForPathname(pathname: string) {
  if (pathname === '/mail/action-needed') return 'mail'
  if (
    /^\/mail\/[^/]+$/.test(pathname) &&
    pathname !== '/mail/compose' &&
    pathname !== '/mail/review'
  ) return 'mail'
  if (pathname === '/contacts/pending') return 'contacts'
  if (
    pathname === '/calendar/conflicts' ||
    pathname === '/calendar/new' ||
    pathname.startsWith('/calendar/events/')
  ) {
    return 'calendar'
  }
  if (pathname === '/tasks/new' || pathname.startsWith('/tasks/')) return 'tasks'
  if (pathname === '/cases/new' || pathname === '/case-tool-icons' || pathname === '/case-auto-assign-rules' || pathname.startsWith('/cases/')) {
    return 'cases'
  }
  if (pathname === '/file-icons' || pathname.startsWith('/files/')) return 'files'
  if (pathname === '/bookshelf/tag-hierarchy' || pathname.startsWith('/bookshelf/')) return 'bookshelf'
  if (pathname === '/paper-journal-icons' || pathname.startsWith('/papers/')) return 'papers'
  if (pathname === '/extensions/help' || pathname === '/extensions/launch') return 'extensions'
  return standardNavigationAreas[pathname] ?? null
}

export function resolveTopNavHref(href: string) {
  const returnTo = returnToFromLocation()
  if (returnTo === null) return href

  try {
    const standardDestination = new URL(href, window.location.origin)
    if (standardDestination.origin !== window.location.origin) return href

    const destinationArea = standardNavigationAreas[standardDestination.pathname]
    if (destinationArea === undefined) return href

    const returnDestination = new URL(returnTo, window.location.origin)
    return navigationAreaForPathname(returnDestination.pathname) === destinationArea
      ? returnTo
      : href
  } catch {
    return href
  }
}

export function AppLink({
  href,
  onClick,
  preserveReturnTo = false,
  target,
  ...props
}: AnchorHTMLAttributes<HTMLAnchorElement> & {
  href: string
  preserveReturnTo?: boolean
}) {
  function handleClick(event: MouseEvent<HTMLAnchorElement>) {
    onClick?.(event)
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.altKey ||
      event.ctrlKey ||
      event.shiftKey ||
      target !== undefined
    ) {
      return
    }

    event.preventDefault()
    navigateTo(href, false, !preserveReturnTo)
  }

  return <a href={href} onClick={handleClick} target={target} {...props} />
}

export type TopNavItem = {
  href: string
  label?: string
  labelKey?: MessageKey
}

function topNavRank(href: string) {
  let pathname = href
  try {
    pathname = new URL(href, window.location.origin).pathname
  } catch {
    pathname = href.split(/[?#]/, 1)[0] ?? href
  }
  if (pathname === '/') return 0
  if (pathname === '/mail' || pathname === '/mail/action-needed' || pathname === '/mail/compose') {
    return 10
  }
  if (pathname === '/today' || pathname === '/tomorrow') return 5
  if (pathname === '/follow-ups') return 15
  if (pathname === '/contacts' || pathname === '/contacts/pending') return 20
  if (pathname === '/cases' || pathname === '/case-auto-assign-rules') return 30
  if (pathname === '/tasks' || pathname === '/tasks/new') return 40
  if (pathname === '/calendar' || pathname === '/calendar/new') return 50
  if (pathname === '/academic-calendar') return 55
  if (pathname === '/files' || pathname === '/file-icons') return 60
  if (pathname === '/external-tools') return 65
  if (pathname === '/extensions' || pathname.startsWith('/extensions/')) return 66
  if (pathname === '/profile') return 70
  if (pathname === '/settings') return 75
  if (pathname === '/logs') return 80
  if (pathname === '/maintenance') return 90
  return 100
}

export function TopNav({
  ariaLabel,
  ariaLabelKey,
  className = 'maintenance-nav',
  items,
}: {
  ariaLabel?: string
  ariaLabelKey?: MessageKey
  className?: string
  items: TopNavItem[]
}) {
  const label = ariaLabel ?? (ariaLabelKey !== undefined ? t(ariaLabelKey) : undefined)
  const sortedItems = items
    .map((item, index) => ({ item, index, resolvedHref: resolveTopNavHref(item.href) }))
    .sort((left, right) => {
      const rankDifference = topNavRank(left.item.href) - topNavRank(right.item.href)
      return rankDifference !== 0 ? rankDifference : left.index - right.index
    })

  return (
    <nav aria-label={label} className={className}>
      {sortedItems.map(({ item, resolvedHref }) => (
        <AppLink
          href={resolvedHref}
          key={`${item.href}:${item.labelKey ?? item.label ?? ''}`}
          preserveReturnTo={resolvedHref !== item.href}
        >
          {item.label ?? (item.labelKey !== undefined ? t(item.labelKey) : item.href)}
        </AppLink>
      ))}
    </nav>
  )
}
