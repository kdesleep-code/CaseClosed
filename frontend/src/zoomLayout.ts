const compactClassName = 'ui-zoom-compact'

const collisionContainerSelectors = [
  '.maintenance-header',
  '.contacts-header',
  '.storage-header',
  '.top-header',
  '.mail-tabs',
  '.mail-tab-gadgets',
  '.mail-list-heading',
  '.calendar-heading-actions',
  '.case-gadget-heading-row',
]

function isVisible(element: Element): element is HTMLElement {
  if (!(element instanceof HTMLElement)) {
    return false
  }
  const style = window.getComputedStyle(element)
  return (
    style.display !== 'none' &&
    style.visibility !== 'hidden' &&
    element.getClientRects().length > 0
  )
}

function layoutChildren(container: Element): HTMLElement[] {
  const children: HTMLElement[] = []
  for (const child of container.children) {
    if (!(child instanceof HTMLElement)) {
      continue
    }
    if (window.getComputedStyle(child).display === 'contents') {
      children.push(...layoutChildren(child))
    } else if (isVisible(child)) {
      children.push(child)
    }
  }
  return children
}

export function rectanglesOverlap(left: DOMRect, right: DOMRect): boolean {
  return (
    Math.min(left.right, right.right) - Math.max(left.left, right.left) > 1 &&
    Math.min(left.bottom, right.bottom) - Math.max(left.top, right.top) > 1
  )
}

export function directChildrenOverlap(container: Element): boolean {
  const children = layoutChildren(container)
  for (let leftIndex = 0; leftIndex < children.length; leftIndex += 1) {
    const left = children[leftIndex]
    if (window.getComputedStyle(left).position === 'absolute') {
      continue
    }
    for (let rightIndex = leftIndex + 1; rightIndex < children.length; rightIndex += 1) {
      const right = children[rightIndex]
      if (window.getComputedStyle(right).position === 'absolute') {
        continue
      }
      if (rectanglesOverlap(left.getBoundingClientRect(), right.getBoundingClientRect())) {
        return true
      }
    }
  }
  return false
}

export function shouldUseCompactLayout(viewportWidth: number): boolean {
  if (viewportWidth <= 1024) {
    return true
  }
  return collisionContainerSelectors.some((selector) =>
    [...document.querySelectorAll(selector)].some(directChildrenOverlap),
  )
}

export function installZoomLayoutGuard(): () => void {
  let animationFrame = 0
  let collisionCompact = false
  let previousViewportWidth = window.visualViewport?.width ?? window.innerWidth

  const update = () => {
    animationFrame = 0
    const viewportWidth = window.visualViewport?.width ?? window.innerWidth
    const widthChanged = Math.abs(viewportWidth - previousViewportWidth) > 48
    const widthCompact = viewportWidth <= 1024
    if (widthChanged && !widthCompact) {
      collisionCompact = false
    }
    if (!widthCompact && shouldUseCompactLayout(viewportWidth)) {
      collisionCompact = true
    }
    document.documentElement.classList.toggle(
      compactClassName,
      widthCompact || collisionCompact,
    )
    previousViewportWidth = viewportWidth
  }
  const schedule = () => {
    if (animationFrame === 0) {
      animationFrame = window.requestAnimationFrame(update)
    }
  }

  window.addEventListener('resize', schedule)
  window.visualViewport?.addEventListener('resize', schedule)
  const mutationObserver = new MutationObserver(schedule)
  mutationObserver.observe(document.body, { childList: true, subtree: true })
  const resizeObserver = 'ResizeObserver' in window ? new ResizeObserver(schedule) : null
  resizeObserver?.observe(document.body)
  schedule()

  return () => {
    window.removeEventListener('resize', schedule)
    window.visualViewport?.removeEventListener('resize', schedule)
    mutationObserver.disconnect()
    resizeObserver?.disconnect()
    if (animationFrame !== 0) {
      window.cancelAnimationFrame(animationFrame)
    }
    document.documentElement.classList.remove(compactClassName)
  }
}
