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

  it('shows the notifications feed (no alerts panel)', async () => {
    render(<AgendaPage />)
    expect(await screen.findByText('PLEX: price crossed above 5.00M')).toBeInTheDocument()
    expect(screen.getByText('NOTIFICATIONS')).toBeInTheDocument()
    expect(screen.getByText('1 new')).toBeInTheDocument()
    // the alert-creation panel was moved to the Analysis tabs' 🔔 dialog
    expect(screen.queryByText('Create alert')).not.toBeInTheDocument()
    expect(screen.queryByText('ALERTS')).not.toBeInTheDocument()
  })
})
