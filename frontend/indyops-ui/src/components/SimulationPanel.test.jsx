import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

// Mock the API client (mount-effect fetches the run detail).
vi.mock('../api/client', () => ({ get: vi.fn(), download: vi.fn() }))
import { get, download } from '../api/client'

// Stub the heavy Plotly stack: factory default → fn → stub component.
let lastPlotProps = null
vi.mock('react-plotly.js/factory', () => ({
  default: () => function PlotMock(props) {
    lastPlotProps = props
    return <div data-testid="plot" />
  },
}))
vi.mock('plotly.js-dist-min', () => ({ default: {} }))

import SimulationPanel from './SimulationPanel'

beforeEach(() => {
  get.mockReset()
  download.mockReset()
  lastPlotProps = null
})

const RUN = {
  run_id: 'abc-123',
  engine: 'fortran',
  n_iterations: 25000,
  summary: { expected_profit: 1.2e9, prob_loss: 0.1 },
}

const METRICS = {
  expected_profit: 1.5e9,
  median_profit: 1.4e9,
  std: 3.2e8,
  cv: 0.21,
  var5: -2.5e8,
  var1: -5e8,
  cvar5: -3e8,
  worst1: -7e8,
  prob_loss: 0.08,
  sharpe_like: 1.85,
  return_per_slot: 4.5e7,
  return_per_time: 9e6,
  hist_counts: [2, 5, 9, 4, 1],
  hist_edges: [-1e9, -5e8, 0, 5e8, 1e9, 1.5e9],
  ci95: { expected_profit: [1.4e9, 1.6e9], var5: [-2.6e8, -2.4e8] },
  best: 2e9,
  worst: -8e8,
  time_mean_h: 36.5,
  mc_rel_error: 0.012,
  converged: true,
}

describe('SimulationPanel', () => {
  it('renders null when there is no run', () => {
    const { container } = render(<SimulationPanel run={null} />)
    expect(container.firstChild).toBeNull()
    expect(get).not.toHaveBeenCalled()
  })

  it('renders the error box when the run failed', () => {
    render(<SimulationPanel run={{ error: 'engine crashed' }} />)
    expect(screen.getByText(/Monte-Carlo simulation failed/i)).toBeInTheDocument()
    expect(screen.getByText(/engine crashed/i)).toBeInTheDocument()
  })

  it('shows the loading state then the metrics + stub chart once detail resolves', async () => {
    let resolveDetail
    get.mockReturnValue(new Promise(r => { resolveDetail = r }))

    render(<SimulationPanel run={RUN} />)

    // header + engine badge render immediately from `run`
    expect(screen.getByText(/Monte-Carlo profit simulation/i)).toBeInTheDocument()
    expect(screen.getByText(/fortran · 25,000 runs/i)).toBeInTheDocument()
    // loading message before detail arrives
    expect(screen.getByText(/Loading distribution/i)).toBeInTheDocument()
    expect(get).toHaveBeenCalledWith('/simulation/runs/abc-123')

    // stat labels render from the summary fallback
    expect(screen.getByText('Expected profit')).toBeInTheDocument()
    expect(screen.getByText('VaR 5%')).toBeInTheDocument()
    expect(screen.getByText('Prob. of loss')).toBeInTheDocument()
    expect(screen.getByText('Sharpe-like')).toBeInTheDocument()
    expect(screen.getByText('Return / slot')).toBeInTheDocument()

    resolveDetail({ metrics: METRICS })

    // chart appears once metrics arrive; loading message disappears
    await waitFor(() => expect(screen.getByTestId('plot')).toBeInTheDocument())
    expect(screen.queryByText(/Loading distribution/i)).not.toBeInTheDocument()

    // metric-derived formatting (isk / pct / num)
    expect(screen.getByText('1.50 B')).toBeInTheDocument()        // expected profit
    expect(screen.getByText('8.00%')).toBeInTheDocument()         // prob of loss
    expect(screen.getByText('1.850')).toBeInTheDocument()         // sharpe-like (num,3)
    expect(screen.getByText(/95% CI ±/)).toBeInTheDocument()      // CI sub-label
    // footer summary + convergence note
    expect(screen.getByText(/Mean completion 36.50 h/)).toBeInTheDocument()
    expect(screen.getByText(/converged/)).toBeInTheDocument()
    expect(screen.getByText(/MC error 1.20%/)).toBeInTheDocument()

    // histogram fed into the stub chart
    const bar = lastPlotProps.data[0]
    expect(bar.type).toBe('bar')
    expect(bar.y).toEqual(METRICS.hist_counts)
    expect(bar.x).toHaveLength(METRICS.hist_counts.length)   // bin centres
  })

  it('surfaces a fetch error from the detail request', async () => {
    get.mockRejectedValue(new Error('boom'))
    render(<SimulationPanel run={RUN} />)
    expect(await screen.findByText('boom')).toBeInTheDocument()
  })

  it('shows the project roll-up button only when projectId is set', () => {
    get.mockReturnValue(new Promise(() => {}))
    const { rerender } = render(<SimulationPanel run={RUN} />)
    expect(screen.queryByText(/Project roll-up/i)).not.toBeInTheDocument()

    rerender(<SimulationPanel run={RUN} projectId={42} />)
    expect(screen.getByText(/Project roll-up/i)).toBeInTheDocument()
  })

  it('downloads the run PDF and the project roll-up via the api client', async () => {
    get.mockReturnValue(new Promise(() => {}))
    download.mockResolvedValue()
    render(<SimulationPanel run={RUN} projectId={42} />)

    fireEvent.click(screen.getByText(/Report PDF/i))
    fireEvent.click(screen.getByText(/Project roll-up/i))

    await waitFor(() => {
      expect(download).toHaveBeenCalledWith('/simulation/runs/abc-123/pdf', 'simulation_abc-123.pdf')
      expect(download).toHaveBeenCalledWith('/simulation/reports/project/42/pdf', 'project_42_simulations.pdf')
    })
  })

  it('surfaces a download failure in the error box', async () => {
    get.mockReturnValue(new Promise(() => {}))
    download.mockRejectedValue(new Error('pdf failed'))
    render(<SimulationPanel run={RUN} />)

    fireEvent.click(screen.getByText(/Report PDF/i))
    expect(await screen.findByText('pdf failed')).toBeInTheDocument()
  })
})
