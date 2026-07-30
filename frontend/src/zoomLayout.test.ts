import { afterEach, describe, expect, it } from 'vitest'

import {
  directChildrenOverlap,
  rectanglesOverlap,
  shouldUseCompactLayout,
} from './zoomLayout'

afterEach(() => {
  document.body.replaceChildren()
  document.documentElement.classList.remove('ui-zoom-compact')
})

function setRect(element: HTMLElement, left: number, top: number, right: number, bottom: number) {
  const rect = {
    bottom,
    height: bottom - top,
    left,
    right,
    toJSON: () => ({}),
    top,
    width: right - left,
    x: left,
    y: top,
  } as DOMRect
  element.getClientRects = () =>
    ({ 0: rect, item: () => rect, length: 1, [Symbol.iterator]: function* () { yield rect } }) as DOMRectList
  element.getBoundingClientRect = () => rect
}

describe('browser zoom layout guard', () => {
  it('recognizes actual rectangle intersections', () => {
    expect(
      rectanglesOverlap(
        { left: 0, top: 0, right: 100, bottom: 50 } as DOMRect,
        { left: 80, top: 10, right: 180, bottom: 60 } as DOMRect,
      ),
    ).toBe(true)
    expect(
      rectanglesOverlap(
        { left: 0, top: 0, right: 100, bottom: 50 } as DOMRect,
        { left: 110, top: 0, right: 180, bottom: 50 } as DOMRect,
      ),
    ).toBe(false)
  })

  it('detects overlapping direct controls in a monitored header', () => {
    const header = document.createElement('header')
    const title = document.createElement('div')
    const navigation = document.createElement('nav')
    setRect(title, 0, 0, 180, 50)
    setRect(navigation, 160, 10, 320, 60)
    header.append(title, navigation)
    document.body.append(header)

    expect(directChildrenOverlap(header)).toBe(true)
  })

  it('uses compact mode for a zoom-reduced viewport or a detected collision', () => {
    expect(shouldUseCompactLayout(1024)).toBe(true)
    expect(shouldUseCompactLayout(1400)).toBe(false)

    const header = document.createElement('header')
    header.className = 'maintenance-header'
    const title = document.createElement('div')
    const navigation = document.createElement('nav')
    setRect(title, 0, 0, 220, 50)
    setRect(navigation, 190, 0, 360, 50)
    header.append(title, navigation)
    document.body.append(header)

    expect(shouldUseCompactLayout(1400)).toBe(true)
  })
})
