import { useState } from 'react'
import PropTypes from 'prop-types'
import { get } from '../api/client'
import { codeFromInput, shareUrl } from '../utils/shareCode'

// QR / barcode are rendered server-side (reuses reportlab) and shown as same-origin
// <img>; the endpoint is public so no auth header is needed.
const imgUrl = (kind, data) => `/api/v1/manufacturing/share-image?kind=${kind}&data=${encodeURIComponent(data)}`

// A share row under a calculator/chain result. The server already stored this build and
// returned a short numeric `code` (+ reopen `link`); we just display the QR + barcode and
// resolve a pasted code/link back to the build. Storage has a ~1-week TTL.
export default function ShareBar({ code, link, onOpen }) {
  const [paste, setPaste] = useState('')
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const url = link || (code ? shareUrl(code) : '')

  const copy = async (text, label) => {
    setErr('')
    try { await navigator.clipboard.writeText(text); setMsg(`${label} copied`); setTimeout(() => setMsg(''), 1800) } catch (e) { setErr(e.message) }
  }
  const open = async () => {
    setErr('')
    const c = codeFromInput(paste)
    if (!c) { setErr('Not a valid job code or link.'); return }
    try {
      const data = await get(`/manufacturing/share/${c}`)
      onOpen?.({ source: data.source, body: data.body, code: c })
      setPaste('')
    } catch (e) { setErr(String(e.message).includes('404') ? 'Code not found or expired.' : e.message) }
  }

  return (
    <div style={{ border: '1px solid var(--border,#2a3140)', borderRadius: 8, padding: '12px 14px', margin: '12px 0',
                  background: 'var(--panel,#161b24)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--accent)' }}>🔗 Share job</span>
        {code && <span style={{ fontSize: 13, fontFamily: 'monospace', fontWeight: 700, padding: '1px 8px',
                                borderRadius: 6, background: '#23304a', color: '#7da7e0' }}>{code}</span>}
      </div>

      {code ? (
        <div style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap', marginTop: 10 }}>
          <img src={imgUrl('qr', url)} alt="QR code — scan to reopen" width={172} height={172}
               style={{ background: '#fff', padding: 8, borderRadius: 6 }} />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, flex: '1 1 260px', minWidth: 220 }}>
            <img src={imgUrl('barcode', code)} alt="barcode" height={76}
                 style={{ background: '#fff', padding: '6px 10px', borderRadius: 6, alignSelf: 'flex-start', maxWidth: '100%' }} />
            <div style={{ fontSize: 11, color: 'var(--text)' }}>Scan the QR, share the code <b>{code}</b>, or copy the link. Valid ~1 week — print &amp; keep for a permanent record.</div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <button className="btn btn-ghost btn-sm" onClick={() => copy(code, 'Code')}>Copy code</button>
              <button className="btn btn-ghost btn-sm" onClick={() => copy(url, 'Link')}>Copy link</button>
            </div>
          </div>
        </div>
      ) : (
        <div style={{ fontSize: 11, color: 'var(--text)', marginTop: 6 }}>Run a calc to get a share code &amp; QR.</div>
      )}

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 10, flexWrap: 'wrap' }}>
        <input value={paste} onChange={e => setPaste(e.target.value)} placeholder="Paste a code or link to open…"
               style={{ fontSize: 12, flex: '1 1 220px' }} />
        <button className="btn btn-ghost btn-sm" disabled={!paste.trim()} onClick={open}>Open</button>
        {msg && <span style={{ fontSize: 11, color: '#4caf7d' }}>{msg}</span>}
        {err && <span style={{ fontSize: 11, color: '#e05252' }}>{err}</span>}
      </div>
    </div>
  )
}

ShareBar.propTypes = {
  code: PropTypes.string,
  link: PropTypes.string,
  onOpen: PropTypes.func,
}
