import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('../api/client', () => ({
  get: vi.fn().mockResolvedValue({ by_article: [], by_section: [] }),
  post: vi.fn(),
}))
import { get } from '../api/client'
import EncyclopediaPage from './EncyclopediaPage'

beforeEach(() => get.mockClear())

describe('EncyclopediaPage', () => {
  it('renders the sidebar sections, the first article and its quiz', async () => {
    render(<EncyclopediaPage />)
    expect(get).toHaveBeenCalledWith('/encyclopedia/scores')
    expect(screen.getByText('📚 Encyclopedia')).toBeInTheDocument()
    // MC article appears in the sidebar and as the body heading
    expect(screen.getAllByText('Monte-Carlo Simulation').length).toBeGreaterThan(0)
    // the other article is listed in the sidebar (also referenced in the MC body)
    expect(screen.getAllByText('Scenario Simulation').length).toBeGreaterThan(0)
    // the quiz renders at the bottom of the active article (count is content-driven)
    expect(await screen.findByText(/Quiz — \d+ questions/)).toBeInTheDocument()
  })
})
