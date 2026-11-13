import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// jsdom no implementa estas APIs del navegador.
Element.prototype.scrollIntoView = vi.fn();
HTMLCanvasElement.prototype.getContext = (() => null) as unknown as HTMLCanvasElement["getContext"];

afterEach(() => {
  cleanup();
  localStorage.clear();
});
