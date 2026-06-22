/**
 * Client-side mirror of the backend's haul economics (app/services/trade.haul_eval).
 *
 * The Auto scanner stores all four Jita/C-J corner prices per item, so the UI can
 * re-price any of the four methods live — for a chosen method *or* the best — as the
 * user changes the courier rate, without another server round-trip. Keep this in sync
 * with `haul_eval`: any formula change there must change here.
 */

// method key → [Jita acquire side, C-J sell side]. 'buy' = place a buy order;
// 'sell' = hit existing sell orders (Jita) / list a sell order (C-J).
export const HAUL_METHOD_SIDES = {
  buy_sell:  ['buy', 'sell'],
  buy_buy:   ['buy', 'buy'],
  sell_sell: ['sell', 'sell'],
  sell_buy:  ['sell', 'buy'],
}

/**
 * Per-unit economics of one method for one scanner item, or null if not priceable.
 * `item` carries jita_buy/jita_sell/cj_buy/cj_sell + volume_each (m³/unit).
 * `broker`/`tax` are fractions (e.g. 0.03, 0.045).
 */
export function priceMethod(item, methodKey, courierRate = 0, broker = 0.03, tax = 0.045) {
  const sides = HAUL_METHOD_SIDES[methodKey]
  if (!sides) return null
  const [acqSide, sellSide] = sides
  const acq = acqSide === 'buy' ? item.jita_buy : item.jita_sell
  const rev = sellSide === 'sell' ? item.cj_sell : item.cj_buy
  if (!acq || acq <= 0 || !rev || rev <= 0) return null   // missing leg → method unavailable
  const ship = Math.max((Number(item.volume_each) || 0) * (Number(courierRate) || 0), 0)
  const unitCost = acqSide === 'buy' ? acq * (1 + broker) : acq          // buy order pays broker
  const unitRev = sellSide === 'sell' ? rev * (1 - broker - tax) : rev * (1 - tax)
  const profit = unitRev - unitCost - ship
  const capital = unitCost + ship
  return { method: methodKey, profit, roi: capital > 0 ? profit / capital : 0, transport: ship }
}

/** Best of the four methods by `rankBy` ('profit' | 'roi'), or null if none priceable. */
export function bestMethod(item, courierRate = 0, broker = 0.03, tax = 0.045, rankBy = 'profit') {
  let best = null
  for (const k of Object.keys(HAUL_METHOD_SIDES)) {
    const r = priceMethod(item, k, courierRate, broker, tax)
    if (r && (!best || r[rankBy] > best[rankBy])) best = r
  }
  return best
}

/**
 * Display economics for a method choice ('best' or a specific key). Returns the same
 * `*_disp` shape the scanner table consumes; nulls when the method isn't priceable.
 */
export function resolveMethod(item, methodChoice, courierRate = 0, broker = 0.03, tax = 0.045, rankBy = 'profit') {
  const r = methodChoice === 'best'
    ? bestMethod(item, courierRate, broker, tax, rankBy)
    : priceMethod(item, methodChoice, courierRate, broker, tax)
  return {
    profit_disp: r ? r.profit : null,
    roi_disp: r ? r.roi : null,
    method_disp: r ? r.method : null,
    transport_disp: r ? r.transport : null,
  }
}
