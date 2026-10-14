import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Without global test functions, Testing Library cannot clear the page by
// itself; each test must start from an empty page.
afterEach(cleanup);
