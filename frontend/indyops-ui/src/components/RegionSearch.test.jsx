import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'

// Mock the API client so no real fetch happens.
vi.mock('../api/client', () => ({
  get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(),
}))
import { get } from '../api/client'

import RegionSearch from './RegionSearch'

const REGIONS = [
  { region_id: 10000002, region_name: 'The Forge' },
  { region_id: 10000043, region_name: 'Domain' },
]

beforeEach(() => {
  vi.useFakeTimers()
  get.mockReset()
})

afterEach(() => {
  vi.runOnlyPendingTimers()
  vi.useRealTimers()
})

// Flush the 250ms debounce and let the awaited get() promise resolve.
async function flushDebounce() {
  await act(async () => { await vi.advanceTimersByTimeAsync(300) })
}

describe('RegionSearch', () => {
  it('does nothing when typing fewer than 2 chars', async () => {
    render(<RegionSearch onChange={() => {}} />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'T' } })
    await flushDebounce()
    expect(get).not.toHaveBeenCalled()
    expect(screen.queryByRole('option')).not.toBeInTheDocument()
  })

  it('queries /eve/regions and renders region options once >=2 chars', async () => {
    get.mockResolvedValue(REGIONS)
    render(<RegionSearch onChange={() => {}} />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'The' } })
    await flushDebounce()
    expect(get).toHaveBeenCalledWith('/eve/regions?q=The')
    const options = screen.getAllByRole('option')
    expect(options).toHaveLength(2)
    expect(screen.getByText('The Forge')).toBeInTheDocument()
    expect(screen.getByText('Domain')).toBeInTheDocument()
  })

  it('selecting an option (mousedown) calls onChange with the region and hides the list', async () => {
    const onChange = vi.fn()
    get.mockResolvedValue(REGIONS)
    render(<RegionSearch onChange={onChange} />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'The' } })
    await flushDebounce()

    fireEvent.mouseDown(screen.getByText('The Forge'))
    expect(onChange).toHaveBeenCalledWith(REGIONS[0])
    expect(screen.queryByRole('option')).not.toBeInTheDocument()
    expect(screen.getByRole('textbox')).toHaveValue('The Forge')
  })

  it('keyboard Enter on an option selects it', async () => {
    const onChange = vi.fn()
    get.mockResolvedValue(REGIONS)
    render(<RegionSearch onChange={onChange} />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Dom' } })
    await flushDebounce()

    fireEvent.keyDown(screen.getByText('Domain'), { key: 'Enter' })
    expect(onChange).toHaveBeenCalledWith(REGIONS[1])
    expect(screen.queryByRole('option')).not.toBeInTheDocument()
  })
})
