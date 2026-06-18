import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

// Mock the API client before importing the page so its mount-effects hit the mock.
vi.mock('../api/client', () => ({ get: vi.fn() }))
import { get } from '../api/client'
import TradeOptimizerPage from './TradeOptimizerPage'

const HUBS = [
  { name: 'Jita', station_id: 60003760, region_id: 10000002 },
  { name: 'Amarr', station_id: 60008494, region_id: 10000043 },
]

// Route the mock by path; tolerate any stray/teardown calls so an unexpected
// invocation never throws and masks the assertion under test.
function mockApi(candidatesResponse) {
  get.mockImplementation((path) => {
    if (typeof path !== 'string') return Promise.resolve(null)
    if (path.startsWith('/trade/hubs')) return Promise.resolve(HUBS)
    if (path.startsWith('/trade/candidates')) return Promise.resolve(candidatesResponse)
    return Promise.resolve({ count: 0, rows: [] })
  })
}

beforeEach(() => get.mockReset())

describe('TradeOptimizerPage', () => {
  it('loads hubs and renders a ranked cross-hub route', async () => {
    mockApi({
      strategy: 'patient', count: 1, updated_at: '2026-06-18T00:00:00+00:00',
      stale: false, ttl_seconds: 900,
      rows: [{
        item_id: 34, type_name: 'Tritanium', buy_hub: 'Jita', sell_hub: 'Amarr',
        buy_price: 5, sell_price: 7, margin_pct: 0.2, profit_isk: 1.2,
        daily_volume: 1000, volume_score: 0.8, units: 100, trip_profit: 120, score: 0.16,
      }],
    })

    render(<TradeOptimizerPage />)

    // hub toggles render once /trade/hubs resolves (one per buy/sell rail)
    expect((await screen.findAllByRole('button', { name: 'Jita' })).length).toBeGreaterThan(0)
    // the candidate row renders with its margin formatted as a percentage
    expect(await screen.findByText('Tritanium')).toBeInTheDocument()
    expect(screen.getByText('20.0%')).toBeInTheDocument()

    await waitFor(() => {
      expect(get).toHaveBeenCalledWith(expect.stringContaining('/trade/hubs'))
      expect(get).toHaveBeenCalledWith(expect.stringContaining('/trade/candidates'))
    })
  })

  it('shows the empty state when no candidates match', async () => {
    mockApi({ count: 0, updated_at: null, stale: true, ttl_seconds: 900, rows: [] })
    render(<TradeOptimizerPage />)
    expect(await screen.findByText(/No candidates match/i)).toBeInTheDocument()
  })
})
