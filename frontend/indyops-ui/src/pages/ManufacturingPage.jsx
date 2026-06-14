import { useState, useEffect, useCallback } from 'react'
import { get, post, patch, del } from '../api/client'
import TypeSearch from '../components/TypeSearch'

const TABS = ['Calculator', 'PAK Jobs', 'Inventory Analysis']

const STATUS_COLOR = {
  Planning:    '#8b93b0',
  Preparing:   '#c8a951',
  'In Progress': '#2980b9',
  Completed:   '#27ae60',
  Cancelled:   '#c0392b',
}

const MARKETS = ['Jita', 'C-J']
const METHODS = ['Buy', 'Split', 'Sell']

/**
 * Fetch market prices for a set of type_ids.
 * Jita → Fuzzwork aggregates; C-J → backend appraise.gnf.lt scraper.
 * Returns { [type_id]: { Buy, Split, Sell } }.
 */
async function fetchMarketPrices(typeIds, market) {
  const ids = [...new Set(typeIds.filter(Boolean))]
  if (!ids.length) return {}
  const out = {}
  if (market === 'Jita') {
    const res = await fetch(`https://market.fuzzwork.co.uk/aggregates/?station=60003760&types=${ids.join(',')}`)
    if (!res.ok) throw new Error(`Fuzzwork ${res.status}`)
    const data = await res.json()
    for (const [tid, p] of Object.entries(data)) {
      const buy = parseFloat(p.buy.max), sell = parseFloat(p.sell.min)
      out[Number(tid)] = { Buy: buy, Sell: sell, Split: (buy + sell) / 2 }
    }
  } else { // C-J via backend
    const data = await get(`/eve/prices/cj?type_ids=${ids.join(',')}`)
    for (const [tid, p] of Object.entries(data)) {
      out[Number(tid)] = { Buy: p.buy, Sell: p.sell, Split: p.split }
    }
  }
  return out
}

export default function ManufacturingPage() {
  const [tab, setTab] = useState(0)
  return (
    <div>
      <h2 style={{ marginBottom: 20 }}>Manufacturing</h2>
      <div className="tabs">
        {TABS.map((t, i) => (
          <button key={i} className={`tab-btn ${tab === i ? 'active' : ''}`} onClick={() => setTab(i)}>{t}</button>
        ))}
      </div>
      {tab === 0 && <CalculatorTab />}
      {tab === 1 && <PakJobsTab />}
      {tab === 2 && <InventoryAnalysisTab />}
    </div>
  )
}

/* ═══════════════════════════ CALCULATOR ═══════════════════════════ */

function CalculatorTab() {
  const [product, setProduct]       = useState(null)     // {type_id, name}
  const [bpInfo, setBpInfo]         = useState(null)     // blueprint info from API
  const [facilities, setFacilities] = useState([])
  const [projects, setProjects]     = useState([])

  const [params, setParams] = useState({
    runs: 1, me: 0, te: 0,
    bpc_cost: 0,
    output_price: 0,
    broker_fee_pct: 3.6,
    facility_id: '',
    system_cost_index: 0,
    facility_tax_pct: 0,
    structure_bonus_pct: 0,
    estimated_item_value: '',
  })
  const [matPrices, setMatPrices] = useState({})   // {type_id: price}
  const [result, setResult]       = useState(null)
  const [calcLoading, setCalcLoading] = useState(false)
  const [bpLoading, setBpLoading]     = useState(false)
  const [saveLoading, setSaveLoading] = useState(false)
  const [saveOpen, setSaveOpen]       = useState(false)
  const [jobForm, setJobForm]         = useState({ project_id: '', status: 'Planning', target: '', target_other: '', paks: '', units_per_pak: '', pack_tier: '', jita_sell: '', jita_buy: '', cj_sell: '', cj_buy: '', initial_contract_price: '', return_contract_price: '', code: '', contract_code: '', place: '', note: '' })
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)

  // market-price source controls
  const [matMarket, setMatMarket] = useState('Jita')
  const [matMethod, setMatMethod] = useState('Sell')
  const [matPriceLoading, setMatPriceLoading] = useState(false)
  const [outMarket, setOutMarket] = useState('Jita')
  const [outMethod, setOutMethod] = useState('Sell')
  const [outPriceLoading, setOutPriceLoading] = useState(false)
  const [pakPriceLoading, setPakPriceLoading] = useState(false)

  // warehouse availability for a project
  const [calcProjectId, setCalcProjectId] = useState('')
  const [availability, setAvailability]   = useState(null)   // { type_id: {required, available, shortfall, warehouse_unit_price} }
  const [availLoading, setAvailLoading]   = useState(false)

  // facility rig bonuses (dogma)
  const [rigBonus, setRigBonus] = useState(null)   // { total_me_pct, total_te_pct, total_cost_pct, band, rigs }
  const [enabledRigs, setEnabledRigs] = useState({})  // { type_id: bool } — user override of applicability

  useEffect(() => {
    get('/facilities').then(setFacilities).catch(() => {})
    get('/organisations').then(async orgs => {
      const all = []
      for (const o of orgs) {
        try { const ps = await get(`/projects?org_id=${o.id}`); all.push(...ps) } catch {}
      }
      setProjects(all)
    }).catch(() => {})
  }, [])

  // load blueprint when product selected
  useEffect(() => {
    if (!product?.type_id) { setBpInfo(null); setMatPrices({}); setResult(null); setAvailability(null); return }
    setBpLoading(true)
    get(`/manufacturing/blueprint?product_type_id=${product.type_id}`)
      .then(info => {
        setBpInfo(info)
        const prices = {}
        info.materials.forEach(m => { prices[m.type_id] = '' })
        setMatPrices(prices)
        setResult(null)
        setAvailability(null)
      })
      .catch(e => setError(e.message))
      .finally(() => setBpLoading(false))
  }, [product?.type_id])

  // auto-fill facility params when facility selected
  useEffect(() => {
    if (!params.facility_id) return
    const f = facilities.find(f => f.id === Number(params.facility_id))
    if (!f) return
    setParams(p => ({
      ...p,
      system_cost_index: f.system_cost_index != null ? +(f.system_cost_index * 100).toFixed(4) : p.system_cost_index,
      facility_tax_pct:  f.tax != null ? f.tax : p.facility_tax_pct,
      structure_bonus_pct: f.cost_bonus != null ? f.cost_bonus : p.structure_bonus_pct,
    }))
  }, [params.facility_id, facilities])

  // fetch dogma rig bonuses when facility + product chosen
  useEffect(() => {
    if (!params.facility_id || !product?.type_id) { setRigBonus(null); return }
    get(`/manufacturing/facility-bonuses?facility_id=${params.facility_id}&product_type_id=${product.type_id}`)
      .then(b => {
        setRigBonus(b)
        const en = {}
        b.rigs.forEach(r => { en[r.type_id] = !!r.applies })
        setEnabledRigs(en)
        const cost = (b.structure_role?.cost_pct || 0) + (b.total_cost_pct || 0)
        if (cost > 0) setParams(p => ({ ...p, structure_bonus_pct: cost }))
      })
      .catch(() => setRigBonus(null))
  }, [params.facility_id, product?.type_id])

  async function calculate() {
    if (!product?.type_id || !bpInfo) return
    setCalcLoading(true); setError('')
    try {
      const res = await post('/manufacturing/calculate', {
        product_type_id: product.type_id,
        runs:   Number(params.runs),
        me:     Number(params.me),
        te:     Number(params.te),
        bpc_cost: Number(params.bpc_cost),
        output_price: Number(params.output_price),
        broker_fee_pct: Number(params.broker_fee_pct),
        facility_id: params.facility_id ? Number(params.facility_id) : null,
        system_cost_index: Number(params.system_cost_index) / 100,
        facility_tax_pct: Number(params.facility_tax_pct),
        structure_bonus_pct: Number(params.structure_bonus_pct),
        material_bonus_pct: rigTotals().me,
        time_bonus_pct: rigTotals().te,
        material_role_pct: rigBonus?.structure_role?.material_pct || 0,
        time_role_pct: rigBonus?.structure_role?.time_pct || 0,
        estimated_item_value: params.estimated_item_value !== '' ? Number(params.estimated_item_value) : null,
        material_prices: Object.entries(matPrices)
          .filter(([, v]) => v !== '')
          .map(([type_id, unit_cost]) => ({ type_id: Number(type_id), unit_cost: Number(unit_cost) })),
      })
      setResult(res)
    } catch (e) { setError(e.message) }
    finally { setCalcLoading(false) }
  }

  async function fillMaterialPrices() {
    if (!bpInfo) return
    setMatPriceLoading(true); setError('')
    try {
      const prices = await fetchMarketPrices(bpInfo.materials.map(m => m.type_id), matMarket)
      setMatPrices(prev => {
        const next = { ...prev }
        bpInfo.materials.forEach(m => {
          const p = prices[m.type_id]
          if (p && p[matMethod] != null) next[m.type_id] = p[matMethod].toFixed(2)
        })
        return next
      })
    } catch (e) { setError('Material price fetch failed: ' + e.message) }
    finally { setMatPriceLoading(false) }
  }

  async function fillOutputPrice() {
    if (!product?.type_id) return
    setOutPriceLoading(true); setError('')
    try {
      const prices = await fetchMarketPrices([product.type_id], outMarket)
      const p = prices[product.type_id]
      if (p && p[outMethod] != null) setParams(pp => ({ ...pp, output_price: p[outMethod].toFixed(2) }))
    } catch (e) { setError('Output price fetch failed: ' + e.message) }
    finally { setOutPriceLoading(false) }
  }

  function rigTotals() {
    if (!rigBonus) return { me: 0, te: 0, cost: 0 }
    return rigBonus.rigs.reduce((a, r) => {
      if (enabledRigs[r.type_id]) {
        a.me += r.me_pct || 0; a.te += r.te_pct || 0; a.cost += r.cost_pct || 0
      }
      return a
    }, { me: 0, te: 0, cost: 0 })
  }

  function adjQtyOf(m) {
    const rigMe  = rigTotals().me
    const roleMe = rigBonus?.structure_role?.material_pct || 0
    return Math.max(
      Number(params.runs),
      Math.ceil(m.base_qty * params.runs * (1 - params.me / 100) * (1 - rigMe / 100) * (1 - roleMe / 100)),
    )
  }

  async function checkWarehouse() {
    if (!bpInfo) return
    setAvailLoading(true); setError('')
    try {
      const res = await post('/manufacturing/material-availability', {
        project_id: calcProjectId ? Number(calcProjectId) : null,
        materials: bpInfo.materials.map(m => ({ type_id: m.type_id, name: m.name, required_qty: adjQtyOf(m) })),
      })
      const map = {}
      res.materials.forEach(m => { map[m.type_id] = m })
      setAvailability(map)
    } catch (e) { setError('Warehouse check failed: ' + e.message) }
    finally { setAvailLoading(false) }
  }

  function useWarehousePrices() {
    if (!availability) return
    setMatPrices(prev => {
      const next = { ...prev }
      Object.values(availability).forEach(m => {
        if (m.warehouse_unit_price != null) next[m.type_id] = String(m.warehouse_unit_price)
      })
      return next
    })
  }

  const shoppingList = availability
    ? Object.values(availability).filter(m => m.shortfall > 0).map(m => `${m.name}\t${m.shortfall}`).join('\n')
    : ''

  // when the Save-as-PAK panel opens: auto Initial Contract + auto product prices
  useEffect(() => {
    if (!saveOpen || !result || !product?.type_id) return
    const initial = Math.round((result.results.total_material_cost || 0) + (result.bpc_cost || 0))
    setJobForm(f => ({
      ...f,
      initial_contract_price: f.initial_contract_price || String(initial),
      project_id: f.project_id || calcProjectId || '',
    }))

    setPakPriceLoading(true)
    Promise.all([
      fetchMarketPrices([product.type_id], 'Jita').catch(() => ({})),
      fetchMarketPrices([product.type_id], 'C-J').catch(() => ({})),
    ]).then(([jita, cj]) => {
      const jp = jita[product.type_id], cp = cj[product.type_id]
      setJobForm(f => ({
        ...f,
        jita_sell: jp?.Sell != null ? jp.Sell.toFixed(2) : f.jita_sell,
        jita_buy:  jp?.Buy  != null ? jp.Buy.toFixed(2)  : f.jita_buy,
        cj_sell:   cp?.Sell != null ? cp.Sell.toFixed(2) : f.cj_sell,
        cj_buy:    cp?.Buy  != null ? cp.Buy.toFixed(2)  : f.cj_buy,
      }))
    }).finally(() => setPakPriceLoading(false))
  }, [saveOpen, result, product?.type_id])

  // prefill PAK code + contract code from the selected project's code
  useEffect(() => {
    if (!jobForm.project_id) return
    const proj = projects.find(p => String(p.id) === String(jobForm.project_id))
    if (proj?.org_project_code) {
      setJobForm(f => ({
        ...f,
        code: f.code || proj.org_project_code,
        contract_code: f.contract_code || `${proj.org_project_code} ${product?.name || ''}`.trim(),
      }))
    }
  }, [jobForm.project_id, projects, product?.name])

  async function saveJob() {
    if (!result) return
    setSaveLoading(true); setSaved(false)
    try {
      const f = facilities.find(f => f.id === Number(params.facility_id))

      // fold "Other" target detail into the note
      let note = jobForm.note || null
      if (jobForm.target === 'Other' && jobForm.target_other) {
        note = (note ? note + ' | ' : '') + 'Target: ' + jobForm.target_other
      }

      await post('/manufacturing/jobs', {
        product_type_id: product.type_id,
        product_name: result.output.name,
        blueprint_type_id: bpInfo.blueprint_type_id,
        blueprint_name: bpInfo.blueprint_name,
        facility_id: params.facility_id ? Number(params.facility_id) : null,
        project_id: jobForm.project_id ? Number(jobForm.project_id) : null,
        runs: Number(params.runs), me: Number(params.me), te: Number(params.te),
        bpc_cost: Number(params.bpc_cost),
        paks: jobForm.paks ? Number(jobForm.paks) : null,
        units_per_pak: jobForm.units_per_pak ? Number(jobForm.units_per_pak) : null,
        pack_tier: jobForm.pack_tier || null,
        pak_reward: returnContract ? Math.round(pakRewardCalc) : null,
        sell_price: Number(params.output_price),
        jita_sell: jobForm.jita_sell ? Number(jobForm.jita_sell) : null,
        jita_buy: jobForm.jita_buy ? Number(jobForm.jita_buy) : null,
        cj_sell: jobForm.cj_sell ? Number(jobForm.cj_sell) : null,
        cj_buy: jobForm.cj_buy ? Number(jobForm.cj_buy) : null,
        initial_contract_price: jobForm.initial_contract_price ? Number(jobForm.initial_contract_price) : null,
        return_contract_price: jobForm.return_contract_price ? Number(jobForm.return_contract_price) : null,
        status: jobForm.status,
        target: jobForm.target || null,
        place: jobForm.place || f?.system_name || null,
        code: jobForm.code || null,
        contract_code: jobForm.contract_code || null,
        note,
        calc_snapshot: result,
      })
      setSaved(true); setSaveOpen(false)
    } catch (e) { setError(e.message) }
    finally { setSaveLoading(false) }
  }

  const setP = k => e => setParams(p => ({ ...p, [k]: e.target.value }))
  const setJ = k => e => setJobForm(f => ({ ...f, [k]: e.target.value }))

  const profit = result?.results?.profit ?? 0
  const margin = result?.results?.margin_pct ?? 0

  // PAK economics — Reward = Return − Initial − Job(install) cost
  const jobInstallCost  = result?.job_cost?.net_install_cost ?? 0
  const initialContract = Number(jobForm.initial_contract_price) || 0
  const returnContract  = Number(jobForm.return_contract_price) || 0
  const pakRewardCalc   = returnContract ? returnContract - initialContract - jobInstallCost : 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {error && <div className="error-box">{error}</div>}

      {/* ── Controls ── */}
      <div className="card">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px,1fr))', gap: 14 }}>
          <div style={{ gridColumn: '1 / -1' }}>
            <CLabel>Product to manufacture</CLabel>
            <TypeSearch value={product} onChange={t => setProduct(t?.type_id ? t : null)} placeholder="Search product…" />
            {bpLoading && <span style={{ fontSize: 11, color: 'var(--text)' }}>Loading blueprint…</span>}
            {bpInfo && <span style={{ fontSize: 11, color: 'var(--success)' }}>✓ {bpInfo.blueprint_name} · {bpInfo.qty_per_run} units/run · {fmtTime(bpInfo.base_time_per_run)}/run</span>}
          </div>
          <NumField label="Runs" value={params.runs} onChange={setP('runs')} min={1} />
          <NumField label="ME (0–10)" value={params.me} onChange={setP('me')} min={0} max={10} />
          <NumField label="TE (0–20)" value={params.te} onChange={setP('te')} min={0} max={20} />
          <NumField label="BPC Cost (ISK)" value={params.bpc_cost} onChange={setP('bpc_cost')} step={1000} />
          <div>
            <CLabel>Facility</CLabel>
            <select value={params.facility_id} onChange={setP('facility_id')}>
              <option value="">— none —</option>
              {facilities.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}
            </select>
          </div>
          <NumField label="System Cost Index %" value={params.system_cost_index} onChange={setP('system_cost_index')} step={0.001} />
          <NumField label="Facility Tax %" value={params.facility_tax_pct} onChange={setP('facility_tax_pct')} step={0.1} />
          <NumField label="Structure Bonus %" value={params.structure_bonus_pct} onChange={setP('structure_bonus_pct')} step={0.1} />
          <div>
            <CLabel>Sell Price / unit</CLabel>
            <input type="number" value={params.output_price} onChange={setP('output_price')} step={100} />
            <PriceSourceRow
              market={outMarket} setMarket={setOutMarket}
              method={outMethod} setMethod={setOutMethod}
              onFill={fillOutputPrice} loading={outPriceLoading}
              disabled={!product?.type_id}
            />
          </div>
          <NumField label="Broker Fee %" value={params.broker_fee_pct} onChange={setP('broker_fee_pct')} step={0.1} />
          <NumField label="Est. Item Value (opt.)" value={params.estimated_item_value} onChange={setP('estimated_item_value')} step={1000000} placeholder="auto" />
        </div>
      </div>

      {/* ── Production modifiers (dogma) ── */}
      {rigBonus && (() => {
        const tot = rigTotals()
        const role = rigBonus.structure_role || {}
        const roleMe = role.material_pct || 0, roleTe = role.time_pct || 0, roleCost = role.cost_pct || 0
        const me = Number(params.me), te = Number(params.te)
        // net multiplicative reductions (what EVE actually applies)
        const netMe = (1 - (1 - me / 100) * (1 - tot.me / 100) * (1 - roleMe / 100)) * 100
        const netTe = (1 - (1 - te / 100) * (1 - tot.te / 100) * (1 - roleTe / 100)) * 100
        return (
          <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
            <div style={{
              display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
              padding: '9px 16px', background: 'var(--surface2)', borderBottom: '1px solid var(--border)',
            }}>
              <span style={{ fontSize: 12, fontWeight: 700, letterSpacing: 1, color: 'var(--accent)' }}>PRODUCTION MODIFIERS</span>
              <span style={{ fontSize: 11, color: 'var(--text)' }}>
                security <b style={{ color: 'var(--accent)' }}>{rigBonus.band}</b>
                {rigBonus.product_group ? ` · ${rigBonus.product_group}` : ''}
                {rigBonus.facility_type ? ` · ${rigBonus.facility_type}` : ''}
              </span>
            </div>

            {/* column headers */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 90px 90px 90px', gap: 0, padding: '6px 16px', fontSize: 10, color: 'var(--text)', borderBottom: '1px solid var(--border)' }}>
              <span>MODIFIER</span>
              <span style={{ textAlign: 'right' }}>MATERIAL</span>
              <span style={{ textAlign: 'right' }}>TIME</span>
              <span style={{ textAlign: 'right' }}>COST</span>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column' }}>
              <ModRow label="Blueprint Efficiency" me={me} te={te} />
              {rigBonus.rigs.map((r, i) => {
                const on = !!enabledRigs[r.type_id]
                const hasData = r.me_pct != null
                return (
                  <div key={i} style={{ display: 'grid', gridTemplateColumns: '1fr 90px 90px 90px', alignItems: 'center', padding: '6px 16px', borderTop: '1px solid var(--border)' }}>
                    <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: hasData ? 'pointer' : 'default', minWidth: 0 }}>
                      <input type="checkbox" checked={on} disabled={!hasData}
                        onChange={e => setEnabledRigs(prev => ({ ...prev, [r.type_id]: e.target.checked }))} />
                      <span style={{ fontSize: 12, color: on ? 'var(--text-white)' : 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {r.name.replace('Standup M-Set ', '')}
                        {hasData && !r.applies && <span style={{ color: 'var(--border2)', fontSize: 10 }}> · auto-skipped</span>}
                      </span>
                    </label>
                    <Pct v={on ? r.me_pct : 0} />
                    <Pct v={on ? r.te_pct : 0} />
                    <Pct v={on ? r.cost_pct : 0} />
                  </div>
                )
              })}
              {(roleMe || roleTe || roleCost) ? (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 90px 90px 90px', alignItems: 'center', padding: '6px 16px', borderTop: '1px solid var(--border)' }}>
                  <span style={{ fontSize: 12, color: 'var(--text-white)' }}>Structure Role Bonus{role.name ? ` (${role.name})` : ''}</span>
                  <Pct v={roleMe} /><Pct v={roleTe} /><Pct v={roleCost} />
                </div>
              ) : null}

              {/* net effective */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 90px 90px 90px', alignItems: 'center', padding: '8px 16px', borderTop: '2px solid var(--border2)', background: 'var(--surface2)' }}>
                <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-white)' }}>Effective reduction</span>
                <Pct v={+netMe.toFixed(2)} bold />
                <Pct v={+netTe.toFixed(2)} bold />
                <Pct v={+(tot.cost + roleCost).toFixed(2)} bold />
              </div>
            </div>
          </div>
        )
      })()}

      {/* ── Materials ── */}
      {bpInfo && bpInfo.materials.length > 0 && (
        <div className="card" style={{ padding: 0 }}>
          <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 13, color: 'var(--text-white)', fontWeight: 500 }}>Input Materials — unit costs (ISK)</span>
            <div style={{ marginLeft: 'auto' }}>
              <PriceSourceRow
                market={matMarket} setMarket={setMatMarket}
                method={matMethod} setMethod={setMatMethod}
                onFill={fillMaterialPrices} loading={matPriceLoading}
              />
            </div>
          </div>
          {/* warehouse controls */}
          <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', background: 'var(--surface2)' }}>
            <span style={{ fontSize: 11, color: 'var(--text)' }}>Warehouse / project:</span>
            <select value={calcProjectId} onChange={e => { setCalcProjectId(e.target.value); setAvailability(null) }} style={{ width: 180, fontSize: 12 }}>
              <option value="">Unassigned stock</option>
              {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            <button className="btn btn-ghost btn-sm" onClick={checkWarehouse} disabled={availLoading}>
              {availLoading ? '📦…' : '📦 Check warehouse'}
            </button>
            {availability && (
              <button className="btn btn-ghost btn-sm" onClick={useWarehousePrices}>
                Use warehouse prices
              </button>
            )}
          </div>
          <table>
            <thead>
              <tr>
                <th>Item</th>
                <th>Base Qty (×{params.runs} runs)</th>
                <th>After ME{params.me}</th>
                <th>Saved</th>
                {availability && <th>Have</th>}
                {availability && <th>Short</th>}
                <th>Unit Cost (ISK)</th>
                <th>Gross Cost</th>
              </tr>
            </thead>
            <tbody>
              {bpInfo.materials.map(m => {
                const adjQty = adjQtyOf(m)
                const baseQty = m.base_qty * Number(params.runs)
                const price = Number(matPrices[m.type_id] || 0)
                const grossCost = adjQty * price
                const av = availability?.[m.type_id]
                return (
                  <tr key={m.type_id}>
                    <td style={{ color: 'var(--text-white)', whiteSpace: 'nowrap' }}>{m.name}</td>
                    <td style={{ color: 'var(--text)' }}>{baseQty.toLocaleString()}</td>
                    <td style={{ color: 'var(--accent)', fontWeight: 500 }}>{adjQty.toLocaleString()}</td>
                    <td style={{ color: '#4caf7d', fontSize: 12 }}>{(baseQty - adjQty).toLocaleString()}</td>
                    {availability && (
                      <td style={{ color: av && av.available >= adjQty ? '#4caf7d' : 'var(--text)' }}>
                        {av ? av.available.toLocaleString() : '0'}
                      </td>
                    )}
                    {availability && (
                      <td style={{ color: av && av.shortfall > 0 ? '#e05252' : 'var(--text)' }}>
                        {av && av.shortfall > 0 ? av.shortfall.toLocaleString() : '✓'}
                      </td>
                    )}
                    <td style={{ minWidth: 140 }}>
                      <input
                        type="number" min="0" step="0.01"
                        value={matPrices[m.type_id]}
                        onChange={e => setMatPrices(p => ({ ...p, [m.type_id]: e.target.value }))}
                        placeholder="0"
                      />
                    </td>
                    <td style={{ color: price ? 'var(--text-white)' : 'var(--text)', whiteSpace: 'nowrap' }}>
                      {price ? fmtIsk(grossCost) : '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          {shoppingList && (
            <div style={{ padding: '14px 16px', borderTop: '1px solid var(--border)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
                <span style={{ fontSize: 12, color: '#e05252', fontWeight: 600 }}>🛒 Shopping list (shortfall) — paste into EVE multibuy</span>
                <button className="btn btn-ghost btn-sm" onClick={() => navigator.clipboard.writeText(shoppingList)}>Copy</button>
              </div>
              <textarea readOnly value={shoppingList} rows={Math.min(shoppingList.split('\n').length, 10)}
                style={{ fontFamily: 'monospace', fontSize: 12 }} />
            </div>
          )}
        </div>
      )}

      <div style={{ display: 'flex', gap: 10 }}>
        <button className="btn btn-primary" onClick={calculate} disabled={!bpInfo || calcLoading}>
          {calcLoading ? 'Calculating…' : '⚡ Calculate'}
        </button>
        {result && (
          <button className="btn btn-ghost" onClick={() => { setSaveOpen(v => !v); setSaved(false) }}>
            💾 Save as PAK Job
          </button>
        )}
      </div>

      {/* ── Results ── */}
      {result && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

          {/* Output */}
          <Section title="Manufacturing Output">
            <table>
              <thead><tr><th>Item</th><th>Quantity</th><th>Unit Price</th><th>Gross Sell</th><th>Net Sell</th></tr></thead>
              <tbody>
                <tr>
                  <td style={{ color: 'var(--accent)' }}>{result.output.name}</td>
                  <td>{result.output.quantity.toLocaleString()}</td>
                  <td>{fmtIsk(result.output.unit_price)}</td>
                  <td>{fmtIsk(result.output.gross_sell)}</td>
                  <td style={{ color: '#4caf7d' }}>{fmtIsk(result.output.net_sell)}</td>
                </tr>
              </tbody>
            </table>
          </Section>

          {/* Materials */}
          <Section title="Input Materials">
            <table>
              <thead>
                <tr><th>Item</th><th>Quantity</th><th>Waste (ME)</th><th>Unit Cost</th><th>Gross Cost</th><th>Net Cost</th></tr>
              </thead>
              <tbody>
                {result.materials.map(m => (
                  <tr key={m.type_id}>
                    <td style={{ color: 'var(--text-white)', whiteSpace: 'nowrap' }}>{m.name}</td>
                    <td>{m.adj_qty.toLocaleString()}</td>
                    <td style={{ color: m.saved > 0 ? '#4caf7d' : 'var(--text)' }}>
                      {m.saved > 0 ? `-${m.saved.toLocaleString()}` : '0'}
                    </td>
                    <td>{fmtIsk(m.unit_cost)}</td>
                    <td>{fmtIsk(m.gross_cost)}</td>
                    <td style={{ color: 'var(--text-bright)' }}>{fmtIsk(m.net_cost)}</td>
                  </tr>
                ))}
                <tr style={{ background: 'var(--surface2)' }}>
                  <td colSpan={4} style={{ textAlign: 'right', color: 'var(--text)', fontWeight: 500 }}>Total Materials Cost</td>
                  <td colSpan={2} style={{ color: 'var(--accent)', fontWeight: 600 }}>{fmtIsk(result.materials_total_gross)}</td>
                </tr>
              </tbody>
            </table>
          </Section>

          {/* Job Installation Cost */}
          <Section title="Job Installation Cost">
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(160px,1fr))', gap: 14, padding: 4 }}>
              <IskStat label="Est. Item Value" value={result.job_cost.estimated_item_value} />
              <PctStat label="System Cost Index" value={result.job_cost.system_cost_index_pct} />
              <IskStat label="System Cost" value={result.job_cost.system_cost} />
              <IskStat label="Structure Bonus" value={-result.job_cost.structure_bonus} color="#4caf7d" />
              <IskStat label="Gross Install Cost" value={result.job_cost.gross_install_cost} />
              <IskStat label="Facility Tax" value={result.job_cost.facility_tax} color="#e05252" />
              <IskStat label="SCC Surcharge (4%)" value={result.job_cost.scc_surcharge} color="#e05252" />
              <IskStat label="Net Install Cost" value={result.job_cost.net_install_cost} color="var(--accent)" bold />
              <IskStat label="BPC Cost" value={result.bpc_cost} />
              <div>
                <div style={statLabel}>Job Time</div>
                <div style={{ color: 'var(--text-white)', fontWeight: 500 }}>{result.job_time.hours.toFixed(2)} h</div>
              </div>
            </div>
          </Section>

          {/* Results */}
          <Section title="Results">
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 16, padding: 4 }}>
              <IskStat label="Total Costs" value={result.results.total_costs} color="var(--text-white)" bold />
              <IskStat label="Total Sell" value={result.results.total_sell} color="#4caf7d" bold />
              <IskStat label="Profit" value={profit} color={profit >= 0 ? '#4caf7d' : '#e05252'} bold />
              <div>
                <div style={statLabel}>Margin</div>
                <div style={{
                  fontWeight: 700, fontSize: 20,
                  color: margin >= 0 ? '#4caf7d' : '#e05252',
                  background: margin >= 0 ? '#0e2a1a' : '#2a0e0e',
                  padding: '4px 10px', borderRadius: 4, display: 'inline-block',
                }}>
                  {margin.toFixed(2)}%
                </div>
              </div>
            </div>
          </Section>
        </div>
      )}

      {/* ── Save Job Form ── */}
      {saveOpen && result && (
        <div className="card">
          <h3 style={{ marginBottom: 16, fontSize: 14 }}>Save as PAK Job</h3>
          {saved && <div style={{ color: '#4caf7d', marginBottom: 10 }}>✓ Job saved!</div>}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(180px,1fr))', gap: 12 }}>
            <div>
              <CLabel>Project</CLabel>
              <select value={jobForm.project_id} onChange={setJ('project_id')}>
                <option value="">No project</option>
                {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </div>
            <div>
              <CLabel>Status</CLabel>
              <select value={jobForm.status} onChange={setJ('status')}>
                {['Planning','Preparing','In Progress','Completed','Cancelled'].map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div>
              <CLabel>Target</CLabel>
              <select value={jobForm.target} onChange={setJ('target')}>
                <option value="">—</option>
                {['Reactions','Refueling','Sell','Internal','Other'].map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            {jobForm.target === 'Other' && (
              <CInput label="Target details" value={jobForm.target_other} onChange={setJ('target_other')} placeholder="describe target" />
            )}
            <CInput label="Place / System" value={jobForm.place} onChange={setJ('place')} placeholder="RYC-19" />
            <CInput label="PAKs" type="number" value={jobForm.paks} onChange={setJ('paks')} />
            <CInput label="Units per PAK" type="number" value={jobForm.units_per_pak} onChange={setJ('units_per_pak')} />
            <CInput label="Pack Tier" value={jobForm.pack_tier} onChange={setJ('pack_tier')} placeholder="F" />

            <div>
              <CLabel>Initial Contract (ISK) <Hint>materials + BPC, auto</Hint></CLabel>
              <input type="number" value={jobForm.initial_contract_price} onChange={setJ('initial_contract_price')} placeholder="0" />
            </div>
            <div>
              <CLabel>Return Contract (ISK) <Hint>you set this</Hint></CLabel>
              <input type="number" value={jobForm.return_contract_price} onChange={setJ('return_contract_price')} placeholder="0" />
            </div>
            <div>
              <CLabel>PAK Reward <Hint>Return − Initial − Job</Hint></CLabel>
              <div style={{
                padding: '7px 10px', borderRadius: 4, fontWeight: 600,
                background: 'var(--surface3)', border: '1px solid var(--border2)',
                color: pakRewardCalc > 0 ? '#4caf7d' : pakRewardCalc < 0 ? '#e05252' : 'var(--text)',
              }}>
                {returnContract ? fmtIsk(pakRewardCalc) : '— set Return Contract'}
              </div>
            </div>

            <div style={{ gridColumn: '1 / -1', fontSize: 11, color: 'var(--text)', display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ color: 'var(--accent)' }}>Market prices</span>
              {pakPriceLoading ? <span>fetching Jita + C-J…</span> : <span>auto-filled (editable)</span>}
            </div>
            <CInput label="Jita SELL" type="number" value={jobForm.jita_sell} onChange={setJ('jita_sell')} />
            <CInput label="Jita BUY" type="number" value={jobForm.jita_buy} onChange={setJ('jita_buy')} />
            <CInput label="C-J SELL" type="number" value={jobForm.cj_sell} onChange={setJ('cj_sell')} />
            <CInput label="C-J BUY" type="number" value={jobForm.cj_buy} onChange={setJ('cj_buy')} />
            <CInput label="Code" value={jobForm.code} onChange={setJ('code')} placeholder="gud63" />
            <div style={{ gridColumn: '1 / -1' }}>
              <CLabel>Contract Code</CLabel>
              <input value={jobForm.contract_code} onChange={setJ('contract_code')} placeholder="gud63 ASCEE Tier F: 180.000.000 @RYC-19" />
            </div>
            <div style={{ gridColumn: '1 / -1' }}>
              <CLabel>Note</CLabel>
              <textarea value={jobForm.note} onChange={setJ('note')} rows={2} />
            </div>
          </div>
          <div style={{ display: 'flex', gap: 10, marginTop: 14, justifyContent: 'flex-end' }}>
            <button className="btn btn-ghost" onClick={() => setSaveOpen(false)}>Cancel</button>
            <button className="btn btn-primary" onClick={saveJob} disabled={saveLoading}>
              {saveLoading ? 'Saving…' : '💾 Save Job'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

/* ═══════════════════════════ PAK JOBS TABLE ═══════════════════════════ */

function PakJobsTab() {
  const [jobs, setJobs]         = useState([])
  const [projects, setProjects] = useState([])
  const [filter, setFilter]     = useState({ project_id: '', status: '' })
  const [expand, setExpand]     = useState(null)

  async function load() {
    const params = new URLSearchParams()
    if (filter.project_id) params.set('project_id', filter.project_id)
    if (filter.status)     params.set('job_status', filter.status)
    try { setJobs(await get(`/manufacturing/jobs?${params}`)) } catch {}
  }

  useEffect(() => {
    get('/organisations').then(async orgs => {
      const all = []
      for (const o of orgs) {
        try { const ps = await get(`/projects?org_id=${o.id}`); all.push(...ps) } catch {}
      }
      setProjects(all)
    }).catch(() => {})
  }, [])

  useEffect(() => { load() }, [filter])

  async function updateStatus(id, status) {
    try { await patch(`/manufacturing/jobs/${id}`, { status }); load() } catch {}
  }

  async function remove(id) {
    if (!confirm('Delete PAK job?')) return
    try { await del(`/manufacturing/jobs/${id}`); load() } catch {}
  }

  return (
    <div>
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        <select value={filter.project_id} onChange={e => setFilter(f => ({ ...f, project_id: e.target.value }))} style={{ width: 200 }}>
          <option value="">All projects</option>
          {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <select value={filter.status} onChange={e => setFilter(f => ({ ...f, status: e.target.value }))} style={{ width: 160 }}>
          <option value="">All statuses</option>
          {['Planning','Preparing','In Progress','Completed','Cancelled'].map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <button className="btn btn-ghost btn-sm" onClick={load}>Refresh</button>
      </div>

      {jobs.length === 0
        ? <div className="empty-state">No production jobs yet — use Calculator tab to create one</div>
        : (
          <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Date</th>
                  <th>Place</th>
                  <th>Product</th>
                  <th>PAKs</th>
                  <th>Amount</th>
                  <th>Unit Price</th>
                  <th>Target</th>
                  <th>Status</th>
                  <th>Released</th>
                  <th>Note</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {jobs.map(j => {
                  const units = j.paks && j.units_per_pak ? j.paks * j.units_per_pak : (j.calc_snapshot?.output?.quantity ?? '—')
                  return [
                    <tr key={j.id} style={{ cursor: 'pointer' }} onClick={() => setExpand(expand === j.id ? null : j.id)}>
                      <td style={{ color: 'var(--text)' }}>{j.id}</td>
                      <td style={{ color: 'var(--text)', fontSize: 12 }}>{j.date_planned ? new Date(j.date_planned).toLocaleDateString() : '—'}</td>
                      <td style={{ color: 'var(--text)', fontSize: 12 }}>{j.place || '—'}</td>
                      <td style={{ color: 'var(--accent)', whiteSpace: 'nowrap' }}>{j.product_name}</td>
                      <td style={{ color: 'var(--text-white)' }}>{j.paks ?? '—'}</td>
                      <td>{typeof units === 'number' ? units.toLocaleString() : units}</td>
                      <td style={{ color: 'var(--text)' }}>{j.sell_price ? fmtIsk(j.sell_price) : '—'}</td>
                      <td style={{ fontSize: 12 }}>{j.target || '—'}</td>
                      <td>
                        <select
                          value={j.status}
                          onClick={e => e.stopPropagation()}
                          onChange={e => updateStatus(j.id, e.target.value)}
                          style={{ width: 110, color: STATUS_COLOR[j.status] || 'var(--text)', background: 'var(--surface)', border: '1px solid var(--border)', padding: '3px 6px', fontSize: 12 }}
                        >
                          {['Planning','Preparing','In Progress','Completed','Cancelled'].map(s =>
                            <option key={s} value={s}>{s}</option>
                          )}
                        </select>
                      </td>
                      <td style={{ color: 'var(--text)', fontSize: 12 }}>{j.date_released ? new Date(j.date_released).toLocaleDateString() : '—'}</td>
                      <td style={{ color: 'var(--text)', fontSize: 12, maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis' }}>{j.note || '—'}</td>
                      <td><button className="btn btn-danger btn-sm" onClick={e => { e.stopPropagation(); remove(j.id) }}>✕</button></td>
                    </tr>,
                    expand === j.id && j.calc_snapshot && (
                      <tr key={`exp-${j.id}`}>
                        <td colSpan={12} style={{ background: 'var(--surface2)', padding: 0 }}>
                          <PakCard job={j} onChange={load} />
                        </td>
                      </tr>
                    )
                  ]
                })}
              </tbody>
            </table>
          </div>
        )
      }
    </div>
  )
}

function PakCard({ job, onChange }) {
  const s = job.calc_snapshot
  const [movements, setMovements] = useState([])
  const [issuing, setIssuing]     = useState(false)
  const [issueMsg, setIssueMsg]   = useState('')

  async function loadMovements() {
    try { setMovements(await get(`/manufacturing/jobs/${job.id}/movements`)) } catch {}
  }

  useEffect(() => { loadMovements() }, [job.id])

  async function issue(force = false) {
    const already = movements.length > 0
    if (already && !force) {
      if (!confirm('Materials already issued for this job. Issue again (deduct more stock)?')) return
      force = true
    } else if (!confirm('Deduct this job\'s materials from the warehouse and log the write-off?')) {
      return
    }
    setIssuing(true); setIssueMsg('')
    try {
      const res = await post(`/manufacturing/jobs/${job.id}/issue${force ? '?force=true' : ''}`, {})
      const shorts = res.shortfalls || []
      setIssueMsg(
        `✓ Consumed ${res.materials.filter(m => m.consumed > 0).length} materials · ${fmtIsk(res.total_cost)}` +
        (shorts.length ? ` · ⚠ ${shorts.length} short: ${shorts.map(x => x.name + ' (-' + x.shortfall + ')').join(', ')}` : '')
      )
      await loadMovements()
      onChange?.()
    } catch (e) { setIssueMsg('⚠ ' + e.message) }
    finally { setIssuing(false) }
  }

  if (!s) {
    return (
      <div style={{ padding: 20 }}>
        <span style={{ color: 'var(--text)', fontSize: 12 }}>No calculation snapshot for this job.</span>
      </div>
    )
  }
  const r = s.results
  const j = s.job_cost
  const roi = job.pak_reward && r.total_costs
    ? ((job.pak_reward / (r.total_costs)) * 100).toFixed(2)
    : null

  return (
    <div style={{ padding: 20, display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(200px,1fr))', gap: 20 }}>
      <CardSection title="Info">
        <Row label="Module"  value={job.product_name} />
        <Row label="Station" value={job.place} />
        <Row label="Pack Tier" value={job.pack_tier} />
        <Row label="PAKs" value={job.paks} />
        <Row label="Units/PAK" value={job.units_per_pak} />
      </CardSection>
      <CardSection title="Inputs">
        <Row label="Job time" value={s.job_time ? s.job_time.hours.toFixed(2) + ' h' : '—'} />
        <Row label="Material cost" value={fmtIsk(r.total_material_cost)} />
        <Row label="BPC cost" value={fmtIsk(s.bpc_cost)} />
        <Row label="Install cost" value={fmtIsk(r.total_install_cost)} />
        <Row label="TOTAL INPUT" value={fmtIsk(r.total_costs)} accent />
      </CardSection>
      <CardSection title="Reward">
        <Row label="Job cost (install)" value={fmtIsk(j.net_install_cost)} />
        <Row label="PAK reward" value={job.pak_reward ? fmtIsk(job.pak_reward) : '—'} />
        <Row label="Reward/hour" value={job.pak_reward && s.job_time?.hours ? fmtIsk(job.pak_reward / s.job_time.hours) : '—'} />
      </CardSection>
      {roi && (
        <CardSection title="Indicators">
          <Row label="ROI" value={roi + '%'} />
        </CardSection>
      )}
      <CardSection title="PAK Prices">
        <Row label="Initial contract" value={job.initial_contract_price ? fmtIsk(job.initial_contract_price) : '—'} />
        <Row label="Return contract" value={job.return_contract_price ? fmtIsk(job.return_contract_price) : '—'} />
        <Row label="Unit cost" value={s.output ? fmtIsk(r.total_costs / s.output.quantity) : '—'} />
      </CardSection>
      <CardSection title="Prices">
        <Row label="Jita SELL" value={job.jita_sell ? fmtIsk(job.jita_sell) : '—'} />
        <Row label="Jita BUY"  value={job.jita_buy  ? fmtIsk(job.jita_buy)  : '—'} />
        <Row label="C-J SELL"  value={job.cj_sell   ? fmtIsk(job.cj_sell)   : '—'} />
        <Row label="C-J BUY"   value={job.cj_buy    ? fmtIsk(job.cj_buy)    : '—'} />
      </CardSection>
      {(job.code || job.contract_code) && (
        <CardSection title="Codes" style={{ gridColumn: '1 / -1' }}>
          <Row label="CODE" value={job.code} />
          <Row label="CONTRACT CODE" value={job.contract_code} mono />
        </CardSection>
      )}

      {/* Material write-off / issue */}
      <CardSection title="Warehouse write-off" style={{ gridColumn: '1 / -1' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: movements.length ? 10 : 0 }}>
          <button className="btn btn-primary btn-sm" onClick={() => issue(false)} disabled={issuing}>
            {issuing ? 'Issuing…' : movements.length ? '📦 Issue again' : '📦 Issue materials'}
          </button>
          <span style={{ fontSize: 11, color: 'var(--text)' }}>
            Deducts the job's materials from {job.project_id ? 'the project' : 'unassigned'} stock (FIFO) and logs it.
          </span>
          {issueMsg && (
            <span style={{ fontSize: 12, color: issueMsg.startsWith('⚠') ? '#e05252' : '#4caf7d' }}>{issueMsg}</span>
          )}
        </div>
        {movements.length > 0 && (
          <table style={{ marginTop: 6 }}>
            <thead>
              <tr><th>Date</th><th>Material</th><th>Qty</th><th>Unit Cost</th><th>Total</th><th>Reason</th></tr>
            </thead>
            <tbody>
              {movements.map(mv => (
                <tr key={mv.id}>
                  <td style={{ color: 'var(--text)', fontSize: 11 }}>{mv.created_at ? new Date(mv.created_at).toLocaleString() : '—'}</td>
                  <td style={{ color: 'var(--text-white)' }}>{mv.name}</td>
                  <td style={{ color: '#e05252' }}>-{mv.quantity.toLocaleString()}</td>
                  <td style={{ color: 'var(--text)' }}>{fmtIsk(mv.unit_cost)}</td>
                  <td style={{ color: 'var(--text-bright)' }}>{fmtIsk(mv.total_cost)}</td>
                  <td style={{ color: 'var(--text)', fontSize: 11 }}>{mv.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </CardSection>
    </div>
  )
}

/* ═══════════════════════════ INVENTORY ANALYSIS ═══════════════════════════ */

function InventoryAnalysisTab() {
  const [method, setMethod]     = useState('FIFO')
  const [orgId, setOrgId]       = useState('')
  const [projectId, setProjectId] = useState('')
  const [orgs, setOrgs]         = useState([])
  const [projects, setProjects] = useState([])
  const [data, setData]         = useState(null)
  const [loading, setLoading]   = useState(false)

  useEffect(() => {
    get('/organisations').then(async os => {
      setOrgs(os)
      const all = []
      for (const o of os) {
        try { all.push(...(await get(`/projects?org_id=${o.id}`))) } catch {}
      }
      setProjects(all)
    }).catch(() => {})
  }, [])

  const visibleProjects = orgId
    ? projects.filter(p => String(p.organisation_id) === String(orgId))
    : projects

  async function analyze() {
    setLoading(true)
    try {
      const params = new URLSearchParams({ method })
      if (projectId) params.set('project_id', projectId)
      else if (orgId) params.set('organisation_id', orgId)
      const res = await get(`/manufacturing/inventory-analysis?${params}`)
      setData(res)
    } catch {}
    finally { setLoading(false) }
  }

  const totalValue = data?.items?.reduce((s, i) => s + i.total_value_isk, 0) ?? 0

  return (
    <div>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 20, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', gap: 6 }}>
          {['FIFO','LIFO'].map(m => (
            <button
              key={m} className={`btn ${method === m ? 'btn-primary' : 'btn-ghost'} btn-sm`}
              onClick={() => setMethod(m)}
            >{m}</button>
          ))}
        </div>
        <select value={orgId} onChange={e => { setOrgId(e.target.value); setProjectId('') }} style={{ width: 180 }}>
          <option value="">All organisations</option>
          {orgs.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select>
        <select value={projectId} onChange={e => setProjectId(e.target.value)} style={{ width: 180 }}>
          <option value="">All projects{orgId ? ' (in org)' : ''}</option>
          {visibleProjects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <button className="btn btn-primary btn-sm" onClick={analyze} disabled={loading}>
          {loading ? 'Analyzing…' : '📊 Analyze'}
        </button>
      </div>

      {data && (
        <>
          <div style={{ display: 'flex', gap: 20, marginBottom: 14 }}>
            <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 6, padding: '8px 16px' }}>
              <div style={{ fontSize: 11, color: 'var(--text)' }}>Method</div>
              <div style={{ color: 'var(--accent)', fontWeight: 700, fontSize: 16 }}>{data.method}</div>
            </div>
            <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 6, padding: '8px 16px' }}>
              <div style={{ fontSize: 11, color: 'var(--text)' }}>Total inventory value</div>
              <div style={{ color: 'var(--text-white)', fontWeight: 500 }}>{fmtIsk(totalValue)}</div>
            </div>
            <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 6, padding: '8px 16px' }}>
              <div style={{ fontSize: 11, color: 'var(--text)' }}>Unique items</div>
              <div style={{ color: 'var(--text-white)', fontWeight: 500 }}>{data.items.length}</div>
            </div>
          </div>

          <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th>Item</th>
                  <th>Total Qty</th>
                  <th>Lots</th>
                  <th>{data.method} Avg Cost / unit</th>
                  <th>Total Value</th>
                  <th>% of total</th>
                </tr>
              </thead>
              <tbody>
                {[...data.items]
                  .sort((a, b) => b.total_value_isk - a.total_value_isk)
                  .map(item => (
                    <tr key={item.key}>
                      <td style={{ color: 'var(--text-white)', whiteSpace: 'nowrap' }}>{item.name}</td>
                      <td>{item.total_qty.toLocaleString()}</td>
                      <td style={{ color: 'var(--text)', fontSize: 12 }}>{item.lots}</td>
                      <td style={{ color: 'var(--accent)' }}>
                        {item.priced_lots > 0 ? fmtIsk(item.avg_cost_isk) : <span style={{ color: 'var(--text)' }}>no price</span>}
                      </td>
                      <td style={{ color: item.total_value_isk > 0 ? 'var(--text-white)' : 'var(--text)' }}>
                        {item.total_value_isk > 0 ? fmtIsk(item.total_value_isk) : '—'}
                      </td>
                      <td style={{ color: 'var(--text)', fontSize: 12 }}>
                        {totalValue > 0 ? (item.total_value_isk / totalValue * 100).toFixed(1) + '%' : '—'}
                      </td>
                    </tr>
                  ))
                }
              </tbody>
            </table>
          </div>
        </>
      )}
      {!data && <div className="empty-state">Select method and click Analyze</div>}
    </div>
  )
}

/* ═══════════════════════════ UI HELPERS ═══════════════════════════ */

function Section({ title, children }) {
  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden' }}>
      <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--border)', fontSize: 13, fontWeight: 600, color: 'var(--accent)', letterSpacing: 1 }}>
        {title.toUpperCase()}
      </div>
      {children}
    </div>
  )
}

function CardSection({ title, children, style }) {
  return (
    <div style={style}>
      <div style={{ fontSize: 11, color: 'var(--accent)', fontWeight: 700, letterSpacing: 1, marginBottom: 8, borderBottom: '1px solid var(--border)', paddingBottom: 4 }}>{title}</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>{children}</div>
    </div>
  )
}

function Row({ label, value, accent, mono }) {
  if (value == null || value === '') return null
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: 12 }}>
      <span style={{ color: 'var(--text)' }}>{label}</span>
      <span style={{ color: accent ? 'var(--accent)' : 'var(--text-white)', fontFamily: mono ? 'monospace' : undefined, textAlign: 'right', maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis' }}>{value}</span>
    </div>
  )
}

function IskStat({ label, value, color, bold }) {
  return (
    <div>
      <div style={statLabel}>{label}</div>
      <div style={{ color: color || 'var(--text-white)', fontWeight: bold ? 600 : 400 }}>{fmtIsk(value)}</div>
    </div>
  )
}

function PctStat({ label, value }) {
  return (
    <div>
      <div style={statLabel}>{label}</div>
      <div style={{ color: 'var(--text-white)' }}>{value.toFixed(2)}%</div>
    </div>
  )
}

function NumField({ label, value, onChange, min, max, step = 1, placeholder }) {
  return (
    <div>
      <CLabel>{label}</CLabel>
      <input type="number" value={value} onChange={onChange} min={min} max={max} step={step} placeholder={placeholder} />
    </div>
  )
}

function CLabel({ children }) {
  return <label style={{ display: 'block', fontSize: 11, color: 'var(--text)', marginBottom: 5 }}>{children}</label>
}

function Hint({ children }) {
  return <span style={{ fontWeight: 400, color: 'var(--border2)', marginLeft: 4 }}>{children}</span>
}

function Pct({ v, bold }) {
  return (
    <span style={{ textAlign: 'right', fontSize: 12, fontWeight: bold ? 700 : 400, color: v > 0 ? '#4caf7d' : 'var(--border2)' }}>
      {v > 0 ? `−${v}%` : '—'}
    </span>
  )
}

function ModRow({ label, me, te }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 90px 90px 90px', alignItems: 'center', padding: '6px 16px' }}>
      <span style={{ fontSize: 12, color: 'var(--text-white)' }}>{label}</span>
      <Pct v={me} /><Pct v={te} /><Pct v={0} />
    </div>
  )
}

function PriceSourceRow({ market, setMarket, method, setMethod, onFill, loading, disabled }) {
  return (
    <div style={{ display: 'flex', gap: 4, alignItems: 'center', marginTop: 5, flexWrap: 'wrap' }}>
      <select value={market} onChange={e => setMarket(e.target.value)} style={{ width: 60, padding: '2px 4px', fontSize: 11 }}>
        {MARKETS.map(m => <option key={m} value={m}>{m}</option>)}
      </select>
      {METHODS.map(m => (
        <button
          key={m} type="button" onClick={() => setMethod(m)}
          className={`btn btn-sm ${method === m ? 'btn-primary' : 'btn-ghost'}`}
          style={{ padding: '2px 8px', fontSize: 11 }}
        >{m}</button>
      ))}
      <button type="button" className="btn btn-ghost btn-sm" onClick={onFill} disabled={loading || disabled} style={{ padding: '2px 8px', fontSize: 11 }}>
        {loading ? '⚡…' : '⚡ Fill'}
      </button>
    </div>
  )
}

function CInput({ label, value, onChange, type = 'text', placeholder }) {
  return (
    <div>
      <CLabel>{label}</CLabel>
      <input type={type} value={value} onChange={onChange} placeholder={placeholder} />
    </div>
  )
}

const statLabel = { fontSize: 11, color: 'var(--text)', marginBottom: 3 }

function fmtIsk(v) {
  if (v == null || v === '') return '—'
  const n = Number(v)
  if (isNaN(n)) return '—'
  if (Math.abs(n) >= 1e9) return (n / 1e9).toFixed(2) + ' B ISK'
  if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(2) + ' M ISK'
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 }) + ' ISK'
}

function fmtTime(seconds) {
  if (!seconds) return '—'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  return h ? `${h}h ${m}m` : `${m}m`
}
