import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

vi.mock('../api/client', () => ({ get: vi.fn(), post: vi.fn(), download: vi.fn() }))
import { get, post, download } from '../api/client'

// Stub the heavy Plotly stack (same pattern as SimulationPanel.test).
vi.mock('react-plotly.js/factory', () => ({
  default: () => function PlotMock() { return <div data-testid="plot" /> },
}))
vi.mock('plotly.js-dist-min', () => ({ default: {} }))

import ScenarioPanel from './ScenarioPanel'

const CATALOG = {
  categories: [
    { category: 'exogenous', scenarios: [
      { key: 'market_shock_up', name: 'Market Shock (up)', category: 'exogenous', description: 'shock', params: {} },
      { key: 'tax_increase', name: 'Tax Increase', category: 'exogenous', description: 'tax', params: {} },
    ] },
    { category: 'logistics', scenarios: [
      { key: 'freighter_risk', name: 'Freighter Risk Increase', category: 'logistics', description: 'risk', params: {} },
    ] },
  ],
  scenarios: [],
}

const ANALYSIS = {
  analysis_id: 77,
  engine: 'fortran',
  n_scenarios: 1,
  baseline: { expected_profit: 1e9, std: 2e8, var5: -1e8, prob_loss: 0.1 },
  outcomes: [{
    key: 'market_shock_up', name: 'Market Shock (up)', category: 'exogenous',
    metrics: { expected_profit: 1.3e9, std: 3e8, var5: -1.5e8, prob_loss: 0.12 },
    comparison: { abs_profit_change: 3e8, pct_profit_change: 0.3, std_change: 1e8,
                  var5_change: -5e7, prob_loss_change: 0.02, roi_change: 0.05, viable: true },
  }],
  ranking: [{ rank: 1, label: 'Market Shock (up)', score: 1.5 },
            { rank: 2, label: '● Baseline', score: 0.0 }],
}

beforeEach(() => {
  get.mockReset(); post.mockReset(); download.mockReset()
})

describe('ScenarioPanel', () => {
  it('loads the catalog and renders scenarios grouped by category', async () => {
    get.mockResolvedValue(CATALOG)
    render(<ScenarioPanel source="production" buildBody={() => ({})} />)
    expect(get).toHaveBeenCalledWith('/simulation/scenarios')
    expect(await screen.findByText('Market Shock (up)')).toBeInTheDocument()
    expect(screen.getByText('Tax Increase')).toBeInTheDocument()
    expect(screen.getByText('Freighter Risk Increase')).toBeInTheDocument()
    expect(screen.getByText(/Exogenous/i)).toBeInTheDocument()
  })

  it('runs the analysis and renders the comparison table + ranking', async () => {
    get.mockResolvedValue(CATALOG)
    post.mockResolvedValue({ scenario_analysis: ANALYSIS })
    render(<ScenarioPanel source="chain" buildBody={() => ({ product_type_id: 5 })} targetTypeId={5} />)
    await screen.findByText('Market Shock (up)')

    fireEvent.click(screen.getByText(/Run Scenario Analysis/i))

    await waitFor(() => expect(post).toHaveBeenCalled())
    const [url, body] = post.mock.calls[0]
    expect(url).toBe('/manufacturing/calculate-chain')
    expect(body.product_type_id).toBe(5)
    expect(body.scenarios).toBeTruthy()

    // baseline row + scenario outcome + ranking chip
    expect(await screen.findByText('● Baseline')).toBeInTheDocument()
    expect(screen.getByText('+30.0%')).toBeInTheDocument()       // pct profit change
    expect(screen.getByText(/#1 Market Shock/)).toBeInTheDocument()
  })

  it('surfaces a backend scenario error', async () => {
    get.mockResolvedValue(CATALOG)
    post.mockResolvedValue({ scenario_analysis: { error: 'history unavailable' } })
    render(<ScenarioPanel source="production" buildBody={() => ({})} />)
    await screen.findByText('Market Shock (up)')
    fireEvent.click(screen.getByText(/Run Scenario Analysis/i))
    expect(await screen.findByText('history unavailable')).toBeInTheDocument()
  })

  it('warns when there is nothing to calculate', async () => {
    get.mockResolvedValue(CATALOG)
    render(<ScenarioPanel source="production" buildBody={() => null} />)
    await screen.findByText('Market Shock (up)')
    fireEvent.click(screen.getByText(/Run Scenario Analysis/i))
    expect(await screen.findByText(/Run a calculation first/i)).toBeInTheDocument()
    expect(post).not.toHaveBeenCalled()
  })

  it('downloads the scenario PDF and the product report', async () => {
    get.mockResolvedValue(CATALOG)
    post.mockResolvedValue({ scenario_analysis: ANALYSIS })
    download.mockResolvedValue()
    render(<ScenarioPanel source="chain" buildBody={() => ({})} targetTypeId={5} />)
    await screen.findByText('Market Shock (up)')
    fireEvent.click(screen.getByText(/Run Scenario Analysis/i))
    await screen.findByText('● Baseline')

    fireEvent.click(screen.getByText(/Scenario PDF/i))
    fireEvent.click(screen.getByText(/Full product report/i))
    await waitFor(() => {
      expect(download).toHaveBeenCalledWith('/simulation/scenario-runs/77/pdf', 'scenario_77.pdf')
      // product report is scoped to the current analysis, not the whole history
      expect(download).toHaveBeenCalledWith('/simulation/reports/product/5/pdf?analysis_id=77', 'product_5_report.pdf')
    })
  })
})
