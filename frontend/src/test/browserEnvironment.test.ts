import { describe, expect, it } from 'vitest'

describe('browser-compatible test environment', () => {
  it('provides DOMMatrix with real browser-style matrix operations', () => {
    const matrix = new DOMMatrix().translate(10, 20).scale(2, 3)

    expect(matrix.a).toBe(2)
    expect(matrix.d).toBe(3)
    expect(matrix.e).toBe(10)
    expect(matrix.f).toBe(20)
    const transformed = matrix.inverse().transformPoint({ x: 12, y: 23 })
    expect(transformed.x).toBeCloseTo(1)
    expect(transformed.y).toBeCloseTo(1)
  })

  it('evaluates the media queries used by the real application', () => {
    expect(window.matchMedia('(max-width: 720px)').matches).toBe(false)
    expect(window.matchMedia('(min-width: 720px)').matches).toBe(true)
  })
})
