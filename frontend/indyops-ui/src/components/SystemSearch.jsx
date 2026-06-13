import { useState, useEffect, useRef } from 'react'
import { get } from '../api/client'

export default function SystemSearch({ value, onChange, placeholder = 'Search system…' }) {
  const [query, setQuery] = useState(value || '')
  const [results, setResults] = useState([])
  const [open, setOpen] = useState(false)
  const timer = useRef(null)
  const wrapRef = useRef(null)

  useEffect(() => {
    const handler = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  function handleInput(e) {
    const q = e.target.value
    setQuery(q)
    clearTimeout(timer.current)
    if (q.length < 2) { setResults([]); setOpen(false); return }
    timer.current = setTimeout(async () => {
      try {
        const data = await get(`/eve/systems?q=${encodeURIComponent(q)}`)
        setResults(data)
        setOpen(true)
      } catch {}
    }, 250)
  }

  function pick(sys) {
    setQuery(sys.solar_system_name)
    onChange(sys.solar_system_name)
    setOpen(false)
    setResults([])
  }

  function secClass(sec) {
    if (sec == null) return ''
    if (sec >= 0.5) return 'sec-high'
    if (sec > 0) return 'sec-low'
    return 'sec-null'
  }

  function fmtSec(sec) {
    if (sec == null) return '?'
    return sec.toFixed(1)
  }

  return (
    <div ref={wrapRef} style={{ position: 'relative' }}>
      <input
        value={query}
        onChange={handleInput}
        onFocus={() => results.length && setOpen(true)}
        placeholder={placeholder}
      />
      {open && results.length > 0 && (
        <ul style={{
          position: 'absolute', zIndex: 999, width: '100%',
          background: 'var(--surface2)', border: '1px solid var(--border2)',
          borderRadius: 4, listStyle: 'none', maxHeight: 220, overflowY: 'auto',
          marginTop: 2,
        }}>
          {results.map(s => (
            <li
              key={s.solar_system_id}
              onMouseDown={() => pick(s)}
              style={{
                padding: '6px 12px', cursor: 'pointer', display: 'flex',
                justifyContent: 'space-between', alignItems: 'center',
              }}
              onMouseEnter={e => e.currentTarget.style.background = 'var(--surface3)'}
              onMouseLeave={e => e.currentTarget.style.background = ''}
            >
              <span style={{ color: 'var(--text-white)' }}>{s.solar_system_name}</span>
              <span className={`sec-label ${secClass(s.security)}`}>{fmtSec(s.security)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
