import type { AnchorHTMLAttributes, MouseEvent } from 'react'
import { t, type MessageKey } from './i18n'

function currentBrowserPath() {
  return `${window.location.pathname}${window.location.search}${window.location.hash}`
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

export function navigateTo(href: string, replace = false) {
  const nextUrl = withImplicitReturnTo(new URL(href, window.location.origin))
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

export function returnToOrFallback(fallback: string) {
  const returnTo = new URLSearchParams(window.location.search).get('return_to')
  if (returnTo === null || returnTo.trim() === '') {
    return fallback
  }
  try {
    const destination = new URL(returnTo, window.location.origin)
    if (
      destination.origin !== window.location.origin ||
      destination.pathname === window.location.pathname
    ) {
      return fallback
    }
    return `${destination.pathname}${destination.search}${destination.hash}`
  } catch {
    return fallback
  }
}

export function AppLink({
  href,
  onClick,
  target,
  ...props
}: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) {
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
    navigateTo(href)
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
  if (pathname === '/cases') return 30
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
    .map((item, index) => ({ item, index }))
    .sort((left, right) => {
      const rankDifference = topNavRank(left.item.href) - topNavRank(right.item.href)
      return rankDifference !== 0 ? rankDifference : left.index - right.index
    })
    .map(({ item }) => item)

  return (
    <nav aria-label={label} className={className}>
      {sortedItems.map((item) => (
        <AppLink href={item.href} key={`${item.href}:${item.labelKey ?? item.label ?? ''}`}>
          {item.label ?? (item.labelKey !== undefined ? t(item.labelKey) : item.href)}
        </AppLink>
      ))}
    </nav>
  )
}
