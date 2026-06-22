import { describe, it, expect } from 'vitest'
import { priceMethod, bestMethod, resolveMethod } from './haulPricing'

// A profitable item: buy cheap in Jita, sell rich at C-J. Small volume so courier is minor.
const ITEM = {
  jita_buy: 1_000_000, jita_sell: 1_100_000,
  cj_buy: 1_400_000, cj_sell: 1_500_000,
  volume_each: 10,
}

describe('haulPricing.priceMethod', () => {
  it('prices sell→buy (instant both legs): no broker, tax on sale', () => {
    // acquire from Jita sell (1.1M, no fee), dump to C-J buy (1.4M − 4.5% tax), ship 10×1200.
    const r = priceMethod(ITEM, 'sell_buy', 1200, 0.03, 0.045)
    const expectedRev = 1_400_000 * (1 - 0.045)
    const expectedProfit = expectedRev - 1_100_000 - 10 * 1200
    expect(r.profit).toBeCloseTo(expectedProfit, 2)
    expect(r.method).toBe('sell_buy')
  })

  it('prices buy→sell (patient both legs): broker on buy + broker+tax on sale', () => {
    const r = priceMethod(ITEM, 'buy_sell', 1200, 0.03, 0.045)
    const cost = 1_000_000 * (1 + 0.03)
    const rev = 1_500_000 * (1 - 0.03 - 0.045)
    const expectedProfit = rev - cost - 10 * 1200
    expect(r.profit).toBeCloseTo(expectedProfit, 2)
  })

  it('returns null when a required leg price is missing', () => {
    expect(priceMethod({ ...ITEM, cj_sell: null }, 'sell_sell')).toBeNull()
    expect(priceMethod({ ...ITEM, jita_buy: 0 }, 'buy_buy')).toBeNull()
  })

  it('higher courier rate lowers profit', () => {
    const cheap = priceMethod(ITEM, 'sell_buy', 0)
    const dear = priceMethod(ITEM, 'sell_buy', 5000)
    expect(dear.profit).toBeLessThan(cheap.profit)
  })
})

describe('haulPricing.bestMethod', () => {
  it('buy→sell yields the highest profit here and is chosen as best', () => {
    const best = bestMethod(ITEM, 1200, 0.03, 0.045, 'profit')
    expect(best.method).toBe('buy_sell')          // cheapest acquire × richest sale
  })

  it('can rank by roi instead of profit', () => {
    const best = bestMethod(ITEM, 1200, 0.03, 0.045, 'roi')
    expect(best).toHaveProperty('roi')
    expect(best.roi).toBeGreaterThan(0)
  })
})

describe('haulPricing.resolveMethod', () => {
  it('"best" resolves to a concrete method with disp fields', () => {
    const d = resolveMethod(ITEM, 'best', 1200, 0.03, 0.045, 'profit')
    expect(d.method_disp).toBe('buy_sell')
    expect(d.profit_disp).toBeGreaterThan(0)
    expect(d.roi_disp).toBeGreaterThan(0)
  })

  it('an explicit unpriceable method yields null disp fields (row gets filtered out)', () => {
    const d = resolveMethod({ ...ITEM, cj_buy: null }, 'sell_buy')
    expect(d).toEqual({ profit_disp: null, roi_disp: null, method_disp: null, transport_disp: null })
  })
})
