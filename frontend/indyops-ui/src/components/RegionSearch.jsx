import { useState, useRef, useEffect } from 'react'
import PropTypes from 'prop-types'
import { get } from '../api/client'

// Region autocomplete against /eve/regions. Calls onChange(region) with the
// picked {region_id, region_name}.
export default function RegionSearch({ value, onChange, placeholder = 'Region (e.g. The Forge)…' }) {
  const [q, setQ] = useState(value || '')
  const [results, setResults] = useState([])
  const [open, setOpen] = useState(false)
  const timer = useRef(null)
  const wrapRef = useRef(null)

  useEffect(() => { setQ(value || '') }, [value])

  useEffect(() => {
    const h = e => { if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])

  function onInput(e) {
    const v = e.target.value; setQ(v)
    clearTimeout(timer.current)
    if (v.length < 2) { setResults([]); setOpen(false); return }
    timer.current = setTimeout(async () => {
      try { setResults(await get(`/eve/regions?q=${encodeURIComponent(v)}`)); setOpen(true) } catch {}
    }, 250)
  }

  return (
    <div ref={wrapRef} style={{ position: 'relative' }}>
      <input value={q} onChange={onInput} onFocus={() => results.length && setOpen(true)} placeholder={placeholder} />
      {open && results.length > 0 && (
        <ul role="listbox" style={{
          position: 'absolute', zIndex: 999, width: '100%', background: 'var(--surface2)',
          border: '1px solid var(--border2)', borderRadius: 4, listStyle: 'none',
          maxHeight: 220, overflowY: 'auto', marginTop: 2,
        }}>
          {results.map(r => {
            const pick = () => { onChange(r); setQ(r.region_name); setOpen(false) }
            return (
              <li key={r.region_id} role="option" aria-selected={false} tabIndex={0}
                onMouseDown={pick}
                onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick() } }}
                style={{ padding: '6px 12px', cursor: 'pointer', color: 'var(--text-white)', fontSize: 13 }}
                onMouseEnter={e => e.currentTarget.style.background = 'var(--surface3)'}
                onMouseLeave={e => e.currentTarget.style.background = ''}>
                {r.region_name}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

RegionSearch.propTypes = {
  value: PropTypes.string,
  onChange: PropTypes.func.isRequired,
  placeholder: PropTypes.string,
}
