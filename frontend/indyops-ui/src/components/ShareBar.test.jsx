import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('../api/client', () => ({ get: vi.fn() }))
import { get } from '../api/client'
import ShareBar from './ShareBar'

beforeEach(() => get.mockReset())

describe('ShareBar', () => {
  it('shows the code and opens a pasted code via the API', async () => {
    const onOpen = vi.fn()
    get.mockResolvedValue({ source: 'production', body: { product_type_id: 9 } })
    render(<ShareBar code="01234567" link="https://x.test/manufacturing?job=01234567" onOpen={onOpen} />)
    expect(screen.getAllByText('01234567').length).toBeGreaterThan(0)
    expect(screen.getByText('Copy code')).toBeInTheDocument()

    fireEvent.change(screen.getByPlaceholderText(/Paste a code/i), { target: { value: '07654321' } })
    fireEvent.click(screen.getByText('Open'))
    await waitFor(() => expect(get).toHaveBeenCalledWith('/manufacturing/share/07654321'))
    await waitFor(() => expect(onOpen).toHaveBeenCalledWith(
      { source: 'production', body: { product_type_id: 9 }, code: '07654321' }))
  })

  it('prompts when there is no code yet and rejects junk', async () => {
    render(<ShareBar onOpen={vi.fn()} />)
    expect(screen.getByText(/Run a calc to get a share code/i)).toBeInTheDocument()
    fireEvent.change(screen.getByPlaceholderText(/Paste a code/i), { target: { value: 'not a code!!' } })
    fireEvent.click(screen.getByText('Open'))
    await waitFor(() => expect(screen.getByText(/Not a valid job code/i)).toBeInTheDocument())
    expect(get).not.toHaveBeenCalled()
  })
})
