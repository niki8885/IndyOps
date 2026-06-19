import { useState } from 'react'
import PropTypes from 'prop-types'
import { post } from '../../api/client'

// A 10-ish question multiple-choice quiz. Scoring is client-side (the answer key ships with
// the article); on submit we POST the score so the account tracks progress per section.
export default function Quiz({ section, articleKey, questions, onSubmitted, passPct = 0.7 }) {
  const [answers, setAnswers] = useState(() => questions.map(() => -1))
  const [submitted, setSubmitted] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [result, setResult] = useState(null)

  const score = answers.reduce((s, a, i) => s + (a === questions[i].answer ? 1 : 0), 0)
  const allAnswered = answers.every(a => a >= 0)
  const pct = Math.round((score / questions.length) * 100)

  const choose = (qi, oi) => { if (!submitted) setAnswers(a => a.map((v, i) => (i === qi ? oi : v))) }

  const submit = async () => {
    setSubmitted(true); setBusy(true); setErr('')
    try {
      const r = await post('/encyclopedia/quiz', { section, article_key: articleKey, score, total: questions.length })
      setResult(r); onSubmitted?.(r)
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  const retry = () => { setAnswers(questions.map(() => -1)); setSubmitted(false); setResult(null); setErr('') }

  return (
    <div style={{ marginTop: 24, borderTop: '1px solid var(--border,#2a3140)', paddingTop: 16 }}>
      <h3 style={{ color: 'var(--accent)', marginTop: 0 }}>📝 Quiz — {questions.length} questions</h3>
      {questions.map((q, qi) => (
        <div key={qi} style={{ margin: '14px 0' }}>
          <div style={{ fontSize: 14, color: 'var(--text-white)', marginBottom: 6 }}>
            <b>{qi + 1}.</b> {q.q}
          </div>
          <div style={{ display: 'grid', gap: 5 }}>
            {q.options.map((opt, oi) => {
              const chosen = answers[qi] === oi
              const correct = q.answer === oi
              let bd = 'var(--border,#2a3140)', bg = 'transparent', col = 'var(--text)'
              if (submitted && correct) { bd = '#4caf7d'; bg = 'rgba(76,175,125,0.1)'; col = '#cdebd9' }
              else if (submitted && chosen && !correct) { bd = '#e05252'; bg = 'rgba(224,82,82,0.1)'; col = '#f0c4c4' }
              else if (chosen) { bd = 'var(--accent)'; col = 'var(--text-white)' }
              return (
                <button key={oi} type="button" onClick={() => choose(qi, oi)} disabled={submitted}
                        style={{ textAlign: 'left', fontSize: 13, padding: '7px 10px', borderRadius: 6,
                                 border: `1px solid ${bd}`, background: bg, color: col,
                                 cursor: submitted ? 'default' : 'pointer' }}>
                  <span style={{ opacity: 0.7, marginRight: 6 }}>{String.fromCharCode(65 + oi)}.</span>{opt}
                  {submitted && correct && <span style={{ float: 'right', color: '#4caf7d' }}>✓</span>}
                  {submitted && chosen && !correct && <span style={{ float: 'right', color: '#e05252' }}>✗</span>}
                </button>
              )
            })}
          </div>
          {submitted && q.explain && (
            <div style={{ fontSize: 12, color: 'var(--text)', marginTop: 5, fontStyle: 'italic' }}>{q.explain}</div>
          )}
        </div>
      ))}

      {err && <div style={{ color: '#e05252', fontSize: 12, marginTop: 8 }}>{err}</div>}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 14 }}>
        {!submitted ? (
          <>
            <button className="btn btn-primary" disabled={!allAnswered || busy} onClick={submit}>Submit answers</button>
            {!allAnswered && <span style={{ fontSize: 12, color: 'var(--text)' }}>Answer all {questions.length} to submit.</span>}
          </>
        ) : (
          <>
            <span style={{ fontSize: 13, fontWeight: 800, letterSpacing: 1, padding: '2px 12px', borderRadius: 12,
                           background: pct >= passPct * 100 ? '#13351f' : '#3a1c1c',
                           color: pct >= passPct * 100 ? '#4caf7d' : '#e05252' }}>
              {pct >= passPct * 100 ? 'PASS' : 'FAIL'}
            </span>
            <span style={{ fontSize: 15, fontWeight: 700, color: pct >= 70 ? '#4caf7d' : pct >= 40 ? '#e0884f' : '#e05252' }}>
              Score {score}/{questions.length} ({pct}%)
            </span>
            {result && <span style={{ fontSize: 12, color: 'var(--text)' }}>Best {result.best}/{result.total} · {result.attempts} attempt(s) · saved to your account</span>}
            <button className="btn btn-ghost btn-sm" onClick={retry}>Try again</button>
          </>
        )}
      </div>
    </div>
  )
}

Quiz.propTypes = {
  section: PropTypes.string.isRequired,
  articleKey: PropTypes.string.isRequired,
  questions: PropTypes.array.isRequired,
  onSubmitted: PropTypes.func,
  passPct: PropTypes.number,
}
