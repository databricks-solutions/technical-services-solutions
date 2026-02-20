import { vi } from 'vitest';

// Mock Cytoscape
const mockCytoscape = vi.fn(() => ({
  elements: vi.fn(() => ({
    remove: vi.fn(),
    restore: vi.fn(),
    length: 0,
  })),
  add: vi.fn(),
  remove: vi.fn(),
  on: vi.fn(),
  off: vi.fn(),
  layout: vi.fn(() => ({
    run: vi.fn(),
    stop: vi.fn(),
  })),
  style: vi.fn(() => ({
    selector: vi.fn(() => ({
      style: vi.fn(),
    })),
    update: vi.fn(),
  })),
  fit: vi.fn(),
  center: vi.fn(),
  zoom: vi.fn(),
  pan: vi.fn(),
  nodes: vi.fn(() => ({
    forEach: vi.fn(),
    length: 0,
  })),
  edges: vi.fn(() => ({
    forEach: vi.fn(),
    length: 0,
  })),
  getElementById: vi.fn(),
  destroy: vi.fn(),
  resize: vi.fn(),
  $: vi.fn(() => ({
    select: vi.fn(),
    unselect: vi.fn(),
    addClass: vi.fn(),
    removeClass: vi.fn(),
    data: vi.fn(),
    style: vi.fn(),
  })),
}));

export default mockCytoscape;
