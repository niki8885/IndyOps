import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

// Mock the heavy Plotly stack. The component does `asFn(factoryModule)` then
// `create(Plotly)`; so the factory module's default must be a function that
// returns a (stub) component. We capture the last props the stub received so we
// can drive its onClick handler and assert on the data-building output.
let lastPlotProps = null
vi.mock('react-plotly.js/factory', () => ({
  default: () => function PlotMock(props) {
    lastPlotProps = props
    return <div data-testid="plot" />
  },
}))
vi.mock('plotly.js-dist-min', () => ({ default: {} }))

import ChainGraph from './ChainGraph'

beforeEach(() => { lastPlotProps = null })

const PLAN = {
  decisions: {
    1: { name: 'Widget', decision: 'make' },
    2: { name: 'Bolt', decision: 'buy', unit_make: 5 },   // has unit_make → BUY colour
    3: { name: 'Ore', decision: 'buy' },                   // no unit_make → LEAF colour
    4: { name: 'Scrap', decision: 'something' },            // falls through → LEAF
  },
  jobs: [
    { type_id: 1, inputs: [{ type_id: 2, qty: 10 }, { type_id: 3, qty: 20 }] },
    // duplicate edge to exercise link aggregation
    { type_id: 1, inputs: [{ type_id: 2, qty: 5 }] },
    // input referencing an unknown id is ignored
    { type_id: 1, inputs: [{ type_id: 999, qty: 1 }] },
  ],
}

describe('ChainGraph', () => {
  it('renders null when the plan has no decisions', () => {
    const { container } = render(<ChainGraph plan={{}} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders the stubbed sankey plot and builds nodes/links from the plan', () => {
    const forceBuy = new Set([4])   // node 4 is force-bought → SKIP colour
    render(<ChainGraph plan={PLAN} forceBuy={forceBuy} onSkip={() => {}} />)

    expect(screen.getByTestId('plot')).toBeInTheDocument()

    const sankey = lastPlotProps.data[0]
    expect(sankey.type).toBe('sankey')
    // labels follow decision order of the id keys
    expect(sankey.node.label).toEqual(['Widget', 'Bolt', 'Ore', 'Scrap'])
    // colours: make / buy-with-unit_make / leaf / forced-skip
    expect(sankey.node.color).toEqual(['#4caf7d', '#3a9bd6', '#5a6178', '#e0884f'])

    // links: two distinct edges (2→1 aggregated to 15, 3→1 = 20); unknown id dropped
    expect(sankey.link.source).toEqual([1, 2])
    expect(sankey.link.target).toEqual([0, 0])
    expect(sankey.link.value).toEqual([15, 20])
  })

  it('accepts forceBuy as a plain array', () => {
    render(<ChainGraph plan={PLAN} forceBuy={[2]} />)
    const sankey = lastPlotProps.data[0]
    // node 2 now SKIP instead of BUY
    expect(sankey.node.color[1]).toBe('#e0884f')
  })

  it('calls onSkip with the type id when a node is clicked', () => {
    const onSkip = vi.fn()
    render(<ChainGraph plan={PLAN} onSkip={onSkip} />)
    // node click: has a label, no link source/target
    lastPlotProps.onClick({ points: [{ label: 'Bolt', pointNumber: 1 }] })
    expect(onSkip).toHaveBeenCalledWith(2)
  })

  it('ignores link clicks (point carries a source)', () => {
    const onSkip = vi.fn()
    render(<ChainGraph plan={PLAN} onSkip={onSkip} />)
    lastPlotProps.onClick({ points: [{ label: 'edge', source: 0, pointNumber: 0 }] })
    lastPlotProps.onClick({ points: [] })   // no point at all
    expect(onSkip).not.toHaveBeenCalled()
  })
})
