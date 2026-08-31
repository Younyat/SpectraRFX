import '@testing-library/jest-dom/vitest'

// jsdom has no layout engine -- every element measures 0x0, which makes
// recharts' ResponsiveContainer render an empty div (it refuses to draw a
// chart into a 0x0 box). Stub a fixed size so chart-primitive tests can
// actually assert on rendered SVG content, not just "did not crash".
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
// eslint-disable-next-line @typescript-eslint/no-explicit-any
;(globalThis as any).ResizeObserver = (globalThis as any).ResizeObserver ?? ResizeObserverStub

Object.defineProperty(HTMLElement.prototype, 'offsetWidth', { configurable: true, value: 600 })
Object.defineProperty(HTMLElement.prototype, 'offsetHeight', { configurable: true, value: 300 })
Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, value: 600 })
Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, value: 300 })
HTMLElement.prototype.getBoundingClientRect = () =>
  ({ width: 600, height: 300, top: 0, left: 0, right: 600, bottom: 300, x: 0, y: 0, toJSON() {} }) as DOMRect
