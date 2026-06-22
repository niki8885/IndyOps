import { useState } from 'react'

/**
 * Numeric input that shows thousand separators *while you type* (1,000,000).
 *
 * Drop-in for a controlled `<input type="number">`: `value` is the raw numeric
 * string (no separators) and `onChange` receives a synthetic event whose
 * `target.value` is that same raw string — so existing handlers that read
 * `e.target.value` keep working unchanged. A text input is used because native
 * number inputs can't render grouping; `inputMode="decimal"` keeps the numeric
 * keypad on mobile.
 */
export default function MoneyInput({ value, onChange, ...rest }) {
  const ext = value == null ? '' : String(value)
  const [display, setDisplay] = useState(() => group(ext))
  const [lastExt, setLastExt] = useState(ext)

  // Re-sync when the value changes from the outside (auto-fill, reset, share
  // import…) but leave half-typed input (e.g. a trailing ".") untouched. This
  // is React's "adjust state during render" pattern, not an effect.
  if (ext !== lastExt) {
    setLastExt(ext)
    if (strip(display) !== ext) setDisplay(group(ext))
  }

  function handle(e) {
    const raw = strip(e.target.value)
    if (raw !== '' && !/^-?\d*\.?\d*$/.test(raw)) return // ignore invalid keystrokes
    setDisplay(group(raw))
    setLastExt(raw)
    onChange?.({ target: { value: raw } })
  }

  return <input type="text" inputMode="decimal" value={display} onChange={handle} {...rest} />
}

const strip = (s) => String(s ?? '').replace(/,/g, '')

// Group the integer part in threes, leaving any decimal portion (and a
// half-typed trailing ".") exactly as the user entered it.
function group(s) {
  let v = String(s ?? '')
  if (v === '') return ''
  const neg = v.startsWith('-')
  if (neg) v = v.slice(1)
  const dot = v.indexOf('.')
  const int = dot === -1 ? v : v.slice(0, dot)
  const frac = dot === -1 ? '' : v.slice(dot) // includes the leading '.'
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return (neg ? '-' : '') + grouped + frac
}
