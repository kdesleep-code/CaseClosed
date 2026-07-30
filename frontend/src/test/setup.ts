import '@testing-library/jest-dom/vitest'
import { DOMMatrix as CanvasDOMMatrix } from '@napi-rs/canvas'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// jsdom does not provide the geometry API that browsers expose to PDF.js.
// Use PDF.js's Node canvas implementation so tests exercise real matrix math.
if (typeof globalThis.DOMMatrix === 'undefined') {
  Object.defineProperty(globalThis, 'DOMMatrix', {
    configurable: true,
    writable: true,
    value: CanvasDOMMatrix,
  })
}

function mediaQueryMatches(query: string) {
  return query.split(',').some((alternative) => {
    const maxWidths = [...alternative.matchAll(/\(max-width:\s*(\d+(?:\.\d+)?)px\)/g)]
    const minWidths = [...alternative.matchAll(/\(min-width:\s*(\d+(?:\.\d+)?)px\)/g)]
    const widthMatches =
      maxWidths.every((match) => window.innerWidth <= Number(match[1])) &&
      minWidths.every((match) => window.innerWidth >= Number(match[1]))
    const hasCoarsePointer = navigator.maxTouchPoints > 0
    const pointerMatches =
      (!alternative.includes('(pointer: coarse)') || hasCoarsePointer) &&
      (!alternative.includes('(pointer: fine)') || !hasCoarsePointer)

    return widthMatches && pointerMatches
  })
}

if (typeof window.matchMedia === 'undefined') {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value: (query: string): MediaQueryList => ({
      get matches() {
        return mediaQueryMatches(query)
      },
      media: query,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    }),
  })
}

afterEach(() => {
  cleanup()
})
