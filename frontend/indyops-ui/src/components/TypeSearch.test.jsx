import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'

// Mock the API client so no real fetch happens.
vi.mock('../api/client', () => ({
  get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(),
}))
import { get } from '../api/client'

import TypeSearch from './TypeSearch'

const TYPES = [
  { type_id: 34, type_name: 'Tritanium', group_name: 'Mineral' },
  { type_id: 35, type_name: 'Pyerite', group_name: 'Mineral' },
]

beforeEach(() => {
  vi.useFakeTimers()
  get.mockReset()
})

afterEach(() => {
  vi.runOnlyPendingTimers()
  vi.useRealTimers()
})

async function flushDebounce() {
  await act(async () => { await vi.advanceTimersByTimeAsync(300) })
}

describe('TypeSearch', () => {
  it('does nothing when typing fewer than 2 chars', async () => {
    render(<TypeSearch onChange={() => {}} />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'T' } })
    await flushDebounce()
    expect(get).not.toHaveBeenCalled()
    expect(screen.queryByText('Tritanium')).not.toBeInTheDocument()
  })

  it('queries /eve/types/search and renders item rows once >=2 chars', async () => {
    get.mockResolvedValue(TYPES)
    render(<TypeSearch onChange={() => {}} />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Tri' } })
    await flushDebounce()
    expect(get).toHaveBeenCalledWith('/eve/types/search?q=Tri')
    expect(screen.getByText('Tritanium')).toBeInTheDocument()
    expect(screen.getByText('Pyerite')).toBeInTheDocument()
    // group_name annotation rendered
    expect(screen.getAllByText('Mineral').length).toBeGreaterThan(0)
  })

  it('selecting an item (mousedown) calls onChange with {type_id, name} and hides the list', async () => {
    const onChange = vi.fn()
    get.mockResolvedValue(TYPES)
    render(<TypeSearch onChange={onChange} />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Tri' } })
    await flushDebounce()

    fireEvent.mouseDown(screen.getByText('Tritanium'))
    expect(onChange).toHaveBeenCalledWith({ type_id: 34, name: 'Tritanium' })
    expect(screen.queryByText('Pyerite')).not.toBeInTheDocument()
    expect(screen.getByRole('textbox')).toHaveValue('Tritanium')
  })

  it('clearing the input via the ✕ button resets the selection', async () => {
    const onChange = vi.fn()
    get.mockResolvedValue(TYPES)
    render(<TypeSearch onChange={onChange} />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Tri' } })
    await flushDebounce()

    fireEvent.click(screen.getByRole('button'))
    expect(onChange).toHaveBeenLastCalledWith({ type_id: null, name: null })
    expect(screen.getByRole('textbox')).toHaveValue('')
  })

  it('shows a search-failed message when the query rejects', async () => {
    get.mockRejectedValue(new Error('boom'))
    render(<TypeSearch onChange={() => {}} />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Tri' } })
    await flushDebounce()
    expect(screen.getByText(/Search failed: boom/i)).toBeInTheDocument()
  })
})
