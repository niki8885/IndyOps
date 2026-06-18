// Registers @testing-library/jest-dom matchers (toBeInTheDocument, etc.) and
// cleans up the DOM between tests. Loaded via vite.config.js `test.setupFiles`.
import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

afterEach(() => cleanup())
