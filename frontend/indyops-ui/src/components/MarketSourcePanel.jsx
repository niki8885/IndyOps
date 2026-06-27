/**
 * Buy-price source selector shared by the Chain and Calculator tabs.
 *
 * Lets the user pick which markets to source materials from (region checkboxes +
 * the optional C-J6MT scrape), choose a Buy/Sell side *per market*, and add custom
 * group rules that force a side for a whole item group (e.g. "Mineral → Buy")
 * regardless of the per-region default. The cheapest price across the selected
 * markets wins. Purely presentational — all state lives in the parent.
 */

const SIDES = ['buy', 'sell']

function SideToggle({ value, onChange, disabled, size = 'sm' }) {
  const pad = size === 'xs' ? '1px 6px' : '2px 8px'
  return (
    <span style={{ display: 'inline-flex', gap: 2, opacity: disabled ? 0.4 : 1 }}>
      {SIDES.map(s => (
        <button
          key={s} type="button" disabled={disabled} onClick={() => onChange(s)}
          className={`btn btn-sm ${value === s ? 'btn-primary' : 'btn-ghost'}`}
          style={{ padding: pad, fontSize: 10, textTransform: 'capitalize', cursor: disabled ? 'default' : 'pointer' }}
        >{s}</button>
      ))}
    </span>
  )
}

// Per-market haul cost (ISK per m³) from that market to the home hub. Folded into the
// fill / analyze price as volume × coef so the cheapest source accounts for delivery.
function DeliveryInput({ value, onChange, disabled }) {
  return (
    <input type="number" min={0} step={100} value={value ?? ''} disabled={disabled}
      onChange={e => onChange(e.target.value)} placeholder="ISK/m³"
      title="Haul cost ISK per m³ from this market to your home hub (0 = local / no haul)"
      style={{ width: 64, padding: '1px 4px', fontSize: 10, opacity: disabled ? 0.4 : 1 }} />
  )
}

export default function MarketSourcePanel({
  regions,
  selectedRegions, toggleRegion,
  regionSide, setSide,
  includeCJ, setIncludeCJ,
  rules, setRules,
  groupOptions = [],
  showCJ = true,
  showDelivery = false,
  delivery = {}, setDelivery,
}) {
  const sideOf = key => regionSide[key] || 'buy'

  // Default a new rule to the side OPPOSITE the markets' prevailing side, so adding it has
  // an immediate, visible effect. Previously a new rule defaulted to 'buy', which equals the
  // Chain tab's default basis — so the rule silently matched the existing side and looked
  // broken ("custom rules don't work in chain").
  const prevailingSide = () => {
    const sides = [...selectedRegions].map(sideOf)
    if (includeCJ) sides.push(sideOf('cj'))
    const buys = sides.filter(s => s === 'buy').length
    return buys >= sides.length - buys ? 'buy' : 'sell'
  }
  const addRule = () => setRules([...rules, { group: groupOptions[0] || '', side: prevailingSide() === 'buy' ? 'sell' : 'buy' }])
  const setRule = (i, patch) => setRules(rules.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  const delRule = i => setRules(rules.filter((_, j) => j !== i))

  const row = {
    display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0',
    justifyContent: 'space-between',
  }

  return (
    <div>
      {showDelivery && (
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 5, fontSize: 10, color: 'var(--border2)' }}>
          <span>delivery ISK/m³</span><span style={{ width: 64, textAlign: 'center' }}>side</span>
        </div>
      )}
      {/* per-market checkbox + (optional delivery) + side */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, marginTop: showDelivery ? 0 : 5 }}>
        {regions.map(r => {
          const on = selectedRegions.has(r.id)
          return (
            <div key={r.id} style={row}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, cursor: 'pointer',
                color: on ? 'var(--text-white)' : 'var(--text)' }}>
                <input type="checkbox" checked={on} onChange={() => toggleRegion(r.id)} />
                {r.name}
              </label>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                {showDelivery && (
                  <DeliveryInput value={delivery[r.id]} onChange={v => setDelivery?.(r.id, v)} disabled={!on} />
                )}
                <SideToggle value={sideOf(r.id)} onChange={s => setSide(r.id, s)} disabled={!on} />
              </span>
            </div>
          )
        })}
        {showCJ && (
          <div style={row}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, cursor: 'pointer',
              color: includeCJ ? '#c8a951' : 'var(--text)' }}>
              <input type="checkbox" checked={includeCJ} onChange={e => setIncludeCJ(e.target.checked)} />
              C-J6MT <span style={{ fontSize: 10, color: 'var(--border2)' }}>(slow)</span>
            </label>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              {showDelivery && (
                <DeliveryInput value={delivery.cj} onChange={v => setDelivery?.('cj', v)} disabled={!includeCJ} />
              )}
              <SideToggle value={sideOf('cj')} onChange={s => setSide('cj', s)} disabled={!includeCJ} />
            </span>
          </div>
        )}
      </div>

      {/* custom group rules */}
      <div style={{ marginTop: 10, paddingTop: 8, borderTop: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
          <span style={{ fontSize: 11, color: 'var(--accent)', fontWeight: 600 }}>Custom rules</span>
          <span style={{ fontSize: 10, color: 'var(--border2)' }}>
            override the side per item group{rules.length === 0 ? ' — none by default' : ''}
          </span>
          <button type="button" className="btn btn-ghost btn-sm" onClick={addRule}
            disabled={groupOptions.length === 0}
            title={groupOptions.length === 0 ? 'Calculate / load a blueprint first to list item groups' : 'Add a rule'}
            style={{ marginLeft: 'auto', padding: '1px 8px', fontSize: 11 }}>+ Add rule</button>
        </div>
        {rules.map((r, i) => {
          // keep the saved group selectable even if it's not in the current options
          const opts = r.group && !groupOptions.includes(r.group) ? [r.group, ...groupOptions] : groupOptions
          return (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
              <span style={{ fontSize: 11, color: 'var(--text)' }}>Use</span>
              <SideToggle value={r.side} onChange={s => setRule(i, { side: s })} size="xs" />
              <span style={{ fontSize: 11, color: 'var(--text)' }}>for</span>
              <select value={r.group} onChange={e => setRule(i, { group: e.target.value })}
                style={{ flex: 1, minWidth: 120, padding: '2px 4px', fontSize: 11 }}>
                {opts.map(g => <option key={g} value={g}>{g}</option>)}
              </select>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => delRule(i)}
                title="Remove rule" style={{ padding: '1px 7px', fontSize: 12 }}>×</button>
            </div>
          )
        })}
      </div>
    </div>
  )
}
