import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { useState } from 'react'
import MoneyInput from './MoneyInput'

// A tiny controlled host so onChange round-trips through state like the real
// callers (setP/setJ/setI all store e.target.value verbatim).
function Host({ initial = '', onRaw }) {
  const [v, setV] = useState(initial)
  return <MoneyInput value={v} onChange={e => { setV(e.target.value); onRaw?.(e.target.value) }} />
}

describe('MoneyInput', () => {
  it('renders the initial value grouped with thousand separators', () => {
    render(<Host initial="1000000" />)
    expect(screen.getByRole('textbox')).toHaveValue('1,000,000')
  })

  it('groups digits as you type and reports the raw (unseparated) value', () => {
    const onRaw = vi.fn()
    render(<Host onRaw={onRaw} />)
    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: '179900000' } })
    expect(input).toHaveValue('179,900,000')
    expect(onRaw).toHaveBeenLastCalledWith('179900000') // handler gets a clean number string
  })

  it('preserves a decimal part and a half-typed trailing dot', () => {
    render(<Host />)
    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: '1234.' } })
    expect(input).toHaveValue('1,234.')
    fireEvent.change(input, { target: { value: '1234.50' } })
    expect(input).toHaveValue('1,234.50')
  })

  it('strips separators from pasted input before re-grouping', () => {
    const onRaw = vi.fn()
    render(<Host onRaw={onRaw} />)
    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: '1,234,567' } })
    expect(input).toHaveValue('1,234,567')
    expect(onRaw).toHaveBeenLastCalledWith('1234567')
  })

  it('ignores non-numeric keystrokes', () => {
    const onRaw = vi.fn()
    render(<Host initial="100" onRaw={onRaw} />)
    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: '100abc' } })
    expect(input).toHaveValue('100') // unchanged
    expect(onRaw).not.toHaveBeenCalled()
  })

  it('re-syncs when the value is replaced from the outside (auto-fill)', () => {
    function AutoFill() {
      const [v, setV] = useState('')
      return (
        <>
          <button onClick={() => setV('179900000.00')}>fill</button>
          <MoneyInput value={v} onChange={e => setV(e.target.value)} />
        </>
      )
    }
    render(<AutoFill />)
    fireEvent.click(screen.getByText('fill'))
    expect(screen.getByRole('textbox')).toHaveValue('179,900,000.00')
  })
})
