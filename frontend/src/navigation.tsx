import type { AnchorHTMLAttributes, MouseEvent } from 'react'

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
