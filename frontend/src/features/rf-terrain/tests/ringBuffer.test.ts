import { describe, expect, it } from 'vitest';
import { createRingBuffer } from '../engine/ringBuffer';

describe('createRingBuffer', () => {
  it('never grows past its declared capacity', () => {
    const buffer = createRingBuffer<number>(3);
    for (let i = 0; i < 100; i += 1) {
      buffer.push(i);
    }
    expect(buffer.size).toBe(3);
    expect(buffer.toChronologicalArray()).toHaveLength(3);
  });

  it('wraps correctly, overwriting the oldest entry first', () => {
    const buffer = createRingBuffer<number>(3);
    [0, 1, 2, 3, 4].forEach((value) => buffer.push(value));
    // 0 and 1 were overwritten; 2,3,4 survive in chronological order.
    expect(buffer.toChronologicalArray()).toEqual([2, 3, 4]);
  });

  it('reconstructs chronological order before the buffer is full', () => {
    const buffer = createRingBuffer<number>(5);
    [10, 20, 30].forEach((value) => buffer.push(value));
    expect(buffer.toChronologicalArray()).toEqual([10, 20, 30]);
  });

  it('clear() resets size and chronological output without changing capacity', () => {
    const buffer = createRingBuffer<number>(4);
    [1, 2, 3].forEach((value) => buffer.push(value));
    buffer.clear();
    expect(buffer.size).toBe(0);
    expect(buffer.toChronologicalArray()).toEqual([]);
    expect(buffer.capacity).toBe(4);
  });

  it('rejects a non-positive or non-integer capacity', () => {
    expect(() => createRingBuffer(0)).toThrow();
    expect(() => createRingBuffer(-1)).toThrow();
    expect(() => createRingBuffer(1.5)).toThrow();
  });
});
