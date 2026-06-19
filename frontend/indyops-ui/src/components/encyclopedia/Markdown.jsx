import PropTypes from 'prop-types'
import { Figure, FIGURES } from './figures'

// A tiny Markdown renderer for our own (controlled) article content: headings, paragraphs,
// bold/italic/code, unordered lists, > callouts, and a [[fig:KEY|caption]] figure marker
// that drops in a responsive SVG figure. Not a full CommonMark — just what the articles use.

const codeStyle = { fontFamily: 'monospace', fontSize: '0.9em', background: '#1b2230',
                    padding: '1px 5px', borderRadius: 4, color: '#cdd6e3' }

function renderInline(text, kp) {
  const parts = []
  const re = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g
  let last = 0, m, i = 0
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index))
    const tok = m[0]
    if (tok.startsWith('**')) parts.push(<strong key={`${kp}-${i}`} style={{ color: 'var(--text-white)' }}>{tok.slice(2, -2)}</strong>)
    else if (tok.startsWith('`')) parts.push(<code key={`${kp}-${i}`} style={codeStyle}>{tok.slice(1, -1)}</code>)
    else parts.push(<em key={`${kp}-${i}`}>{tok.slice(1, -1)}</em>)
    last = m.index + tok.length; i++
  }
  if (last < text.length) parts.push(text.slice(last))
  return parts
}

function block(b, i) {
  const key = `b${i}`
  if (b.t === 'fig') {
    const Fig = FIGURES[b.key]
    return Fig ? <Figure key={key} caption={b.caption ? renderInline(b.caption, key) : null}><Fig /></Figure> : null
  }
  if (b.t === 'h1') return <h2 key={key} style={{ color: 'var(--accent)', fontSize: 22, margin: '22px 0 8px' }}>{renderInline(b.text, key)}</h2>
  if (b.t === 'h2') return <h3 key={key} style={{ color: 'var(--text-white)', fontSize: 17, margin: '20px 0 6px' }}>{renderInline(b.text, key)}</h3>
  if (b.t === 'h3') return <h4 key={key} style={{ color: 'var(--text-white)', fontSize: 14, margin: '16px 0 4px' }}>{renderInline(b.text, key)}</h4>
  if (b.t === 'ul') return (
    <ul key={key} style={{ margin: '8px 0', paddingLeft: 22, color: 'var(--text)', fontSize: 14, lineHeight: 1.6 }}>
      {b.items.map((it, j) => <li key={j} style={{ marginBottom: 4 }}>{renderInline(it, `${key}-${j}`)}</li>)}
    </ul>
  )
  if (b.t === 'quote') return (
    <div key={key} style={{ borderLeft: '3px solid var(--accent)', background: 'rgba(76,175,125,0.07)',
                            padding: '8px 12px', margin: '12px 0', borderRadius: '0 6px 6px 0',
                            fontSize: 13.5, color: 'var(--text)', lineHeight: 1.55 }}>
      {renderInline(b.text, key)}
    </div>
  )
  return <p key={key} style={{ margin: '8px 0', color: 'var(--text)', fontSize: 14, lineHeight: 1.65 }}>{renderInline(b.text, key)}</p>
}

export default function Markdown({ source }) {
  const lines = String(source || '').replace(/\r/g, '').split('\n')
  const blocks = []
  let para = [], list = null
  const flushPara = () => { if (para.length) { blocks.push({ t: 'p', text: para.join(' ') }); para = [] } }
  const flushList = () => { if (list) { blocks.push({ t: 'ul', items: list }); list = null } }
  const flush = () => { flushPara(); flushList() }

  for (const raw of lines) {
    const line = raw.trimEnd()
    const fig = line.match(/^\[\[fig:([a-zA-Z]+)(?:\|(.*))?\]\]$/)
    if (fig) { flush(); blocks.push({ t: 'fig', key: fig[1], caption: fig[2] || '' }); continue }
    if (!line.trim()) { flush(); continue }
    const h = line.match(/^(#{1,3})\s+(.*)$/)
    if (h) { flush(); blocks.push({ t: `h${h[1].length}`, text: h[2] }); continue }
    if (line.startsWith('> ')) { flush(); blocks.push({ t: 'quote', text: line.slice(2) }); continue }
    const li = line.match(/^[-*]\s+(.*)$/)
    if (li) { flushPara(); list = list || []; list.push(li[1]); continue }
    flushList(); para.push(line.trim())
  }
  flush()
  return <div>{blocks.map((b, i) => block(b, i))}</div>
}

Markdown.propTypes = { source: PropTypes.string }
