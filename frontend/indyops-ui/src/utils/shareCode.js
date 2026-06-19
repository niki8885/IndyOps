// Short shareable job codes are now stored server-side (POST /calculate returns one;
// GET /manufacturing/share/{code} resolves it), so the client only needs to extract a
// code from pasted text / a share URL and build a link for display.

// Extract a short code from a raw code or a full share URL (…?job=CODE). '' if invalid.
export function codeFromInput(input) {
  if (!input) return ''
  let s = String(input).trim()
  const m = s.match(/[?&]job=([^&\s]+)/)
  if (m) s = decodeURIComponent(m[1])
  return /^[A-Za-z0-9]{1,16}$/.test(s) ? s : ''
}

export function shareUrl(code) {
  const origin = (typeof window !== 'undefined' && window.location && window.location.origin) || ''
  return `${origin}/manufacturing?job=${encodeURIComponent(code)}`
}
