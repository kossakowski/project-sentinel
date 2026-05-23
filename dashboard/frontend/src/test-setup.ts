// Vitest global setup.
//
// * Wires `@testing-library/jest-dom` matchers into the default expect.
// * Resets the localStorage backing store between tests so persistence assertions
//   start from a clean slate.
// * Auto-cleans up React Testing Library trees after every test.

import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach } from "vitest";

afterEach(() => {
  cleanup();
});

beforeEach(() => {
  window.localStorage.clear();
});
