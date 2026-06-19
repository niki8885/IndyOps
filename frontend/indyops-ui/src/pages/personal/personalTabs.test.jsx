import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

// Mock the API client before importing the tabs so their mount-effects hit the mock.
vi.mock('../../api/client', () => ({
  get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(),
}))
import { get } from '../../api/client'

import StandingsTab from './StandingsTab'
import StatisticsTab from './StatisticsTab'
import SettingsTab from './SettingsTab'
import IndustryTab from './IndustryTab'
import JournalTab from './JournalTab'
import CharactersTab from './CharactersTab'

beforeEach(() => get.mockReset())

describe('StandingsTab', () => {
  it('shows the empty state with no standings', async () => {
    get.mockResolvedValue([])
    render(<StandingsTab charId={1} />)
    expect(await screen.findByText(/No standings synced/i)).toBeInTheDocument()
  })

  it('renders standing rows with names + values', async () => {
    get.mockResolvedValue([{ from_id: 5, from_type: 'faction', name: 'Caldari State', standing: 7.5 }])
    render(<StandingsTab charId={1} />)
    expect(await screen.findByText('Caldari State')).toBeInTheDocument()
    expect(screen.getByText('7.50')).toBeInTheDocument()
  })
})

describe('SettingsTab', () => {
  it('renders the settings form from saved values', async () => {
    get.mockResolvedValue({ mining_tax_pct: 10, price_basis: 'sell', refine_base_yield: 0.5 })
    render(<SettingsTab charId={1} />)
    expect(await screen.findByText(/JOURNAL SETTINGS/i)).toBeInTheDocument()
    expect(screen.getByText(/Mining tax/i)).toBeInTheDocument()
    expect(screen.getByText(/Refine base yield/i)).toBeInTheDocument()
  })
})

describe('IndustryTab', () => {
  it('shows slot cards and a job row with location', async () => {
    get.mockResolvedValue({
      slots: {
        manufacturing: { used: 1, max: 6 },
        science: { used: 0, max: 1 },
        reaction: { used: 0, max: 1 },
      },
      jobs: [{
        job_id: 1, product_name: 'Widget', activity: 'Manufacturing', runs: 1, status: 'active',
        cost: 1000, start_date: '2026-06-01T00:00:00', end_date: '2026-07-01T00:00:00', location_name: 'Jita IV',
      }],
    })
    render(<IndustryTab charId={1} />)
    expect(await screen.findByText('Widget')).toBeInTheDocument()
    expect(screen.getByText('Research')).toBeInTheDocument()   // a slot card label
    expect(screen.getByText('Jita IV')).toBeInTheDocument()
  })
})

describe('StatisticsTab', () => {
  it('renders the category breakdown, totals and 30-day stats', async () => {
    get.mockResolvedValue({
      period: { type: 'month', key: '2026-06', scope: 'character' },
      basis: 'sell', tax_pct: 10,
      categories: {
        ore: { value: 100000, qty: 10000 }, moon_ore: { value: 0, qty: 0 },
        ice: { value: 0, qty: 0 }, gas: { value: 0, qty: 0 }, other: { value: 0, qty: 0 },
      },
      items: [{ type_id: 1230, name: 'Veldspar', category: 'ore', qty: 10000, value: 100000 }],
      gross_value: 100000, tax_amount: 10000, net_value: 90000, written_off: false,
      stats_30d: { total: 100000, categories: {} },
    })
    render(<StatisticsTab charId={1} />)
    expect((await screen.findAllByText('Regular ore')).length).toBeGreaterThan(0)
    expect(screen.getByText('Write off tax')).toBeInTheDocument()
    expect(screen.getByText('LAST 30 DAYS')).toBeInTheDocument()
    expect(screen.getByText('Veldspar')).toBeInTheDocument()
  })
})

describe('JournalTab', () => {
  it('renders historical ledger entries newest first with totals', async () => {
    get.mockResolvedValue({
      scope: 'character', period: null, count: 2, total_quantity: 17000,
      entries: [
        { date: '2026-06-18', type_id: 1230, name: 'Veldspar', category: 'ore',
          solar_system_id: 30000142, system_name: 'Jita', quantity: 12000,
          character_id: 99, character_name: 'Miner' },
        { date: '2026-06-16', type_id: 1230, name: 'Veldspar', category: 'ore',
          solar_system_id: 30000142, system_name: 'Jita', quantity: 5000,
          character_id: 99, character_name: 'Miner' },
      ],
    })
    render(<JournalTab charId={1} />)
    expect((await screen.findAllByText('Veldspar')).length).toBe(2)
    expect(screen.getAllByText('Jita').length).toBeGreaterThan(0)
    expect(screen.getByText('12,000')).toBeInTheDocument()
    expect(screen.getByText(/17,000 units/)).toBeInTheDocument()
  })

  it('shows the empty state when nothing was mined', async () => {
    get.mockResolvedValue({ scope: 'character', period: null, count: 0, total_quantity: 0, entries: [] })
    render(<JournalTab charId={1} />)
    expect(await screen.findByText(/No mining recorded/i)).toBeInTheDocument()
  })
})

describe('CharactersTab', () => {
  it('lists characters and offers the add button', () => {
    render(
      <CharactersTab
        chars={[{ id: 1, character_id: 99, character_name: 'Miner Joe', portrait: 'x',
                  is_active: true, scopes: [], corporation_name: 'GSF' }]}
        reload={() => {}} onOpen={() => {}}
      />,
    )
    expect(screen.getByText('Miner Joe')).toBeInTheDocument()
    expect(screen.getByText(/Add EVE character/i)).toBeInTheDocument()
  })
})
