import "@testing-library/jest-dom/vitest";

HTMLCanvasElement.prototype.getContext = (() => ({
  clearRect: () => undefined, setTransform: () => undefined, fillRect: () => undefined,
  globalAlpha: 1, globalCompositeOperation: "source-over", fillStyle: ""
})) as unknown as typeof HTMLCanvasElement.prototype.getContext;
Object.defineProperty(HTMLCanvasElement.prototype, "getBoundingClientRect", { value: () => ({ width: 400, height: 400, top: 0, left: 0, right: 400, bottom: 400, x: 0, y: 0, toJSON: () => ({}) }) });
Object.defineProperty(window, "matchMedia", { value: (query: string) => ({ matches: false, media: query, onchange: null, addListener: () => undefined, removeListener: () => undefined, addEventListener: () => undefined, removeEventListener: () => undefined, dispatchEvent: () => false }) });
Object.defineProperty(window, "requestAnimationFrame", { writable: true, value: () => 1 });
Object.defineProperty(window, "cancelAnimationFrame", { writable: true, value: () => undefined });
Object.defineProperty(window, "PointerEvent", { writable: true, value: MouseEvent });
