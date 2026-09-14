/**
 * Vitest setup — jsdom + Testing Library matchers.
 * Loaded once per test file via vite.config.ts `test.setupFiles`.
 */
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});
