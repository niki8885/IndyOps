import { useState, useEffect, useCallback, lazy, Suspense } from 'react'
import { get, post, patch, del } from '../api/client'
import TypeSearch from '../components/TypeSearch'

// Plotly (~4MB) only loads when the chain graph actually renders — keeps it out
// of the eagerly-imported Manufacturing bundle.
const ChainGraph = lazy(() => import('../components/ChainGraph'))

const TABS = ['Calculator', 'Chain', 'PAK Jobs', 'Inventory Analysis']

// Major trade-hub regions for chain buy/sell pricing (Fuzzwork aggregates).
const REGIONS = [
  { id: 10000002, name: 'Jita (The Forge)' },
  { id: 10000043, name: 'Amarr (Domain)' },
  { id: 10000032, name: 'Dodixie (Sinq Laison)' },
  { id: 10000030, name: 'Rens (Heimatar)' },
  { id: 10000042, name: 'Hek (Metropolis)' },
]

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
      {tab === 1 && <ChainTab />}
      {tab === 2 && <PakJobsTab />}
      {tab === 3 && <InventoryAnalysisTab />}
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
    runs: 1, windows: 1, me: 0, te: 0,
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

  // market analysis (4-source comparison)
  const [market, setMarket]           = useState(null)   // { rows:[...], totals:{...} }
  const [marketLoading, setMarketLoading] = useState(false)
  const [deliveryOn, setDeliveryOn]   = useState(false)
  const [deliveryCoef, setDeliveryCoef] = useState(1200)  // ISK per m³ (Jita → C-J haul)

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
        runs:    Number(params.runs),
        windows: Number(params.windows) || 1,
        me:      Number(params.me),
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
    const w = Math.max(1, Number(params.windows) || 1)
    const perJob = Math.max(
      Number(params.runs),
      Math.ceil(m.base_qty * params.runs * (1 - params.me / 100) * (1 - rigMe / 100) * (1 - roleMe / 100)),
    )
    return perJob * w
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

  async function analyzeMarket() {
    if (!bpInfo) return
    setMarketLoading(true); setError('')
    try {
      const ids = bpInfo.materials.map(m => m.type_id)
      const [jita, cj] = await Promise.all([
        fetchMarketPrices(ids, 'Jita').catch(() => ({})),
        fetchMarketPrices(ids, 'C-J').catch(() => ({})),
      ])
      const rows = bpInfo.materials.map(m => {
        const qty = adjQtyOf(m)
        const j = jita[m.type_id] || {}, c = cj[m.type_id] || {}
        return {
          type_id: m.type_id, name: m.name, qty, volume: m.volume || 0,
          jita_buy: j.Buy ?? null, jita_sell: j.Sell ?? null,
          cj_buy: c.Buy ?? null, cj_sell: c.Sell ?? null,
        }
      })
      setMarket({ rows })
    } catch (e) { setError('Market analysis failed: ' + e.message) }
    finally { setMarketLoading(false) }
  }

  const marketView = buildMarketView(market?.rows, deliveryOn, deliveryCoef)
  const bestBuyList = bestBuyListOf(marketView)

  // when the Save-as-PAK panel opens: auto Initial Contract + auto product prices
  useEffect(() => {
    if (!saveOpen || !result || !product?.type_id) return
    const w = result.windows || 1
    // per-PAK initial contract = (materials + BPC) for one window
    const perPakInitial = Math.round(((result.results.total_material_cost || 0) + (result.bpc_cost || 0)) / w)
    const perPakUnits = Math.round((result.output.quantity || 0) / w)
    setJobForm(f => ({
      ...f,
      initial_contract_price: f.initial_contract_price || String(perPakInitial),
      paks: f.paks || String(w),
      units_per_pak: f.units_per_pak || String(perPakUnits),
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
        runs: Number(params.runs), windows: Number(params.windows) || 1,
        me: Number(params.me), te: Number(params.te),
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

  // PAK economics are PER PAK (one window); the batch = windows PAKs.
  const calcWindows     = result?.windows || 1
  const jobInstallCost  = (result?.job_cost?.net_install_cost ?? 0) / calcWindows
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
          <NumField label="Runs / window" value={params.runs} onChange={setP('runs')} min={1} />
          <div>
            <CLabel>Windows (slots) <Hint>{`${params.windows}×${params.runs} = ${(Number(params.windows) || 1) * Number(params.runs)} runs`}</Hint></CLabel>
            <input type="number" value={params.windows} onChange={setP('windows')} min={1} />
          </div>
          <NumField label="ME (0–10)" value={params.me} onChange={setP('me')} min={0} max={10} />
          <NumField label="TE (0–20)" value={params.te} onChange={setP('te')} min={0} max={20} />
          <NumField label="BPC Cost / window" value={params.bpc_cost} onChange={setP('bpc_cost')} step={1000} />
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
                <th>Base Qty ({params.windows}×{params.runs})</th>
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
                const baseQty = m.base_qty * Number(params.runs) * (Number(params.windows) || 1)
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

      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <button className="btn btn-primary" onClick={calculate} disabled={!bpInfo || calcLoading}>
          {calcLoading ? 'Calculating…' : '⚡ Calculate'}
        </button>
        <button className="btn btn-ghost" onClick={analyzeMarket} disabled={!bpInfo || marketLoading}>
          {marketLoading ? 'Analyzing…' : '🔍 Analyze market'}
        </button>
        {result && (
          <button className="btn btn-ghost" onClick={() => { setSaveOpen(v => !v); setSaved(false) }}>
            💾 Save as PAK Job
          </button>
        )}
      </div>

      {/* ── Market analysis ── */}
      {marketView && (
        <MarketPanel
          view={marketView} bestBuyList={bestBuyList}
          deliveryOn={deliveryOn} setDeliveryOn={setDeliveryOn}
          deliveryCoef={deliveryCoef} setDeliveryCoef={setDeliveryCoef}
        />
      )}

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

          {/* Cost composition + production metrics */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            <Section title="Cost Composition">
              <CostPie result={result} />
            </Section>
            <Section title="Production Metrics">
              <ProductionMetrics result={result} />
            </Section>
          </div>
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
              <CLabel>Initial Contract / PAK <Hint>(materials + BPC) ÷ windows</Hint></CLabel>
              <input type="number" value={jobForm.initial_contract_price} onChange={setJ('initial_contract_price')} placeholder="0" />
            </div>
            <div>
              <CLabel>Return Contract / PAK <Hint>you set this</Hint></CLabel>
              <input type="number" value={jobForm.return_contract_price} onChange={setJ('return_contract_price')} placeholder="0" />
            </div>
            <div>
              <CLabel>PAK Reward / PAK <Hint>Return − Initial − Job</Hint></CLabel>
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
              <div style={{ display: 'flex', gap: 8 }}>
                <input value={jobForm.contract_code} onChange={setJ('contract_code')} placeholder="gud63 Tier:F 180.000.000 @RYC-19" />
                <button type="button" className="btn btn-ghost btn-sm" style={{ whiteSpace: 'nowrap' }}
                  onClick={() => {
                    const ret = Number(jobForm.return_contract_price) || 0
                    const code = `${jobForm.code || ''} Tier:${jobForm.pack_tier || ''} ${ret.toLocaleString('de-DE')} @${jobForm.place || ''}`
                      .replace(/\s+/g, ' ').trim()
                    setJobForm(f => ({ ...f, contract_code: code }))
                  }}>
                  ⚙ Generate
                </button>
              </div>
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

/* ═══════════════════════════ CHAIN (MAKE-VS-BUY) ═══════════════════════════ */

function ChainTab() {
  const [product, setProduct]     = useState(null)
  const [facilities, setFacilities] = useState([])

  // global chain params
  const [params, setParams] = useState({
    qty: 1, price_basis: 'buy',
    me_pct: 0, te_pct: 0,
    system_cost_index: 0, facility_tax_pct: 0, structure_discount_pct: 0,
    man_lines: 10, react_lines: 0, max_depth: 12,
  })

  // ── (1) Buy-price region multi-select ──
  const [selectedRegions, setSelectedRegions] = useState(new Set([10000002]))
  const [includeCJ, setIncludeCJ] = useState(false)

  // ── (2) Sell market for profit calculation ──
  const [sellMarket, setSellMarket] = useState('Jita')
  const [sellMethod, setSellMethod] = useState('Sell')
  const [sellPrice, setSellPrice]   = useState(null)
  const [sellLoading, setSellLoading] = useState(false)

  // ── (3) Facility mode: 'none' = single + manual, 'multi' = checklist ──
  const [facilityMode, setFacilityMode] = useState('none')
  const [singleFacilityId, setSingleFacilityId] = useState('')
  // facilityChecks: { [id]: { checked: bool, man: number, react: number } }
  const [facilityChecks, setFacilityChecks] = useState({})

  // advanced: manual multi-location structures (used when facilityMode='none')
  const [structures, setStructures] = useState([])

  const [result, setResult]   = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState('')
  const [forceBuy, setForceBuy] = useState(new Set())   // nodes the user chose to skip making

  // owned blueprints + per-node selection (product_type_id -> blueprint_id)
  const [ownedBPs, setOwnedBPs]   = useState([])
  const [useBlueprints, setUseBlueprints] = useState(false)
  const [bpSelection, setBpSelection] = useState({})

  useEffect(() => {
    get('/facilities').then(fs => {
      setFacilities(fs)
      const checks = {}
      fs.forEach(f => { checks[f.id] = { checked: false, man: 5, react: 5 } })
      setFacilityChecks(checks)
    }).catch(() => {})
    get('/blueprints').then(setOwnedBPs).catch(() => {})
  }, [])

  // auto-fill global params when single facility selected
  useEffect(() => {
    if (!singleFacilityId || facilityMode !== 'none') return
    const f = facilities.find(f => f.id === Number(singleFacilityId))
    if (!f) return
    setParams(p => ({
      ...p,
      system_cost_index: f.system_cost_index != null ? +(f.system_cost_index * 100).toFixed(4) : p.system_cost_index,
      facility_tax_pct:  f.tax != null ? f.tax : p.facility_tax_pct,
      structure_discount_pct: f.cost_bonus != null ? f.cost_bonus : p.structure_discount_pct,
    }))
  }, [singleFacilityId, facilities, facilityMode])

  // structures auto-built from facility checklist
  const multiStructures = facilityMode === 'multi'
    ? facilities
        .filter(f => facilityChecks[f.id]?.checked)
        .map(f => {
          const fc = facilityChecks[f.id] || {}
          return {
            place_id: f.id,
            name: f.name,
            system_cost_index: f.system_cost_index || 0,   // fraction from DB
            facility_tax_pct: f.tax || 0,
            structure_discount_pct: f.cost_bonus || 0,
            man_lines: Number(fc.man) || 0,
            react_lines: Number(fc.react) || 0,
          }
        })
    : []

  function toggleRegion(rid) {
    setSelectedRegions(prev => {
      const next = new Set(prev)
      if (next.has(rid)) { if (next.size > 1) next.delete(rid) }
      else next.add(rid)
      return next
    })
  }

  function toggleFacility(fid, checked) {
    setFacilityChecks(prev => ({ ...prev, [fid]: { ...(prev[fid] || { man: 5, react: 5 }), checked } }))
  }
  function setFacilitySlot(fid, key, val) {
    setFacilityChecks(prev => ({ ...prev, [fid]: { ...(prev[fid] || { checked: false, man: 5, react: 5 }), [key]: val } }))
  }
  function setAllFacilities(checked) {
    setFacilityChecks(prev => {
      const next = { ...prev }
      facilities.forEach(f => { next[f.id] = { ...(prev[f.id] || { man: 5, react: 5 }), checked } })
      return next
    })
  }
  // switching to "use my facilities" auto-includes them all (no 20 clicks)
  function pickFacilityMode(mode) {
    setFacilityMode(mode)
    if (mode === 'multi' && !Object.values(facilityChecks).some(c => c?.checked)) setAllFacilities(true)
  }

  // manual structures (advanced)
  const addStruct    = () => setStructures(s => [...s, { place_id: '', name: '', sci: '', tax: '', disc: '', man: 5, react: 5 }])
  const updateStruct = (i, k) => e => setStructures(s => s.map((st, j) => j === i ? { ...st, [k]: e.target.value } : st))
  const removeStruct = i => setStructures(s => s.filter((_, j) => j !== i))

  async function calculate(fbSet, opts = {}) {
    if (!product?.type_id) return
    const fb = fbSet instanceof Set ? fbSet : forceBuy
    const useBP = opts.useBP ?? useBlueprints
    const bpSel = opts.bpSel ?? bpSelection
    setLoading(true); setError('')
    try {
      const activeStructures = facilityMode === 'multi' ? multiStructures : structures
      const res = await post('/manufacturing/calculate-chain', {
        product_type_id: product.type_id,
        qty: Number(params.qty) || 1,
        region_ids: [...selectedRegions],
        region_id: [...selectedRegions][0] || 10000002,
        price_basis: params.price_basis,
        include_cj: includeCJ,
        use_owned_blueprints: useBP,
        blueprint_selection: bpSel,
        facility_id: singleFacilityId && facilityMode === 'none' ? Number(singleFacilityId) : null,
        me_pct: Number(params.me_pct),
        te_pct: Number(params.te_pct),
        system_cost_index: Number(params.system_cost_index) / 100,
        facility_tax_pct: Number(params.facility_tax_pct),
        structure_discount_pct: Number(params.structure_discount_pct),
        man_lines: Number(params.man_lines),
        react_lines: Number(params.react_lines),
        max_depth: Number(params.max_depth),
        force_buy: [...fb],
        ...(activeStructures.length ? {
          structures: facilityMode === 'multi'
            ? activeStructures   // already in API format (fractions)
            : activeStructures.map(s => ({
                place_id: Number(s.place_id) || 0,
                name: s.name || '',
                system_cost_index: Number(s.sci) / 100,
                facility_tax_pct: Number(s.tax),
                structure_discount_pct: Number(s.disc),
                man_lines: Number(s.man) || 0,
                react_lines: Number(s.react) || 0,
              })),
        } : {}),
      })
      setResult(res)

      // auto-fetch sell price for profit calculation
      setSellLoading(true)
      try {
        const prices = await fetchMarketPrices([product.type_id], sellMarket)
        const p = prices[product.type_id]
        setSellPrice(p?.[sellMethod] ?? null)
      } catch {}
      finally { setSellLoading(false) }
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  const setP = k => e => setParams(p => ({ ...p, [k]: e.target.value }))

  // Toggle skip-make on a node and immediately re-solve the chain with it forced-buy.
  function toggleSkip(tid) {
    const next = new Set(forceBuy)
    next.has(tid) ? next.delete(tid) : next.add(tid)
    setForceBuy(next)
    calculate(next)
  }

  // owned blueprints keyed by the product they make
  const bpByProduct = {}
  ownedBPs.forEach(b => { (bpByProduct[b.product_type_id] ||= []).push(b) })

  function toggleUseBlueprints(on) {
    setUseBlueprints(on)
    calculate(undefined, { useBP: on })
  }
  // Pick a specific blueprint for one node (or '' = auto) and re-solve.
  function selectBP(tid, bpId) {
    const next = { ...bpSelection }
    if (bpId) next[tid] = bpId; else delete next[tid]
    setBpSelection(next)
    if (!useBlueprints) setUseBlueprints(true)
    calculate(undefined, { useBP: true, bpSel: next })
  }

  const plan      = result?.plan
  const asg       = result?.assignment
  const boughtIdx = new Set((asg?.bought || []).map(a => a.job_index))
  const hasAssign = asg && (asg.status === 'optimal' || asg.status === 'feasible')
  const decisions = plan ? Object.values(plan.decisions) : []
  const makeCount = decisions.filter(d => d.decision === 'make').length
  const buyCount  = decisions.filter(d => d.decision === 'buy').length
  const shopping  = plan?.shopping_list || []
  const shopText  = shopping.map(s => `${s.name}\t${s.qty}`).join('\n')

  // where to buy each shopping item — winning region/source the backend reported
  const priceSource = result?.price_source || {}
  const buyAtLabel = tid => {
    const src = priceSource[tid] ?? priceSource[String(tid)]
    if (src == null) return '—'
    if (src === 'C-J6MT') return 'C-J6MT'
    if (src === 'override') return 'manual'
    const r = REGIONS.find(r => r.id === Number(src))
    return r ? r.name.replace(/\s*\(.*\)$/, '') : `region ${src}`
  }

  const totalCost = result?.final_cost ?? plan?.total_cost ?? null
  const totalSell = sellPrice != null && plan ? sellPrice * plan.target_qty : null
  const profit    = totalSell != null && totalCost != null ? totalSell - totalCost : null
  const margin    = profit != null && totalSell ? profit / totalSell * 100 : null

  // estimated wall-clock build time: the busiest (facility, slot) line drives it
  const buildSeconds = (asg?.usage || []).reduce(
    (mx, u) => Math.max(mx, (u.used_s || 0) / Math.max(u.lines || 1, 1)), 0)
  const buildHours = buildSeconds / 3600

  function downloadPDF() {
    if (!plan) return
    const html = _chainPdfHtml(product, plan, result, totalCost, sellPrice, totalSell, profit, margin, sellMarket, sellMethod, facilities, facilityMode, facilityChecks)
    const blob = new Blob([html], { type: 'text/html;charset=utf-8' })
    const url  = URL.createObjectURL(blob)
    const w    = window.open(url, '_blank', 'width=960,height=720')
    if (w) w.addEventListener('load', () => setTimeout(() => w.print(), 300), { once: true })
    setTimeout(() => URL.revokeObjectURL(url), 30000)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {error && <div className="error-box">{error}</div>}

      {/* ── Controls ── */}
      <div className="card">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px,1fr))', gap: 14 }}>
          <div style={{ gridColumn: '1 / -1' }}>
            <CLabel>Product to build (full chain)</CLabel>
            <TypeSearch value={product} onChange={t => { setProduct(t?.type_id ? t : null); setForceBuy(new Set()) }} placeholder="Search product…" />
            <span style={{ fontSize: 11, color: 'var(--text)' }}>
              Whole build tree priced; each node decided make-vs-buy recursively.
            </span>
          </div>
          <NumField label="Quantity" value={params.qty} onChange={setP('qty')} min={1} />

          {/* ── (1) Buy-price regions ── */}
          <div style={{ gridColumn: '1 / -1' }}>
            <CLabel>Buy-price regions <Hint>min price across all selected</Hint></CLabel>
            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginTop: 5 }}>
              {REGIONS.map(r => (
                <label key={r.id} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 12, cursor: 'pointer',
                  color: selectedRegions.has(r.id) ? 'var(--text-white)' : 'var(--text)' }}>
                  <input type="checkbox" checked={selectedRegions.has(r.id)} onChange={() => toggleRegion(r.id)} />
                  {r.name}
                </label>
              ))}
              <label style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 12, cursor: 'pointer',
                color: includeCJ ? '#c8a951' : 'var(--text)' }}>
                <input type="checkbox" checked={includeCJ} onChange={e => setIncludeCJ(e.target.checked)} />
                C-J6MT <span style={{ fontSize: 10, color: 'var(--border2)' }}>(slow)</span>
              </label>
            </div>
          </div>

          <div>
            <CLabel>Price basis</CLabel>
            <select value={params.price_basis} onChange={setP('price_basis')}>
              <option value="buy">Buy orders (place buy)</option>
              <option value="sell">Sell orders (instant)</option>
            </select>
          </div>

          {/* ── (2) Sell at for profit ── */}
          <div>
            <CLabel>Sell at <Hint>profit calc</Hint></CLabel>
            <div style={{ display: 'flex', gap: 5, alignItems: 'center', marginTop: 5, flexWrap: 'wrap' }}>
              <select value={sellMarket} onChange={e => setSellMarket(e.target.value)} style={{ width: 64, padding: '2px 4px', fontSize: 11 }}>
                {MARKETS.map(m => <option key={m} value={m}>{m}</option>)}
              </select>
              {METHODS.map(m => (
                <button key={m} type="button" onClick={() => setSellMethod(m)}
                  className={`btn btn-sm ${sellMethod === m ? 'btn-primary' : 'btn-ghost'}`}
                  style={{ padding: '2px 8px', fontSize: 11 }}>{m}</button>
              ))}
            </div>
          </div>

          <NumField label="ME % (manuf.)" value={params.me_pct} onChange={setP('me_pct')} step={0.1} />
          <NumField label="TE %" value={params.te_pct} onChange={setP('te_pct')} step={0.1} />
          <NumField label="Max depth" value={params.max_depth} onChange={setP('max_depth')} min={1} max={20} />
          <div>
            <CLabel>Blueprints <Hint>use ME/TE you own</Hint></CLabel>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, cursor: 'pointer', marginTop: 5,
              color: ownedBPs.length ? 'var(--text-white)' : 'var(--text)' }}>
              <input type="checkbox" checked={useBlueprints} disabled={!ownedBPs.length}
                onChange={e => toggleUseBlueprints(e.target.checked)} />
              Use my blueprints ({ownedBPs.length})
            </label>
          </div>
        </div>
      </div>

      {/* ── (3) Facility mode ── */}
      <div className="card" style={{ padding: 0 }}>
        <div style={{ padding: '10px 16px', background: 'var(--surface2)', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 18, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 13, color: 'var(--text-white)', fontWeight: 500 }}>Facilities</span>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, cursor: 'pointer' }}>
            <input type="radio" name="facilityMode" value="none" checked={facilityMode === 'none'} onChange={() => pickFacilityMode('none')} />
            Default / no buffs
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, cursor: 'pointer' }}>
            <input type="radio" name="facilityMode" value="multi" checked={facilityMode === 'multi'} onChange={() => pickFacilityMode('multi')} />
            Use my facilities <Hint>all selected — each job built at its cheapest</Hint>
          </label>
        </div>

        {/* ── no-buffs mode: single facility + manual params ── */}
        {facilityMode === 'none' && (
          <div style={{ padding: '12px 16px', display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px,1fr))', gap: 12 }}>
            <div>
              <CLabel>Facility</CLabel>
              <select value={singleFacilityId} onChange={e => setSingleFacilityId(e.target.value)}>
                <option value="">— none —</option>
                {facilities.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}
              </select>
            </div>
            <NumField label="System Cost Index %" value={params.system_cost_index} onChange={setP('system_cost_index')} step={0.001} />
            <NumField label="Facility Tax %" value={params.facility_tax_pct} onChange={setP('facility_tax_pct')} step={0.1} />
            <NumField label="Structure Discount %" value={params.structure_discount_pct} onChange={setP('structure_discount_pct')} step={0.1} />
            <NumField label="Manufacturing slots" value={params.man_lines} onChange={setP('man_lines')} min={0} />
            <NumField label="Reaction slots" value={params.react_lines} onChange={setP('react_lines')} min={0} />
          </div>
        )}

        {/* ── multi-facility checklist ── */}
        {facilityMode === 'multi' && (
          <div>
            {facilities.length > 0 && (
              <div style={{ padding: '8px 16px', display: 'flex', gap: 8, alignItems: 'center', borderBottom: '1px solid var(--border)' }}>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAllFacilities(true)}>Select all</button>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAllFacilities(false)}>None</button>
                <span style={{ fontSize: 11, color: 'var(--text)' }}>each job is built at whichever selected facility is cheapest</span>
              </div>
            )}
            {facilities.length === 0
              ? <div style={{ padding: 16, color: 'var(--text)', fontSize: 12 }}>No facilities saved yet.</div>
              : (
                <table>
                  <thead>
                    <tr><th></th><th>Facility</th><th>SCI %</th><th>Tax %</th><th>Disc %</th><th>Manuf. slots</th><th>React. slots</th></tr>
                  </thead>
                  <tbody>
                    {facilities.map(f => {
                      const fc = facilityChecks[f.id] || { checked: false, man: 5, react: 5 }
                      return (
                        <tr key={f.id} style={{ opacity: fc.checked ? 1 : 0.5 }}>
                          <td>
                            <input type="checkbox" checked={!!fc.checked} onChange={e => toggleFacility(f.id, e.target.checked)} />
                          </td>
                          <td style={{ color: fc.checked ? 'var(--text-white)' : 'var(--text)', whiteSpace: 'nowrap' }}>{f.name}</td>
                          <td style={{ fontSize: 12, color: 'var(--text)' }}>
                            {f.system_cost_index != null ? (f.system_cost_index * 100).toFixed(3) : '—'}
                          </td>
                          <td style={{ fontSize: 12, color: 'var(--text)' }}>{f.tax != null ? f.tax : '—'}</td>
                          <td style={{ fontSize: 12, color: 'var(--text)' }}>{f.cost_bonus != null ? f.cost_bonus : '—'}</td>
                          <td>
                            <input type="number" style={{ width: 60 }} value={fc.man} disabled={!fc.checked}
                              onChange={e => setFacilitySlot(f.id, 'man', e.target.value)} />
                          </td>
                          <td>
                            <input type="number" style={{ width: 60 }} value={fc.react} disabled={!fc.checked}
                              onChange={e => setFacilitySlot(f.id, 'react', e.target.value)} />
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              )
            }
            <div style={{ padding: '8px 16px', fontSize: 11, color: 'var(--text)', borderTop: facilities.length ? '1px solid var(--border)' : 'none' }}>
              {multiStructures.length
                ? `${multiStructures.length} structure${multiStructures.length !== 1 ? 's' : ''} selected — each job is built at whichever is cheapest`
                : 'Select at least one facility above'}
            </div>
          </div>
        )}
      </div>

      {/* ── Advanced: manual structures (no-buffs mode only) ── */}
      {facilityMode === 'none' && (
        <div className="card" style={{ padding: 0 }}>
          <div style={{ padding: '10px 16px', borderBottom: structures.length ? '1px solid var(--border)' : 'none', display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 12, color: 'var(--text)', fontWeight: 500 }}>Advanced: multi-location structures</span>
            <Hint>add 2+ → each job is built at whichever structure is cheapest</Hint>
            <button className="btn btn-ghost btn-sm" style={{ marginLeft: 'auto' }} onClick={addStruct}>+ Add</button>
          </div>
          {structures.length > 0 && (
            <table>
              <thead><tr><th>Place ID</th><th>Name</th><th>SCI %</th><th>Tax %</th><th>Disc %</th><th>Manuf</th><th>React</th><th></th></tr></thead>
              <tbody>
                {structures.map((s, i) => (
                  <tr key={i}>
                    <td><input style={{ width: 90 }} value={s.place_id} onChange={updateStruct(i, 'place_id')} placeholder="id" /></td>
                    <td><input style={{ width: 120 }} value={s.name} onChange={updateStruct(i, 'name')} placeholder="Sotiyo" /></td>
                    <td><input type="number" style={{ width: 70 }} step="0.001" value={s.sci} onChange={updateStruct(i, 'sci')} /></td>
                    <td><input type="number" style={{ width: 60 }} step="0.1" value={s.tax} onChange={updateStruct(i, 'tax')} /></td>
                    <td><input type="number" style={{ width: 60 }} step="0.1" value={s.disc} onChange={updateStruct(i, 'disc')} /></td>
                    <td><input type="number" style={{ width: 60 }} value={s.man} onChange={updateStruct(i, 'man')} /></td>
                    <td><input type="number" style={{ width: 60 }} value={s.react} onChange={updateStruct(i, 'react')} /></td>
                    <td><button className="btn btn-danger btn-sm" onClick={() => removeStruct(i)}>✕</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <button className="btn btn-primary" onClick={calculate} disabled={!product?.type_id || loading}>
          {loading ? 'Solving chain…' : '⚙ Calculate chain'}
        </button>
        {result && plan && (
          <button className="btn btn-ghost" onClick={downloadPDF}>📄 Download PDF</button>
        )}
        <span style={{ fontSize: 11, color: 'var(--text)' }}>
          {includeCJ ? 'C-J prices take ~5–15 s extra.' : ''}
          {facilityMode === 'multi' && multiStructures.length > 1
            ? `Multi-location: each job built at the cheapest of ${multiStructures.length} facilities.` : ''}
        </span>
      </div>

      {result && plan && (
        <>
          {/* ── Summary ── */}
          <Section title="Chain summary">
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(160px,1fr))', gap: 14, padding: 12 }}>
              <IskStat label="Unit cost" value={plan.unit_cost} color="var(--accent)" bold />
              <IskStat label="Total production cost" value={totalCost} bold />
              {sellLoading
                ? <div style={{ fontSize: 12, color: 'var(--text)' }}>Fetching sell price…</div>
                : sellPrice != null
                  ? <>
                      <IskStat label={`Sell (${sellMarket} ${sellMethod})`} value={totalSell} color="#4caf7d" bold />
                      <IskStat label="Profit" value={profit} color={profit >= 0 ? '#4caf7d' : '#e05252'} bold />
                      <div>
                        <div style={statLabel}>Margin</div>
                        <div style={{ fontWeight: 700, fontSize: 18, color: margin >= 0 ? '#4caf7d' : '#e05252',
                          background: margin >= 0 ? '#0e2a1a' : '#2a0e0e', padding: '3px 8px', borderRadius: 4, display: 'inline-block' }}>
                          {margin?.toFixed(1)}%
                        </div>
                      </div>
                    </>
                  : null}
              <div>
                <div style={statLabel}>Engine</div>
                <span style={{
                  fontSize: 12, fontWeight: 700, padding: '2px 8px', borderRadius: 4,
                  background: result.engine === 'haskell' ? '#0e2a1a' : 'var(--surface3)',
                  color: result.engine === 'haskell' ? '#4caf7d' : 'var(--text)',
                }}>{result.engine === 'haskell' ? '⬢ Haskell' : '🐍 Python'}</span>
              </div>
              <div>
                <div style={statLabel}>Decisions</div>
                <div style={{ color: 'var(--text-white)' }}>
                  <span style={{ color: '#4caf7d' }}>{makeCount} make</span> · <span>{buyCount} buy</span>
                </div>
              </div>
            </div>
            {asg && hasAssign && (
              <div style={{ padding: '0 12px 12px', fontSize: 12, color: 'var(--text)' }}>
                Built in-house: <b style={{ color: 'var(--accent)' }}>{asg.in_house?.length || 0}</b> job{(asg.in_house?.length || 0) !== 1 ? 's' : ''}
                {' · '}saved vs buying <span style={{ color: '#4caf7d' }}>{fmtIsk(asg.savings_captured)}</span>
              </div>
            )}
          </Section>

          {/* ── Build graph + skip controls ── */}
          <Section title="Build graph">
            <div style={{ padding: '8px 12px', fontSize: 11, color: 'var(--text)', display: 'flex', gap: 14, flexWrap: 'wrap', alignItems: 'center' }}>
              <LegendDot color="#4caf7d" label="make" />
              <LegendDot color="#3a9bd6" label="buy (has recipe)" />
              <LegendDot color="#5a6178" label="raw / leaf" />
              <LegendDot color="#e0884f" label="skipped" />
              <span>Click a node to skip making it — the chain re-solves.</span>
            </div>
            {forceBuy.size > 0 && (
              <div style={{ padding: '0 12px 8px', display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                <span style={{ fontSize: 11, color: 'var(--text)' }}>Skipped:</span>
                {[...forceBuy].map(tid => (
                  <button key={tid} type="button" onClick={() => toggleSkip(tid)} className="btn btn-sm"
                    style={{ background: '#2a1d10', color: '#e0884f', border: '1px solid #5a3d1a', fontSize: 11, padding: '2px 8px' }}>
                    {plan.decisions[tid]?.name || tid} ✕
                  </button>
                ))}
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setForceBuy(new Set()); calculate(new Set()) }}>Reset all</button>
              </div>
            )}
            <Suspense fallback={<div style={{ padding: 16, fontSize: 12, color: 'var(--text)' }}>Loading graph…</div>}>
              <ChainGraph plan={plan} forceBuy={forceBuy} onSkip={toggleSkip} />
            </Suspense>
          </Section>

          {/* ── Analytics: ROI / profit-per-hour / cost pie ── */}
          <Section title="Analytics">
            <ChainMetrics plan={plan} totalCost={totalCost} profit={profit} buildHours={buildHours} />
            <div style={{ borderTop: '1px solid var(--border)' }}>
              <ChainCostPie plan={plan} />
            </div>
          </Section>

          {/* ── Make vs Buy ── */}
          <Section title={`Make vs Buy — ${decisions.length} nodes`}>
            <table>
              <thead><tr><th>Item</th><th>Decision</th><th>Make /u</th><th>Buy /u</th><th>Chosen /u</th><th>Saved /u</th><th>Build?</th></tr></thead>
              <tbody>
                {[...decisions].sort((a, b) => (b.saved_per_unit || 0) - (a.saved_per_unit || 0)).map(d => {
                  const skipped = forceBuy.has(d.type_id)
                  const makeable = d.unit_make != null || skipped   // has a recipe we could run
                  return (
                  <tr key={d.type_id}>
                    <td style={{ color: 'var(--text-white)', whiteSpace: 'nowrap' }}>{d.name}</td>
                    <td><DecisionBadge decision={d.decision} /></td>
                    <td>{d.unit_make != null ? fmtIsk(d.unit_make) : '—'}</td>
                    <td>{d.unit_buy != null ? fmtIsk(d.unit_buy) : '—'}</td>
                    <td style={{ color: 'var(--accent)' }}>{d.unit_cost != null ? fmtIsk(d.unit_cost) : '—'}</td>
                    <td style={{ color: d.saved_per_unit > 0 ? '#4caf7d' : 'var(--text)' }}>
                      {d.saved_per_unit > 0 ? fmtIsk(d.saved_per_unit) : '—'}
                    </td>
                    <td>
                      {makeable
                        ? <input type="checkbox" checked={!skipped} title="uncheck to skip making this (force buy)"
                            onChange={() => toggleSkip(d.type_id)} />
                        : <span style={{ color: 'var(--border2)', fontSize: 11 }}>—</span>}
                    </td>
                  </tr>
                  )
                })}
              </tbody>
            </table>
          </Section>

          {/* ── Blueprints (per-node ME/TE + needed report) ── */}
          {ownedBPs.length > 0 && (() => {
            const bpRep = {}
            ;(result.bp_report || []).forEach(r => { bpRep[r.type_id] = r })
            const nodes = decisions.filter(d => d.decision === 'make' && bpByProduct[d.type_id]?.length)
            if (!nodes.length) return null
            return (
              <Section title="Blueprints needed">
                {!useBlueprints && (
                  <div style={{ padding: '8px 12px', fontSize: 12, color: 'var(--text)' }}>
                    Enable <b>Use my blueprints</b> above to apply owned ME/TE, or pick one per item below.
                  </div>
                )}
                <table>
                  <thead><tr><th>Item</th><th>Blueprint</th><th>ME/TE</th><th>Runs needed</th><th>Owned</th><th>Shortfall</th></tr></thead>
                  <tbody>
                    {nodes.map(d => {
                      const cands = bpByProduct[d.type_id] || []
                      const rep = bpRep[d.type_id]
                      return (
                        <tr key={d.type_id}>
                          <td style={{ color: 'var(--text-white)', whiteSpace: 'nowrap' }}>{d.name}</td>
                          <td>
                            <select value={bpSelection[d.type_id] || ''} onChange={e => selectBP(d.type_id, Number(e.target.value) || null)}>
                              <option value="">Auto</option>
                              {cands.map(b => (
                                <option key={b.id} value={b.id}>
                                  {b.is_bpo ? 'BPO' : 'BPC'} ME{b.me} TE{b.te}{b.is_bpo ? '' : ` ×${b.runs ?? '?'}r`}
                                </option>
                              ))}
                            </select>
                          </td>
                          <td style={{ fontSize: 12, color: 'var(--text)' }}>{rep ? `${rep.me} / ${rep.te}` : '—'}</td>
                          <td>{rep ? rep.runs_needed.toLocaleString() : '—'}</td>
                          <td>{rep ? (rep.runs_owned == null ? '∞' : rep.runs_owned.toLocaleString()) : '—'}</td>
                          <td style={{ color: rep && rep.shortfall > 0 ? '#e05252' : 'var(--text)' }}>
                            {rep ? (rep.shortfall > 0 ? `⚠ ${rep.shortfall}` : 'ok') : '—'}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </Section>
            )
          })()}

          {/* ── Production plan ── */}
          {plan.jobs.length > 0 && (() => {
            // Every job already carries its concrete factory (the core assigned the
            // cheapest). 'facility' is the placeholder used when no facility is set.
            const jobFactory = (j) => (j.place_name && j.place_name !== 'facility') ? j.place_name : null

            return (
              <>
                {(() => {
                  // Merge max_production_limit split batches: same type_id + same factory → one row
                  const merged = []
                  const seen = {} // key → merged index
                  plan.jobs.forEach((j, i) => {
                    const bounced = hasAssign && boughtIdx.has(i)
                    const fl = jobFactory(j)
                    const key = `${j.type_id}|${fl || j.activity}|${bounced ? 'b' : 'i'}`
                    if (seen[key] !== undefined) {
                      const m = merged[seen[key]]
                      m.runs += j.runs
                      m.qty_out += j.qty_out
                      m.time_s = Math.max(m.time_s, j.time_s) // longest batch determines the run
                      m.batches++
                    } else {
                      seen[key] = merged.length
                      merged.push({ ...j, i, bounced, fl, batches: 1 })
                    }
                  })
                  return (
                    <Section title={`Production plan — ${merged.length} job${merged.length !== 1 ? 's' : ''}`}>
                      <table>
                        <thead>
                          <tr>
                            <th>Item</th><th>Runs</th><th>Qty to produce</th><th>Time</th>
                            <th>Factory</th><th>Slot</th>
                          </tr>
                        </thead>
                        <tbody>
                          {merged.map((j, idx) => {
                            const typeTag = j.activity === 11 ? 'R' : 'M'
                            return (
                              <tr key={idx} style={{ opacity: j.bounced ? 0.55 : 1 }}>
                                <td style={{ color: 'var(--text-white)', whiteSpace: 'nowrap' }}>
                                  {j.name}
                                  {j.batches > 1 && (
                                    <span style={{ fontSize: 10, color: 'var(--border2)', marginLeft: 6 }}>×{j.batches} batches</span>
                                  )}
                                </td>
                                <td>{j.runs.toLocaleString()}</td>
                                <td style={{ color: j.bounced ? 'var(--text)' : 'var(--accent)', fontWeight: j.bounced ? 400 : 600 }}>
                                  {j.qty_out.toLocaleString()}
                                </td>
                                <td style={{ fontSize: 12, color: 'var(--text)' }}>{fmtTime(j.time_s)}</td>
                                <td style={{ whiteSpace: 'nowrap' }}>
                                  {j.bounced
                                    ? <span style={{ color: '#e0884f', fontSize: 12 }}>↩ buy instead</span>
                                    : j.fl
                                      ? <><span style={{ color: 'var(--text-white)', fontSize: 12 }}>{j.fl}</span>
                                          <span style={{ fontSize: 10, color: 'var(--text)', marginLeft: 5,
                                            background: 'var(--surface3)', padding: '1px 4px', borderRadius: 3 }}>{typeTag}</span>
                                        </>
                                      : <span style={{ fontSize: 12, color: 'var(--text)' }}>{j.activity === 11 ? 'Reaction' : 'Manufacturing'}</span>}
                                </td>
                                <td>
                                  {hasAssign
                                    ? (j.bounced
                                      ? <span style={{ color: '#e0884f', fontSize: 11 }}>↩ bought</span>
                                      : <span style={{ color: '#4caf7d', fontSize: 11 }}>● in-house</span>)
                                    : <span style={{ fontSize: 11, color: 'var(--text)' }}>{j.slot_kind}</span>}
                                </td>
                              </tr>
                            )
                          })}
                        </tbody>
                      </table>
                    </Section>
                  )
                })()}

                {/* ── Shopping list ── */}
                {shopping.length > 0 && (
                  <Section title={`Shopping list — ${shopping.length} items`}>
                    <table>
                      <thead>
                        <tr>
                          <th>Item</th><th>Qty</th><th>Unit</th><th>Total</th><th>Buy at</th>
                        </tr>
                      </thead>
                      <tbody>
                        {shopping.map(s => (
                          <tr key={s.type_id}>
                            <td style={{ color: 'var(--text-white)', whiteSpace: 'nowrap' }}>{s.name}</td>
                            <td>{s.qty.toLocaleString()}</td>
                            <td>{fmtIsk(s.unit)}</td>
                            <td style={{ color: 'var(--accent)' }}>{fmtIsk(s.total)}</td>
                            <td style={{ fontSize: 11, color: 'var(--text)', whiteSpace: 'nowrap' }}>
                              {buyAtLabel(s.type_id)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
              <div style={{ padding: '12px 16px', borderTop: '1px solid var(--border)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
                  <span style={{ fontSize: 12, color: 'var(--accent)', fontWeight: 600 }}>🛒 Multibuy (paste into EVE)</span>
                  <button className="btn btn-ghost btn-sm" onClick={() => navigator.clipboard.writeText(shopText)}>Copy</button>
                </div>
                <textarea readOnly value={shopText} rows={Math.min(shopping.length, 10)}
                  style={{ fontFamily: 'monospace', fontSize: 12, width: '100%' }} />
              </div>
                </Section>
              )}
            </>
          )
        })()}
      </>
    )}
    </div>
  )
}

/* Generate printable HTML for the chain plan PDF */
function _chainPdfHtml(product, plan, result, totalCost, sellPrice, totalSell, profit, margin, sellMarket, sellMethod, facilities, facilityMode, facilityChecks) {
  const decisions = Object.values(plan.decisions)
  const shopping  = plan.shopping_list || []
  const jobs      = plan.jobs || []

  const isk = v => {
    if (v == null) return '—'
    const n = Number(v); if (isNaN(n)) return '—'
    if (Math.abs(n) >= 1e9) return (n / 1e9).toFixed(2) + ' B ISK'
    if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(2) + ' M ISK'
    return n.toLocaleString(undefined, { maximumFractionDigits: 0 }) + ' ISK'
  }
  const fmtT = s => {
    if (!s) return '—'
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60)
    return h ? `${h}h ${m}m` : `${m}m`
  }

  // group jobs by facility (exclude bounced-to-buy)
  const byFacility = {}
  jobs.forEach(j => {
    const key = j.place_name || (j.place_id ? `#${j.place_id}` : 'Unassigned')
    ;(byFacility[key] = byFacility[key] || []).push(j)
  })

  // deliver-to map for shopping list
  const shopTo = {}
  jobs.forEach(j => {
    const factory = j.place_name || (j.place_id ? `#${j.place_id}` : null)
    if (!factory) return
    ;(j.inputs || []).forEach(inp => {
      if (!inp.is_make) {
        if (!shopTo[inp.type_id]) shopTo[inp.type_id] = new Set()
        shopTo[inp.type_id].add(factory)
      }
    })
  })
  const multiFactory = new Set(jobs.map(j => j.place_name || j.place_id)).size > 1

  const profitColor = profit >= 0 ? '#1a7a3c' : '#9b1c1c'

  return `<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Chain Plan — ${product?.name || ''}</title>
<style>
  body{font-family:Arial,sans-serif;font-size:12px;color:#222;margin:20px;max-width:960px}
  h1{font-size:20px;margin-bottom:2px}
  h2{font-size:14px;margin:18px 0 6px;border-bottom:2px solid #ccc;padding-bottom:3px;color:#333}
  h3{font-size:12px;margin:12px 0 4px;color:#555;background:#f9f9f9;padding:4px 8px;border-left:3px solid #c8a951}
  table{width:100%;border-collapse:collapse;margin-bottom:10px}
  th{background:#f4f4f4;text-align:left;padding:5px 8px;font-size:11px;border-bottom:2px solid #ddd}
  td{padding:4px 8px;border-bottom:1px solid #eee}
  .tag{display:inline-block;font-size:9px;padding:1px 4px;border-radius:2px;background:#e8e8e8;color:#555;margin-left:4px}
  .summary{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:12px 0}
  .stat{padding:10px;border:1px solid #ddd;border-radius:5px}
  .stat-label{font-size:10px;color:#666;margin-bottom:2px}
  .stat-value{font-weight:700;font-size:15px}
  .make{color:#1a7a3c}.buy{color:#1a5c9b}.na{color:#9b1c1c}
  @media print{@page{margin:12mm}}
</style>
</head>
<body>
<h1>Chain Production Plan</h1>
<p style="color:#666;margin:0 0 12px">${product?.name || ''} &times; ${plan.target_qty.toLocaleString()} units &mdash; ${new Date().toLocaleDateString()}</p>

<div class="summary">
  <div class="stat"><div class="stat-label">Unit cost</div><div class="stat-value">${isk(plan.unit_cost)}</div></div>
  <div class="stat"><div class="stat-label">Total production cost</div><div class="stat-value">${isk(totalCost)}</div></div>
  ${sellPrice != null ? `
  <div class="stat"><div class="stat-label">Sell (${sellMarket} ${sellMethod})</div><div class="stat-value" style="color:#1a7a3c">${isk(totalSell)}</div></div>
  <div class="stat"><div class="stat-label">Profit &bull; Margin</div><div class="stat-value" style="color:${profitColor}">${isk(profit)} &bull; ${margin?.toFixed(1)}%</div></div>
  ` : '<div class="stat"><div class="stat-label">Sell price</div><div class="stat-value">—</div></div><div></div>'}
</div>

<h2>Production Plan — What &amp; Where to Make</h2>
${Object.entries(byFacility).map(([place, pjobs]) => `
<h3>@ ${place}</h3>
<table>
<thead><tr><th>Item</th><th>Runs</th><th>Qty to produce</th><th>Time</th></tr></thead>
<tbody>
${pjobs.map(j => `<tr>
  <td>${j.name}<span class="tag">${j.activity === 11 ? 'R' : 'M'}</span></td>
  <td>${j.runs.toLocaleString()}</td>
  <td><b>${j.qty_out.toLocaleString()}</b></td>
  <td>${fmtT(j.time_s)}</td>
</tr>`).join('')}
</tbody>
</table>`).join('')}

${shopping.length ? `
<h2>Shopping List — Items to Buy</h2>
<table>
<thead><tr><th>Item</th><th>Qty</th><th>Unit price</th><th>Total</th>${multiFactory ? '<th>Deliver to</th>' : ''}</tr></thead>
<tbody>
${shopping.map(s => `<tr>
  <td>${s.name}</td>
  <td>${s.qty.toLocaleString()}</td>
  <td>${isk(s.unit)}</td>
  <td><b>${isk(s.total)}</b></td>
  ${multiFactory ? `<td style="font-size:11px;color:#555">${[...(shopTo[s.type_id] || [])].join(', ') || '—'}</td>` : ''}
</tr>`).join('')}
</tbody>
</table>` : ''}

<h2>Make vs Buy Decisions</h2>
<table>
<thead><tr><th>Item</th><th>Decision</th><th>Make /u</th><th>Buy /u</th><th>Chosen /u</th><th>Saved /u</th></tr></thead>
<tbody>
${[...decisions].sort((a, b) => (b.saved_per_unit || 0) - (a.saved_per_unit || 0)).map(d => `<tr>
  <td>${d.name}</td>
  <td class="${d.decision}">${d.decision.toUpperCase()}</td>
  <td>${d.unit_make != null ? isk(d.unit_make) : '—'}</td>
  <td>${d.unit_buy  != null ? isk(d.unit_buy)  : '—'}</td>
  <td><b>${d.unit_cost != null ? isk(d.unit_cost) : '—'}</b></td>
  <td style="color:${(d.saved_per_unit || 0) > 0 ? '#1a7a3c' : '#999'}">${(d.saved_per_unit || 0) > 0 ? isk(d.saved_per_unit) : '—'}</td>
</tr>`).join('')}
</tbody>
</table>
</body></html>`
}

function DecisionBadge({ decision }) {
  const map = {
    make: { c: '#4caf7d', bg: '#0e2a1a', t: 'MAKE' },
    buy:  { c: '#3a9bd6', bg: '#0e1f2a', t: 'BUY' },
    unobtainable: { c: '#e05252', bg: '#2a0e0e', t: 'N/A' },
  }
  const s = map[decision] || map.unobtainable
  return <span style={{ fontSize: 11, fontWeight: 700, color: s.c, background: s.bg, padding: '2px 7px', borderRadius: 4 }}>{s.t}</span>
}

/* ═══════════════════════════ PAK JOBS TABLE ═══════════════════════════ */

function PakJobsTab() {
  const [jobs, setJobs]         = useState([])
  const [projects, setProjects] = useState([])
  const [filter, setFilter]     = useState({ project_id: '', status: '' })
  const [expand, setExpand]     = useState(null)
  const [selected, setSelected] = useState({})   // { jobId: true }
  const [combineOpen, setCombineOpen] = useState(false)

  const selectedJobs = jobs.filter(j => selected[j.id])
  const toggleSel = id => setSelected(s => ({ ...s, [id]: !s[id] }))

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
        {selectedJobs.length > 0 && (
          <button className="btn btn-primary btn-sm" onClick={() => setCombineOpen(v => !v)} style={{ marginLeft: 'auto' }}>
            🛒 Combined buy list ({selectedJobs.length})
          </button>
        )}
      </div>

      {combineOpen && selectedJobs.length > 0 && (
        <CombinedBuyPanel jobs={selectedJobs} projects={projects} onClose={() => setCombineOpen(false)} />
      )}

      {jobs.length === 0
        ? <div className="empty-state">No production jobs yet — use Calculator tab to create one</div>
        : (
          <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th></th>
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
                      <td onClick={e => e.stopPropagation()}>
                        <input type="checkbox" checked={!!selected[j.id]} onChange={() => toggleSel(j.id)} />
                      </td>
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
                        <td colSpan={13} style={{ background: 'var(--surface2)', padding: 0 }}>
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
  const [receiving, setReceiving] = useState(false)
  const [receiveMsg, setReceiveMsg] = useState('')
  const [receivePrice, setReceivePrice] = useState('')

  const outMoves = movements.filter(m => m.direction === 'out')
  const inMoves  = movements.filter(m => m.direction === 'in')
  const actualUnit = s?.actual?.unit_cost ?? null

  async function loadMovements() {
    try { setMovements(await get(`/manufacturing/jobs/${job.id}/movements`)) } catch {}
  }

  useEffect(() => { loadMovements() }, [job.id])

  async function issue(force = false) {
    const already = outMoves.length > 0
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
        `✓ Consumed ${res.materials.filter(m => m.consumed > 0).length} materials · ${fmtIsk(res.total_cost)} · unit cost ${fmtIsk(res.actual_unit_cost)}` +
        (shorts.length ? ` · ⚠ ${shorts.length} short: ${shorts.map(x => x.name + ' (-' + x.shortfall + ')').join(', ')}` : '')
      )
      await loadMovements()
      onChange?.()
    } catch (e) { setIssueMsg('⚠ ' + e.message) }
    finally { setIssuing(false) }
  }

  async function receive(force = false) {
    if (inMoves.length > 0 && !force) {
      if (!confirm('Output already received. Receive again (add more to stock)?')) return
      force = true
    }
    setReceiving(true); setReceiveMsg('')
    try {
      const body = receivePrice !== '' ? { unit_price: Number(receivePrice) } : {}
      const res = await post(`/manufacturing/jobs/${job.id}/receive${force ? '?force=true' : ''}`, body)
      setReceiveMsg(`✓ Added ${res.received_qty.toLocaleString()} ${job.product_name} to output @ ${fmtIsk(res.unit_cost)}/u`)
      await loadMovements()
      onChange?.()
    } catch (e) { setReceiveMsg('⚠ ' + e.message) }
    finally { setReceiving(false) }
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
        <Row label="Production" value={`${job.windows || 1} × ${job.runs} runs`} />
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
        <Row label="Unit cost (plan)" value={s.output ? fmtIsk(r.total_costs / s.output.quantity) : '—'} />
        {actualUnit != null && <Row label="Unit cost (actual)" value={fmtIsk(actualUnit)} accent />}
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
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 10 }}>
          <button className="btn btn-primary btn-sm" onClick={() => issue(false)} disabled={issuing}>
            {issuing ? 'Issuing…' : outMoves.length ? '📦 Issue again' : '📦 Issue materials'}
          </button>
          <span style={{ fontSize: 11, color: 'var(--text)' }}>
            Deduct the batch's materials from {job.project_id ? 'project' : 'unassigned'} stock (FIFO)
          </span>
          {issueMsg && <span style={{ fontSize: 12, color: issueMsg.startsWith('⚠') ? '#e05252' : '#4caf7d' }}>{issueMsg}</span>}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 10 }}>
          <button className="btn btn-ghost btn-sm" onClick={() => receive(false)} disabled={receiving}
            style={{ borderColor: '#4caf7d', color: '#4caf7d' }}>
            {receiving ? 'Receiving…' : inMoves.length ? '✅ Received again' : '✅ Received'}
          </button>
          <label style={{ fontSize: 11, color: 'var(--text)', display: 'flex', alignItems: 'center', gap: 6 }}>
            unit cost
            <input type="number" value={receivePrice} onChange={e => setReceivePrice(e.target.value)}
              placeholder={actualUnit != null ? String(actualUnit) : 'auto'} style={{ width: 110 }} />
          </label>
          <span style={{ fontSize: 11, color: 'var(--text)' }}>→ adds output to stock at production cost</span>
          {receiveMsg && <span style={{ fontSize: 12, color: receiveMsg.startsWith('⚠') ? '#e05252' : '#4caf7d' }}>{receiveMsg}</span>}
        </div>

        {movements.length > 0 && (
          <table style={{ marginTop: 6 }}>
            <thead>
              <tr><th>Date</th><th>Item</th><th>Qty</th><th>Unit Cost</th><th>Total</th><th>Reason</th></tr>
            </thead>
            <tbody>
              {movements.map(mv => (
                <tr key={mv.id}>
                  <td style={{ color: 'var(--text)', fontSize: 11 }}>{mv.created_at ? new Date(mv.created_at).toLocaleString() : '—'}</td>
                  <td style={{ color: 'var(--text-white)' }}>{mv.name}</td>
                  <td style={{ color: mv.direction === 'in' ? '#4caf7d' : '#e05252' }}>
                    {mv.direction === 'in' ? '+' : '-'}{mv.quantity.toLocaleString()}
                  </td>
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

const PIE_COLORS = ['#c8a951', '#3a9bd6', '#4caf7d', '#9b6dd6', '#e0884f', '#5fb0b0', '#d65f8a', '#8a9b3a', '#b0703a', '#6d8ad6', '#c05a5a', '#4a9b6d']

/* Build the 4-source comparison view from raw rows.
   rows: [{type_id,name,qty,volume,jita_buy,jita_sell,cj_buy,cj_sell}] */
function buildMarketView(rows, deliveryOn, deliveryCoef) {
  if (!rows) return null
  const dpu = vol => (deliveryOn ? (vol || 0) * Number(deliveryCoef || 0) : 0)
  const opts = ['jita_buy', 'jita_sell', 'cj_buy', 'cj_sell']
  const totals = { jita_buy: 0, jita_sell: 0, cj_buy: 0, cj_sell: 0, best: 0, delivery: 0 }
  const out = rows.map(r => {
    const eff = {
      jita_buy:  r.jita_buy  != null ? r.jita_buy  + dpu(r.volume) : null,
      jita_sell: r.jita_sell != null ? r.jita_sell + dpu(r.volume) : null,
      cj_buy:    r.cj_buy,
      cj_sell:   r.cj_sell,
    }
    let best = null, bestKey = null
    for (const k of opts) if (eff[k] != null && (best == null || eff[k] < best)) { best = eff[k]; bestKey = k }
    for (const k of opts) if (eff[k] != null) totals[k] += eff[k] * r.qty
    if (best != null) {
      totals.best += best * r.qty
      if (bestKey.startsWith('jita')) totals.delivery += dpu(r.volume) * r.qty
    }
    return { ...r, eff, bestKey, bestUnit: best }
  })
  return { rows: out, totals }
}

function bestBuyListOf(view) {
  if (!view) return []
  return ['jita', 'cj'].map(hub => ({ hub, items: view.rows.filter(r => r.bestKey?.startsWith(hub)) }))
}

/* ── Market analysis panel (4-source comparison + delivery) ── */
function MarketPanel({ view, bestBuyList, deliveryOn, setDeliveryOn, deliveryCoef, setDeliveryCoef }) {
  const t = view.totals
  const cell = (val, best) => (
    <td style={{ whiteSpace: 'nowrap', color: best ? '#4caf7d' : 'var(--text-bright)', fontWeight: best ? 600 : 400, background: best ? 'rgba(76,175,125,0.08)' : undefined }}>
      {val != null ? fmtIsk(val) : '—'}
    </td>
  )
  return (
    <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '10px 16px', background: 'var(--surface2)', borderBottom: '1px solid var(--border)', flexWrap: 'wrap' }}>
        <span style={{ fontSize: 12, fontWeight: 700, letterSpacing: 1, color: 'var(--accent)' }}>MARKET ANALYSIS</span>
        <label style={{ fontSize: 12, color: 'var(--text-bright)', display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
          <input type="checkbox" checked={deliveryOn} onChange={e => setDeliveryOn(e.target.checked)} />
          Add Jita→hub delivery
        </label>
        <label style={{ fontSize: 12, color: 'var(--text)', display: 'flex', alignItems: 'center', gap: 6 }}>
          ISK/m³
          <input type="number" value={deliveryCoef} onChange={e => setDeliveryCoef(e.target.value)} disabled={!deliveryOn} style={{ width: 90 }} />
        </label>
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table>
          <thead>
            <tr>
              <th>Item</th><th>Qty</th>
              <th>Jita Buy{deliveryOn ? ' +d' : ''}</th><th>Jita Sell{deliveryOn ? ' +d' : ''}</th>
              <th>C-J Buy</th><th>C-J Sell</th><th>Best</th>
            </tr>
          </thead>
          <tbody>
            {view.rows.map(r => (
              <tr key={r.type_id}>
                <td style={{ color: 'var(--text-white)', whiteSpace: 'nowrap' }}>{r.name}</td>
                <td style={{ color: 'var(--text)' }}>{r.qty.toLocaleString()}</td>
                {cell(r.eff.jita_buy,  r.bestKey === 'jita_buy')}
                {cell(r.eff.jita_sell, r.bestKey === 'jita_sell')}
                {cell(r.eff.cj_buy,    r.bestKey === 'cj_buy')}
                {cell(r.eff.cj_sell,   r.bestKey === 'cj_sell')}
                <td style={{ color: 'var(--accent)', fontSize: 11, whiteSpace: 'nowrap' }}>
                  {r.bestKey ? r.bestKey.replace('_', ' ').toUpperCase() : '—'}
                </td>
              </tr>
            ))}
            <tr style={{ background: 'var(--surface2)', fontWeight: 600 }}>
              <td colSpan={2} style={{ textAlign: 'right', color: 'var(--text)' }}>Total (all from)</td>
              <td style={{ whiteSpace: 'nowrap' }}>{fmtIsk(t.jita_buy)}</td>
              <td style={{ whiteSpace: 'nowrap' }}>{fmtIsk(t.jita_sell)}</td>
              <td style={{ whiteSpace: 'nowrap' }}>{fmtIsk(t.cj_buy)}</td>
              <td style={{ whiteSpace: 'nowrap' }}>{fmtIsk(t.cj_sell)}</td>
              <td style={{ color: '#4caf7d', whiteSpace: 'nowrap' }}>{fmtIsk(t.best)}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div style={{ padding: '10px 16px', borderTop: '1px solid var(--border)', display: 'flex', gap: 24, flexWrap: 'wrap', fontSize: 12 }}>
        <span style={{ color: 'var(--text)' }}>Best-mix total: <b style={{ color: '#4caf7d' }}>{fmtIsk(t.best)}</b></span>
        {deliveryOn && <span style={{ color: 'var(--text)' }}>incl. delivery <b style={{ color: 'var(--text-white)' }}>{fmtIsk(t.delivery)}</b></span>}
        <span style={{ color: 'var(--text)' }}>vs all-Jita-sell <b style={{ color: 'var(--text-white)' }}>{fmtIsk(t.jita_sell)}</b></span>
        <span style={{ color: 'var(--text)' }}>vs all-C-J-sell <b style={{ color: 'var(--text-white)' }}>{fmtIsk(t.cj_sell)}</b></span>
      </div>
      {/* best buy lists per hub */}
      <div style={{ padding: '0 16px 14px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {bestBuyList.map(({ hub, items }) => items.length > 0 && (
          <div key={hub}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '8px 0' }}>
              <span style={{ fontSize: 11, color: 'var(--accent)', fontWeight: 600 }}>
                🛒 Buy at {hub === 'jita' ? 'Jita' : 'C-J'} ({items.length})
              </span>
              <button className="btn btn-ghost btn-sm" onClick={() => navigator.clipboard.writeText(items.map(i => `${i.name}\t${i.qty}`).join('\n'))}>Copy</button>
            </div>
            <textarea readOnly rows={Math.min(items.length, 8)} value={items.map(i => `${i.name}\t${i.qty}`).join('\n')} style={{ fontFamily: 'monospace', fontSize: 12 }} />
          </div>
        ))}
      </div>
    </div>
  )
}

/* ── Multi-PAK combined buy list ── */
function CombinedBuyPanel({ jobs, projects, onClose }) {
  const [deliveryOn, setDeliveryOn]     = useState(false)
  const [deliveryCoef, setDeliveryCoef] = useState(1200)
  const [needs, setNeeds]   = useState([])
  const [rows, setRows]     = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr]       = useState('')

  const projIds = [...new Set(jobs.map(j => j.project_id))]
  const scopeProject = projIds.length === 1 ? projIds[0] : null
  const projLabel = scopeProject
    ? (projects.find(p => p.id === scopeProject)?.name || `#${scopeProject}`)
    : 'unassigned / mixed'

  async function build() {
    setLoading(true); setErr('')
    try {
      const agg = {}
      for (const j of jobs) {
        for (const m of (j.calc_snapshot?.materials || [])) {
          if (!agg[m.type_id]) agg[m.type_id] = { type_id: m.type_id, name: m.name, needed: 0 }
          agg[m.type_id].needed += m.adj_qty || 0
        }
      }
      const list = Object.values(agg)
      if (!list.length) { setErr('Selected jobs have no material snapshots'); setRows([]); setNeeds([]); return }

      const av = await post('/manufacturing/material-availability', {
        project_id: scopeProject,
        materials: list.map(m => ({ type_id: m.type_id, name: m.name, required_qty: m.needed })),
      })
      const avMap = {}; av.materials.forEach(m => { avMap[m.type_id] = m })
      const merged = list.map(m => {
        const available = avMap[m.type_id]?.available || 0
        return { ...m, available, shortfall: Math.max(0, m.needed - available) }
      }).sort((a, b) => b.shortfall - a.shortfall)
      setNeeds(merged)

      const shortIds = merged.filter(m => m.shortfall > 0).map(m => m.type_id)
      if (shortIds.length) {
        const [vols, jita, cj] = await Promise.all([
          get(`/eve/volumes?type_ids=${shortIds.join(',')}`).catch(() => ({})),
          fetchMarketPrices(shortIds, 'Jita').catch(() => ({})),
          fetchMarketPrices(shortIds, 'C-J').catch(() => ({})),
        ])
        setRows(merged.filter(m => m.shortfall > 0).map(m => ({
          type_id: m.type_id, name: m.name, qty: m.shortfall, volume: vols[m.type_id] || 0,
          jita_buy: jita[m.type_id]?.Buy ?? null, jita_sell: jita[m.type_id]?.Sell ?? null,
          cj_buy: cj[m.type_id]?.Buy ?? null, cj_sell: cj[m.type_id]?.Sell ?? null,
        })))
      } else { setRows([]) }
    } catch (e) { setErr(e.message) }
    finally { setLoading(false) }
  }

  useEffect(() => { build() }, [jobs.map(j => j.id).join(',')])

  const view = buildMarketView(rows, deliveryOn, deliveryCoef)
  const fullList = needs.filter(m => m.shortfall > 0).map(m => `${m.name}\t${m.shortfall}`).join('\n')

  return (
    <div className="card" style={{ padding: 0, overflow: 'hidden', marginBottom: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 16px', background: 'var(--surface2)', borderBottom: '1px solid var(--border)', flexWrap: 'wrap' }}>
        <span style={{ fontSize: 12, fontWeight: 700, letterSpacing: 1, color: 'var(--accent)' }}>
          COMBINED BUY LIST · {jobs.length} jobs
        </span>
        <span style={{ fontSize: 11, color: 'var(--text)' }}>project: <b style={{ color: 'var(--text-white)' }}>{projLabel}</b> · stock netted off</span>
        <button className="btn btn-ghost btn-sm" onClick={build} disabled={loading} style={{ marginLeft: 'auto' }}>
          {loading ? '…' : '⟳ Rebuild'}
        </button>
        <button className="btn btn-ghost btn-sm" onClick={onClose}>✕</button>
      </div>

      {err && <div className="error-box" style={{ margin: 12 }}>{err}</div>}

      {/* needs vs stock */}
      {needs.length > 0 && (
        <table>
          <thead><tr><th>Material</th><th>Needed (all jobs)</th><th>On hand</th><th>To buy</th></tr></thead>
          <tbody>
            {needs.map(m => (
              <tr key={m.type_id}>
                <td style={{ color: 'var(--text-white)', whiteSpace: 'nowrap' }}>{m.name}</td>
                <td>{m.needed.toLocaleString()}</td>
                <td style={{ color: m.available >= m.needed ? '#4caf7d' : 'var(--text)' }}>{m.available.toLocaleString()}</td>
                <td style={{ color: m.shortfall > 0 ? '#e05252' : '#4caf7d', fontWeight: 500 }}>
                  {m.shortfall > 0 ? m.shortfall.toLocaleString() : '✓'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {fullList && (
        <div style={{ padding: '12px 16px', borderTop: '1px solid var(--border)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
            <span style={{ fontSize: 11, color: '#e05252', fontWeight: 600 }}>🛒 Shortfall multibuy</span>
            <button className="btn btn-ghost btn-sm" onClick={() => navigator.clipboard.writeText(fullList)}>Copy</button>
          </div>
          <textarea readOnly value={fullList} rows={Math.min(needs.filter(m => m.shortfall > 0).length, 10)} style={{ fontFamily: 'monospace', fontSize: 12 }} />
        </div>
      )}

      {view && view.rows.length > 0 && (
        <div style={{ padding: 12 }}>
          <MarketPanel view={view} bestBuyList={bestBuyListOf(view)}
            deliveryOn={deliveryOn} setDeliveryOn={setDeliveryOn}
            deliveryCoef={deliveryCoef} setDeliveryCoef={setDeliveryCoef} />
        </div>
      )}
      {rows && rows.length === 0 && !loading && (
        <div style={{ padding: 16, color: '#4caf7d', fontSize: 13 }}>✓ Everything needed is already in stock.</div>
      )}
    </div>
  )
}

/* ── Cost composition donut ── */
function Donut({ data, size = 150, thickness = 24 }) {
  const total = data.reduce((s, d) => s + d.value, 0) || 1
  const r = (size - thickness) / 2
  const circ = 2 * Math.PI * r
  let offset = 0
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <g transform={`rotate(-90 ${size / 2} ${size / 2})`}>
        {data.map((d, i) => {
          const dash = (d.value / total) * circ
          const el = (
            <circle key={i} cx={size / 2} cy={size / 2} r={r} fill="none"
              stroke={d.color} strokeWidth={thickness}
              strokeDasharray={`${dash} ${circ - dash}`} strokeDashoffset={-offset} />
          )
          offset += dash
          return el
        })}
      </g>
    </svg>
  )
}

function CostPie({ result }) {
  const data = [
    ...result.materials.map((m, i) => ({ label: m.name, value: m.gross_cost, color: PIE_COLORS[i % PIE_COLORS.length] })),
    { label: 'Job install', value: result.job_cost.net_install_cost, color: '#e05252' },
    ...(result.bpc_cost ? [{ label: 'BPC', value: result.bpc_cost, color: '#777' }] : []),
  ].filter(d => d.value > 0).sort((a, b) => b.value - a.value)
  const total = data.reduce((s, d) => s + d.value, 0) || 1
  return (
    <div style={{ display: 'flex', gap: 16, alignItems: 'center', padding: 8, flexWrap: 'wrap' }}>
      <Donut data={data} />
      <div style={{ flex: 1, minWidth: 160, display: 'flex', flexDirection: 'column', gap: 3 }}>
        {data.slice(0, 10).map((d, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11 }}>
            <span style={{ width: 9, height: 9, borderRadius: 2, background: d.color, flexShrink: 0 }} />
            <span style={{ color: 'var(--text-white)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{d.label}</span>
            <span style={{ color: 'var(--text)' }}>{(d.value / total * 100).toFixed(1)}%</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function ProductionMetrics({ result }) {
  const hours = result.job_time?.hours || 0     // parallel slots → batch wall-clock
  const windows = result.windows || 1
  const profit = result.results.profit
  const costs = result.results.total_costs
  const units = result.output.quantity
  const profitPerHour = hours ? profit / hours : null   // whole batch finishes in `hours`
  const roi = costs ? profit / costs * 100 : null
  const unitsPerHour = hours ? units / hours : null
  const profitPerUnit = units ? profit / units : null
  const profitPerWindow = windows ? profit / windows : null
  const stats = [
    { label: 'Profit (batch)', value: fmtIsk(profit), color: profit >= 0 ? '#4caf7d' : '#e05252' },
    { label: `Profit / window (×${windows})`, value: profitPerWindow != null ? fmtIsk(profitPerWindow) : '—', color: profitPerWindow >= 0 ? '#4caf7d' : '#e05252' },
    { label: 'Profit / hour', value: profitPerHour != null ? fmtIsk(profitPerHour) : '—', color: profitPerHour >= 0 ? '#4caf7d' : '#e05252' },
    { label: 'ROI', value: roi != null ? roi.toFixed(1) + '%' : '—', color: roi >= 0 ? '#4caf7d' : '#e05252' },
    { label: 'Profit / unit', value: profitPerUnit != null ? fmtIsk(profitPerUnit) : '—' },
    { label: 'Units / hour', value: unitsPerHour != null ? Math.round(unitsPerHour).toLocaleString() : '—' },
    { label: 'Job time', value: hours.toFixed(1) + ' h' },
    { label: 'Output', value: units.toLocaleString() },
  ]
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(120px,1fr))', gap: 12, padding: 8 }}>
      {stats.map((s, i) => (
        <div key={i}>
          <div style={statLabel}>{s.label}</div>
          <div style={{ fontWeight: 600, color: s.color || 'var(--text-white)' }}>{s.value}</div>
        </div>
      ))}
    </div>
  )
}

function LegendDot({ color, label }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
      <span style={{ width: 10, height: 10, borderRadius: 2, background: color, flexShrink: 0 }} />
      {label}
    </span>
  )
}

// Chain analytics — mirrors the Calculator tab's ProductionMetrics, fed from the plan.
function ChainMetrics({ plan, totalCost, profit, buildHours }) {
  const units = plan.target_qty || 0
  const pos = c => (c == null ? undefined : c >= 0 ? '#4caf7d' : '#e05252')
  const roi = (profit != null && totalCost) ? profit / totalCost * 100 : null
  const profitPerHour = (profit != null && buildHours) ? profit / buildHours : null
  const profitPerUnit = (profit != null && units) ? profit / units : null
  const unitsPerHour = buildHours ? units / buildHours : null
  const stats = [
    { label: 'Profit', value: profit != null ? fmtIsk(profit) : '—', color: pos(profit) },
    { label: 'ROI', value: roi != null ? roi.toFixed(1) + '%' : '—', color: pos(roi) },
    { label: 'Profit / hour', value: profitPerHour != null ? fmtIsk(profitPerHour) : '—', color: pos(profitPerHour) },
    { label: 'Profit / unit', value: profitPerUnit != null ? fmtIsk(profitPerUnit) : '—', color: pos(profitPerUnit) },
    { label: 'Units / hour', value: unitsPerHour ? Math.round(unitsPerHour).toLocaleString() : '—' },
    { label: 'Est. build time', value: buildHours ? buildHours.toFixed(1) + ' h' : '—' },
    { label: 'Output', value: units.toLocaleString() },
    { label: 'Total cost', value: totalCost != null ? fmtIsk(totalCost) : '—' },
  ]
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(120px,1fr))', gap: 12, padding: 8 }}>
      {stats.map((s, i) => (
        <div key={i}>
          <div style={statLabel}>{s.label}</div>
          <div style={{ fontWeight: 600, color: s.color || 'var(--text-white)' }}>{s.value}</div>
        </div>
      ))}
    </div>
  )
}

// Cost breakdown pie for the whole chain: every bought line + total install + BPC.
function ChainCostPie({ plan }) {
  const jobs = plan.jobs || []
  const install = jobs.reduce((s, j) => s + (j.install_cost || 0), 0)
  const bpc = jobs.reduce((s, j) => s + (j.bpc_cost || 0), 0)
  const data = [
    ...(plan.shopping_list || []).map((s, i) => ({ label: s.name, value: s.total, color: PIE_COLORS[i % PIE_COLORS.length] })),
    { label: 'Job install', value: install, color: '#e05252' },
    ...(bpc ? [{ label: 'BPC', value: bpc, color: '#777' }] : []),
  ].filter(d => d.value > 0).sort((a, b) => b.value - a.value)
  const total = data.reduce((s, d) => s + d.value, 0) || 1
  if (!data.length) return null
  return (
    <div style={{ display: 'flex', gap: 16, alignItems: 'center', padding: 8, flexWrap: 'wrap' }}>
      <Donut data={data} />
      <div style={{ flex: 1, minWidth: 160, display: 'flex', flexDirection: 'column', gap: 3 }}>
        {data.slice(0, 12).map((d, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11 }}>
            <span style={{ width: 9, height: 9, borderRadius: 2, background: d.color, flexShrink: 0 }} />
            <span style={{ color: 'var(--text-white)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{d.label}</span>
            <span style={{ color: 'var(--text)' }}>{(d.value / total * 100).toFixed(1)}%</span>
          </div>
        ))}
      </div>
    </div>
  )
}

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
