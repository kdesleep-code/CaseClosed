import type { AnchorHTMLAttributes, MouseEvent } from 'react'
import { t, type MessageKey } from './i18n'

export function navigateTo(href: string, replace = false) {
  const nextUrl = new URL(href, window.location.origin)
  if (nextUrl.origin !== window.location.origin) {
    window.location.href = href
    return
  }

  const nextPath = `${nextUrl.pathname}${nextUrl.search}${nextUrl.hash}`
  const currentPath = `${window.location.pathname}${window.location.search}${window.location.hash}`
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
  if (pathname === '/contacts' || pathname === '/contacts/pending') return 20
  if (pathname === '/cases') return 30
  if (pathname === '/tasks' || pathname === '/tasks/new') return 40
  if (pathname === '/calendar' || pathname === '/calendar/new') return 50
  if (pathname === '/files' || pathname === '/file-icons') return 60
  if (pathname === '/profile') return 70
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
