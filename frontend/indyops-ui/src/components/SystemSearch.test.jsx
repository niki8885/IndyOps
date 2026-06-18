import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'

// Mock the API client so no real fetch happens.
vi.mock('../api/client', () => ({
  get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(),
}))
import { get } from '../api/client'

import SystemSearch from './SystemSearch'

const SYSTEMS = [
  { solar_system_id: 30000142, solar_system_name: 'Jita', security: 0.9 },
  { solar_system_id: 30002187, solar_system_name: 'Amarr', security: 1.0 },
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

describe('SystemSearch', () => {
  it('does nothing when typing fewer than 2 chars', async () => {
    render(<SystemSearch onChange={() => {}} />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'J' } })
    await flushDebounce()
    expect(get).not.toHaveBeenCalled()
    expect(screen.queryByText('Jita')).not.toBeInTheDocument()
  })

  it('queries /eve/systems and renders system rows once >=2 chars', async () => {
    get.mockResolvedValue(SYSTEMS)
    render(<SystemSearch onChange={() => {}} />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Jit' } })
    await flushDebounce()
    expect(get).toHaveBeenCalledWith('/eve/systems?q=Jit')
    expect(screen.getByText('Jita')).toBeInTheDocument()
    expect(screen.getByText('Amarr')).toBeInTheDocument()
    // security label formatted to one decimal
    expect(screen.getByText('0.9')).toBeInTheDocument()
  })

  it('selecting a system (mousedown) calls onChange(name, sys) and hides the list', async () => {
    const onChange = vi.fn()
    get.mockResolvedValue(SYSTEMS)
    render(<SystemSearch onChange={onChange} />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Jit' } })
    await flushDebounce()

    fireEvent.mouseDown(screen.getByText('Jita'))
    expect(onChange).toHaveBeenCalledWith('Jita', SYSTEMS[0])
    expect(screen.queryByText('Amarr')).not.toBeInTheDocument()
    expect(screen.getByRole('textbox')).toHaveValue('Jita')
  })
})
