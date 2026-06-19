import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('../api/client', () => ({
  get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(),
}))
import { get } from '../api/client'
import AgendaPage from './AgendaPage'

const RESPONSES = {
  '/agenda/ticker': {
    entries: [
      { kind: 'index', key: 'plex', label: 'PLEX', price: 5_200_000, volume: 100, change_pct: 4.0 },
      { kind: 'item', key: 7, label: 'Tritanium', price: 5.5, volume: 999, change_pct: -1.5 },
    ],
  },
  '/agenda/notifications': {
    unread: 1,
    notifications: [
      { id: 1, alert_id: 1, severity: 'up', title: 'PLEX: price crossed above 5.00M',
        body: 'Now 5.20M · +4.0% vs 24h ago', read: false, created_at: new Date().toISOString() },
    ],
  },
  '/agenda/alerts': [
    { id: 1, target_kind: 'index', index_key: 'plex', item_id: null, place_id: null,
      metric: 'price', condition: 'above', threshold: 5_000_000, window_hours: 24,
      active: true, repeat: false, note: null, label: 'PLEX', last_value: 5_200_000,
      last_triggered_at: null, created_at: new Date().toISOString() },
  ],
  '/analysis/indices': { indices: [{ key: 'plex', label: 'PLEX' }] },
  '/tracking/items': [{ id: 7, type_id: 34, name: 'Tritanium', place_ids: [1] }],
  '/tracking/places': [{ id: 1, name: 'Jita', kind: 'system' }],
}

beforeEach(() => {
  get.mockReset()
  get.mockImplementation(path => Promise.resolve(RESPONSES[path] ?? {}))
})

describe('AgendaPage', () => {
  it('renders the ticker with index + item prices', async () => {
    render(<AgendaPage />)
    // PLEX appears in the ticker (duplicated for the marquee loop)
    expect((await screen.findAllByText('PLEX')).length).toBeGreaterThan(0)
    expect(screen.getAllByText('Tritanium').length).toBeGreaterThan(0)
  })

  it('shows the notifications feed', async () => {
    render(<AgendaPage />)
    expect(await screen.findByText('PLEX: price crossed above 5.00M')).toBeInTheDocument()
    expect(screen.getByText('NOTIFICATIONS')).toBeInTheDocument()
    expect(screen.getByText('1 new')).toBeInTheDocument()
  })

  it('lists existing alerts and the create form', async () => {
    render(<AgendaPage />)
    expect(await screen.findByText('price ≥ 5.00M')).toBeInTheDocument()
    expect(screen.getByText('Create alert')).toBeInTheDocument()
  })
})
