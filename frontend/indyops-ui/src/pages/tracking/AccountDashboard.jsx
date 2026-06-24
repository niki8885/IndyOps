import { useState, useEffect } from 'react'
import { get } from '../../api/client'
import { fmtIsk, fmtInt } from './fmt'
import aureusImg from '../../assets/aureus.png'
import pennyImg from '../../assets/penny.png'

// ── coin icon (gold Aureus / copper Penny) ───────────────────────────────────
function Coin({ kind }) {
  const gold = kind === 'aureus'
  return (
    <img
      src={gold ? aureusImg : pennyImg}
      alt={gold ? 'Aureus' : 'Penny'}
      width={24}
      height={24}
      style={{ display: 'block', flexShrink: 0 }}
    />
  )
}

function BankCard({ currency }) {
  return (
    <div className="card" style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
      <span className="sec-label">BANK BALANCE</span>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
        <Coin kind="aureus" />
        <span style={{ color: 'var(--text-white)', fontWeight: 700, fontSize: 16 }}>{fmtInt(currency?.aureus ?? 0)}</span>
        <span style={{ color: 'var(--text)', fontSize: 12 }}>Aureus</span>
      </span>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
        <Coin kind="penny" />
        <span style={{ color: 'var(--text-white)', fontWeight: 700, fontSize: 16 }}>{fmtInt(currency?.penny ?? 0)}</span>
        <span style={{ color: 'var(--text)', fontSize: 12 }}>Penny</span>
      </span>
    </div>
  )
}

const slot = s => (s ? `${s.used}/${s.max}` : '—')

export default function AccountDashboard() {
  const [data, setData] = useState(null)
  useEffect(() => {
    let alive = true
    const tick = () => get('/account/dashboard').then(d => { if (alive) setData(d) }).catch(() => {})
    tick()
    const id = setInterval(tick, 60_000)
    return () => { alive = false; clearInterval(id) }
  }, [])

  if (!data) return null
  const { characters = [], totals, currency } = data
  if (!characters.length) {
    return (
      <div style={{ marginBottom: 20 }}>
        <BankCard currency={currency} />
      </div>
    )
  }

  return (
    <div style={{ marginBottom: 22, display: 'grid', gap: 14 }}>
      <BankCard currency={currency} />
      <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
        <table>
          <thead>
            <tr>
              <th>Character</th>
              <th style={{ textAlign: 'right' }}>Wallet</th>
              <th style={{ textAlign: 'right' }}>Sell ISK</th>
              <th style={{ textAlign: 'right' }}>Buy ISK</th>
              <th style={{ textAlign: 'right' }}>Escrow</th>
              <th style={{ textAlign: 'center' }}>Mfg</th>
              <th style={{ textAlign: 'center' }}>Sci</th>
              <th style={{ textAlign: 'center' }}>Rea</th>
              <th style={{ textAlign: 'center' }}>Jobs M/R/Res</th>
              <th style={{ textAlign: 'right' }}>Contracts</th>
            </tr>
          </thead>
          <tbody>
            {characters.map(c => (
              <tr key={c.character_id}>
                <td>
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                    <img src={c.portrait} alt="" width={22} height={22} style={{ borderRadius: 3 }} />
                    <span style={{ color: 'var(--text-white)' }}>{c.name}</span>
                    {c.needs_scope && <span className="badge badge-warn" title="Re-link to enable order tracking">scope</span>}
                  </span>
                </td>
                <td style={{ textAlign: 'right' }}>{fmtIsk(c.wallet)}</td>
                <td style={{ textAlign: 'right' }}>{fmtIsk(c.sell_isk)}</td>
                <td style={{ textAlign: 'right' }}>{fmtIsk(c.buy_isk)}</td>
                <td style={{ textAlign: 'right' }}>{fmtIsk(c.escrow)}</td>
                <td style={{ textAlign: 'center' }}>{slot(c.slots?.manufacturing)}</td>
                <td style={{ textAlign: 'center' }}>{slot(c.slots?.science)}</td>
                <td style={{ textAlign: 'center' }}>{slot(c.slots?.reaction)}</td>
                <td style={{ textAlign: 'center' }}>
                  {fmtInt(c.jobs?.manufacturing)}/{fmtInt(c.jobs?.reactions)}/{fmtInt((c.jobs?.research || 0) + (c.jobs?.copying || 0) + (c.jobs?.invention || 0))}
                </td>
                <td style={{ textAlign: 'right' }}>{fmtInt(c.contracts)}</td>
              </tr>
            ))}
            {totals && (
              <tr style={{ fontWeight: 700, background: 'var(--surface2)' }}>
                <td style={{ color: 'var(--accent)' }}>Total</td>
                <td style={{ textAlign: 'right' }}>{fmtIsk(totals.wallet)}</td>
                <td style={{ textAlign: 'right' }}>{fmtIsk(totals.sell_isk)}</td>
                <td style={{ textAlign: 'right' }}>{fmtIsk(totals.buy_isk)}</td>
                <td style={{ textAlign: 'right' }}>{fmtIsk(totals.escrow)}</td>
                <td style={{ textAlign: 'center' }}>{slot(totals.slots?.manufacturing)}</td>
                <td style={{ textAlign: 'center' }}>{slot(totals.slots?.science)}</td>
                <td style={{ textAlign: 'center' }}>{slot(totals.slots?.reaction)}</td>
                <td style={{ textAlign: 'center' }}>
                  {fmtInt(totals.jobs?.manufacturing)}/{fmtInt(totals.jobs?.reactions)}/{fmtInt((totals.jobs?.research || 0) + (totals.jobs?.copying || 0) + (totals.jobs?.invention || 0))}
                </td>
                <td style={{ textAlign: 'right' }}>{fmtInt(totals.contracts)}</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
