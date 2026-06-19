import { useEffect, useMemo, useState } from 'react'
import PropTypes from 'prop-types'
import { get } from '../api/client'
import Markdown from '../components/encyclopedia/Markdown'
import Quiz from '../components/encyclopedia/Quiz'
import { ARTICLES, SECTIONS } from '../content/encyclopedia/articles'

const stars = n => '★'.repeat(n) + '☆'.repeat(Math.max(0, 3 - n))
const PASS_PCT = 0.7   // quiz pass threshold

function Tag({ children, color }) {
  return <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 10, background: '#23304a', color: color || '#7da7e0' }}>{children}</span>
}
Tag.propTypes = { children: PropTypes.node, color: PropTypes.string }

// Persistent result plaque under the article: best score + PASS/FAIL (pass ≥ PASS_PCT).
function ResultPlaque({ title, best }) {
  const has = !!best
  const passed = has && best.total && best.best_score / best.total >= PASS_PCT
  const pct = has && best.total ? Math.round((best.best_score / best.total) * 100) : null
  const border = !has ? 'var(--border,#2a3140)' : passed ? '#2c5a3f' : '#5a2c2c'
  const bg = !has ? 'var(--panel,#161b24)' : passed ? 'rgba(76,175,125,0.10)' : 'rgba(224,82,82,0.08)'
  return (
    <div style={{ marginTop: 16, display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap',
                  padding: '12px 16px', borderRadius: 8, border: `1px solid ${border}`, background: bg }}>
      <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-white)' }}>{title} — your result</span>
      {has ? (
        <>
          <span style={{ fontSize: 13, fontWeight: 800, letterSpacing: 1, padding: '2px 12px', borderRadius: 12,
                         background: passed ? '#13351f' : '#3a1c1c', color: passed ? '#4caf7d' : '#e05252' }}>
            {passed ? 'PASS' : 'FAIL'}
          </span>
          <span style={{ fontSize: 14, fontWeight: 700, color: passed ? '#4caf7d' : '#e0884f' }}>
            best {best.best_score}/{best.total} ({pct}%)
          </span>
          <span style={{ fontSize: 11, color: 'var(--text)' }}>
            {best.attempts} attempt(s) · pass ≥ {Math.round(PASS_PCT * 100)}%
          </span>
        </>
      ) : (
        <span style={{ fontSize: 12, color: 'var(--text)' }}>
          Not attempted yet — take the quiz above. Pass ≥ {Math.round(PASS_PCT * 100)}%.
        </span>
      )}
    </div>
  )
}
ResultPlaque.propTypes = { title: PropTypes.string, best: PropTypes.object }

export default function EncyclopediaPage() {
  const [activeKey, setActiveKey] = useState(ARTICLES[0].key)
  const [byArticle, setByArticle] = useState({})
  const [bySection, setBySection] = useState([])

  const loadScores = () => get('/encyclopedia/scores')
    .then(d => {
      setByArticle(Object.fromEntries((d.by_article || []).map(a => [a.article_key, a])))
      setBySection(d.by_section || [])
    })
    .catch(() => {})
  useEffect(() => { loadScores() }, [])

  const article = useMemo(() => ARTICLES.find(a => a.key === activeKey) || ARTICLES[0], [activeKey])
  const best = byArticle[article.key]

  return (
    <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start', flexWrap: 'wrap' }}>
      {/* sidebar: sections → articles */}
      <aside style={{ flex: '1 1 240px', maxWidth: 300, minWidth: 220 }}>
        <h2 style={{ marginTop: 0 }}>📚 Encyclopedia</h2>
        {SECTIONS.map(sec => {
          const ss = bySection.find(x => x.section === sec.section)
          return (
            <div key={sec.section} style={{ marginBottom: 16 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text)',
                            textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 6 }}>
                <span>{sec.label}</span>
                {ss && <span style={{ color: 'var(--accent)' }}>{Math.round(ss.avg_best_pct * 100)}%</span>}
              </div>
              {sec.articles.map(a => {
                const b = byArticle[a.key]
                const active = a.key === activeKey
                return (
                  <button key={a.key} onClick={() => setActiveKey(a.key)}
                          style={{ display: 'block', width: '100%', textAlign: 'left', padding: '8px 10px',
                                   marginBottom: 4, borderRadius: 6, cursor: 'pointer',
                                   border: `1px solid ${active ? 'var(--accent)' : 'var(--border,#2a3140)'}`,
                                   background: active ? 'rgba(76,175,125,0.1)' : 'transparent', color: 'var(--text-white)' }}>
                    <div style={{ fontSize: 13, fontWeight: 600 }}>{a.title}</div>
                    <div style={{ fontSize: 11, color: 'var(--text)', display: 'flex', justifyContent: 'space-between', marginTop: 2 }}>
                      <span title={`difficulty ${a.difficulty}/3`} style={{ color: '#e0c14f' }}>{stars(a.difficulty)}</span>
                      {b && <span style={{ color: b.best_score / b.total >= 0.7 ? '#4caf7d' : '#e0884f' }}>best {b.best_score}/{b.total}</span>}
                    </div>
                  </button>
                )
              })}
            </div>
          )
        })}
      </aside>

      {/* article + quiz */}
      <article style={{ flex: '3 1 520px', minWidth: 0, maxWidth: 860 }}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 2 }}>
          <Tag>{article.sectionLabel}</Tag>
          <Tag>{article.level}</Tag>
          <span style={{ color: '#e0c14f' }} title={`difficulty ${article.difficulty}/3`}>{stars(article.difficulty)}</span>
          {best && <Tag color="#4caf7d">best {best.best_score}/{best.total}</Tag>}
        </div>
        {article.summary && <p style={{ color: 'var(--text)', fontSize: 13, fontStyle: 'italic', margin: '4px 0 0' }}>{article.summary}</p>}
        <Markdown source={article.body} />
        <Quiz key={article.key} section={article.section} articleKey={article.key}
              questions={article.quiz} onSubmitted={loadScores} passPct={PASS_PCT} />
        <ResultPlaque title={article.title} best={best} />
      </article>
    </div>
  )
}
