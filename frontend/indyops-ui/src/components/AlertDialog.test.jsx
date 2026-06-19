import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('../api/client', () => ({
  get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(),
}))
import { get } from '../api/client'
import AlertDialog from './AlertDialog'

const ALERTS = [
  { id: 1, target_kind: 'index', index_key: 'plex', item_id: null, metric: 'price',
    condition: 'above', threshold: 5_000_000, window_hours: 24, active: true, repeat: false, note: null },
  { id: 2, target_kind: 'item', index_key: null, item_id: 7, metric: 'volume',
    condition: 'pct_up', threshold: 20, window_hours: 24, active: true, repeat: true, note: 'spike' },
]

beforeEach(() => {
  get.mockReset()
  get.mockResolvedValue(ALERTS)
})

describe('AlertDialog', () => {
  it('shows the create form and only this index\'s existing alerts', async () => {
    render(<AlertDialog target={{ kind: 'index', key: 'plex', label: 'PLEX' }} onClose={() => {}} />)
    expect(await screen.findByText(/ALERTS · PLEX/)).toBeInTheDocument()
    expect(screen.getByText('Create alert')).toBeInTheDocument()
    // index alert (id 1) shows; the item alert (id 2) is filtered out
    expect(screen.getByText('price ≥ 5.00M')).toBeInTheDocument()
    expect(screen.queryByText(/volume \+20%/)).not.toBeInTheDocument()
  })

  it('filters to the tracked item and offers a place selector', async () => {
    render(<AlertDialog target={{ kind: 'item', itemId: 7, label: 'Tritanium',
      places: [{ id: 1, name: 'Jita' }] }} onClose={() => {}} />)
    expect(await screen.findByText(/ALERTS · Tritanium/)).toBeInTheDocument()
    expect(screen.getByText('volume +20% / 24h · repeats')).toBeInTheDocument()
    expect(screen.queryByText('price ≥ 5.00M')).not.toBeInTheDocument()
    expect(screen.getByText('Auto (first place)')).toBeInTheDocument()
  })
})
