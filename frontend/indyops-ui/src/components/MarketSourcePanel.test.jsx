import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import { useState } from 'react'
import MarketSourcePanel from './MarketSourcePanel'

const REGIONS = [{ id: 1, name: 'Jita' }, { id: 2, name: 'Amarr' }]

// Controlled host mirroring how the Chain/Calculator tabs drive the panel.
function Host({ onState }) {
  const [selectedRegions, setSel] = useState(new Set([1]))
  const [regionSide, setRS] = useState({ 1: 'buy' })
  const [includeCJ, setCJ] = useState(false)
  const [rules, setRules] = useState([])
  const toggleRegion = rid => setSel(prev => {
    const n = new Set(prev)
    if (n.has(rid)) { if (n.size > 1) n.delete(rid) } else n.add(rid)
    return n
  })
  const setSide = (k, s) => setRS(m => ({ ...m, [k]: s }))
  onState?.({ selectedRegions, regionSide, includeCJ, rules })
  return (
    <MarketSourcePanel
      regions={REGIONS}
      selectedRegions={selectedRegions} toggleRegion={toggleRegion}
      regionSide={regionSide} setSide={setSide}
      includeCJ={includeCJ} setIncludeCJ={setCJ}
      rules={rules} setRules={setRules}
      groupOptions={['Mineral', 'Component']}
    />
  )
}

function renderHost() {
  let state
  render(<Host onState={s => { state = s }} />)
  return () => state
}

describe('MarketSourcePanel', () => {
  it('lists the regions and the C-J market', () => {
    renderHost()
    expect(screen.getByText('Jita')).toBeInTheDocument()
    expect(screen.getByText('Amarr')).toBeInTheDocument()
    expect(screen.getByText('C-J6MT')).toBeInTheDocument()
  })

  it('disables the side toggle of an unselected market', () => {
    renderHost()
    // Jita is selected → its Buy/Sell enabled; Amarr unselected → disabled.
    const jitaRow = screen.getByText('Jita').closest('div')
    const amarrRow = screen.getByText('Amarr').closest('div')
    expect(within(jitaRow).getByRole('button', { name: 'buy' })).not.toBeDisabled()
    expect(within(amarrRow).getByRole('button', { name: 'buy' })).toBeDisabled()
  })

  it('toggles a region on and records a per-region side', () => {
    const state = renderHost()
    fireEvent.click(screen.getByLabelText('Amarr'))
    expect([...state().selectedRegions]).toEqual([1, 2])
    // pick Sell for Jita
    const jitaRow = screen.getByText('Jita').closest('div')
    fireEvent.click(within(jitaRow).getByRole('button', { name: 'sell' }))
    expect(state().regionSide[1]).toBe('sell')
  })

  it('adds, edits and removes a custom group rule', () => {
    const state = renderHost()
    fireEvent.click(screen.getByText('+ Add rule'))
    // A new rule defaults to the side OPPOSITE the prevailing market side (Jita is on Buy),
    // so it has an immediate effect instead of silently matching the default.
    expect(state().rules).toEqual([{ group: 'Mineral', side: 'sell' }])

    // change the rule's group to Component and its side back to Buy
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'Component' } })
    expect(state().rules[0].group).toBe('Component')
    const ruleRow = screen.getByRole('combobox').closest('div')
    fireEvent.click(within(ruleRow).getByRole('button', { name: 'buy' }))
    expect(state().rules[0].side).toBe('buy')

    fireEvent.click(screen.getByTitle('Remove rule'))
    expect(state().rules).toEqual([])
  })

  it('disables Add rule when there are no group options', () => {
    render(
      <MarketSourcePanel
        regions={REGIONS} selectedRegions={new Set([1])} toggleRegion={() => {}}
        regionSide={{ 1: 'buy' }} setSide={() => {}}
        includeCJ={false} setIncludeCJ={() => {}}
        rules={[]} setRules={() => {}} groupOptions={[]}
      />,
    )
    expect(screen.getByText('+ Add rule')).toBeDisabled()
  })
})
