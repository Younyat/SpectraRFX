// Circular buffer (spec §45): fixed-capacity storage, head advances by one
// slot per push, oldest entry is overwritten once full -- never a full
// array shift/copy per frame. `capacity` is fixed for the buffer's
// lifetime; callers that need a different capacity (e.g. after an
// acquisition-generation reset) create a new buffer rather than resizing.
export interface RingBuffer<T> {
  readonly capacity: number;
  readonly size: number;
  push(item: T): void;
  toChronologicalArray(): T[];
  clear(): void;
}

export const createRingBuffer = <T>(capacity: number): RingBuffer<T> => {
  if (!Number.isInteger(capacity) || capacity <= 0) {
    throw new Error(`RingBuffer capacity must be a positive integer, got ${capacity}`);
  }

  const slots: (T | undefined)[] = new Array(capacity);
  let head = 0;
  let size = 0;

  return {
    capacity,
    get size() {
      return size;
    },
    push(item: T) {
      slots[head] = item;
      head = (head + 1) % capacity;
      size = Math.min(size + 1, capacity);
    },
    toChronologicalArray() {
      if (size < capacity) {
        return slots.slice(0, size) as T[];
      }
      // Buffer is full: `head` already points at the oldest surviving
      // entry (the next slot due for overwrite), so chronological order is
      // [head..end) followed by [0..head).
      return [...slots.slice(head), ...slots.slice(0, head)] as T[];
    },
    clear() {
      slots.fill(undefined);
      head = 0;
      size = 0;
    },
  };
};
