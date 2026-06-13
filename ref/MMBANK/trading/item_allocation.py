import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

pd.set_option("display.max_columns", None)
pd.set_option("display.max_rows", None)
pd.set_option("display.width", None)
pd.set_option("display.max_colwidth", None)


class Strategy:
    def __init__(self, name, price, demand_rate):
        self.name = name
        self.price = price
        self.demand_rate = demand_rate


def simulate_strategy(strategy, initial_inventory, unit_cost, holding_cost, discount_rate, horizon, n_simulations=1000,
                      seed=28):
    rng = np.random.default_rng(seed)
    profits = []

    for _ in range(n_simulations):
        inventory = initial_inventory
        total_profit = 0.0

        for t in range(horizon):
            demand = rng.poisson(strategy.demand_rate)
            sales = min(demand, inventory)
            inventory -= sales

            margin = strategy.price - unit_cost
            reward = (margin * sales) - (holding_cost * inventory)

            discounted_reward = reward * np.exp(-discount_rate * t)
            total_profit += discounted_reward

            if inventory <= 0:
                break
        profits.append(total_profit)

    return {
        "strategy": strategy.name,
        "expected_profit": np.mean(profits),
        "profit_std": np.std(profits),
        "expected_time_to_sellout": estimate_time_to_sellout(strategy.demand_rate, initial_inventory)
    }


def estimate_time_to_sellout(demand_rate, inventory):
    if demand_rate == 0: return np.inf
    return inventory / demand_rate


def simulate_allocation(strategies, allocations, initial_inventory, unit_cost, holding_cost, discount_rate, horizon,
                        n_simulations=300):
    total_profits = []
    assigned_inventories = np.floor(np.array(allocations) * initial_inventory)

    for _ in range(n_simulations):
        total_profit = 0.0
        for i, strat in enumerate(strategies):
            if assigned_inventories[i] <= 0:
                continue

            res = simulate_strategy(
                strategy=strat,
                initial_inventory=int(assigned_inventories[i]),
                unit_cost=unit_cost,
                holding_cost=holding_cost,
                discount_rate=discount_rate,
                horizon=horizon,
                n_simulations=1
            )
            total_profit += res["expected_profit"]
        total_profits.append(total_profit)

    return {
        "expected_profit": np.mean(total_profits),
        "profit_std": np.std(total_profits)
    }


def optimize_allocation_mc(strategies, initial_inventory, unit_cost, holding_cost, discount_rate, horizon, step=0.1):
    best = None
    for x1 in np.linspace(0, 1, int(1 / step) + 1):
        for x2 in np.linspace(0, 1 - x1, int((1 - x1) / step) + 1 if (1 - x1) > 0 else 1):
            x3 = max(0, 1 - x1 - x2)
            allocations = [x1, x2, x3]

            res = simulate_allocation(
                strategies, allocations, initial_inventory,
                unit_cost, holding_cost, discount_rate, horizon
            )

            if best is None or res["expected_profit"] > best["expected_profit"]:
                best = {
                    "allocations": allocations,
                    "expected_profit": res["expected_profit"],
                    "profit_std": res["profit_std"]
                }
    return best


def simulate_profit_path(strategy, initial_inventory, unit_cost, holding_cost, discount_rate, horizon, seed=None):
    rng = np.random.default_rng(seed)
    inventory = initial_inventory
    cumulative_profit = 0.0
    profit_path = []

    for t in range(horizon):
        demand = rng.poisson(strategy.demand_rate)
        sales = min(demand, inventory)
        inventory -= sales
        reward = ((strategy.price - unit_cost) * sales) - (holding_cost * inventory)
        cumulative_profit += reward * np.exp(-discount_rate * t)
        profit_path.append(cumulative_profit)
        if inventory <= 0:
            profit_path.extend([cumulative_profit] * (horizon - t - 1))
            break
    return np.array(profit_path)


def monte_carlo_with_ci(strategy, initial_inventory, unit_cost, holding_cost, discount_rate, horizon,
                        n_simulations=500):
    paths = [simulate_profit_path(strategy, initial_inventory, unit_cost, holding_cost, discount_rate, horizon, seed=i)
             for i in range(n_simulations)]
    paths = np.array(paths)
    mean_path = paths.mean(axis=0)
    std_path = paths.std(axis=0)
    ci_low = mean_path - 1.96 * std_path / np.sqrt(n_simulations)
    ci_high = mean_path + 1.96 * std_path / np.sqrt(n_simulations)
    return mean_path, ci_low, ci_high


def plot_profit_ci(mean, low, high, title):
    plt.figure(figsize=(10, 5))
    plt.plot(mean, label="Expected profit", color='blue')
    plt.fill_between(range(len(mean)), low, high, alpha=0.2, color='blue', label="95% CI")
    plt.title(title)
    plt.xlabel("Days")
    plt.ylabel("Discounted Profit (ISK)")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.show()


if __name__ == "__main__":
    item_name = '250mm Light Artillery Cannon II'
    initial_inventory = 1000
    unit_cost = 458000
    holding_cost = 0.00666 * unit_cost
    discount_rate = 0.0066
    horizon = 60

    strategies = [
        Strategy("Fast / Low margin", price=659000, demand_rate=100),
        Strategy("Instant / Medium margin", price=594000, demand_rate=400),
        Strategy("Slow / High margin", price=993000, demand_rate=10),
    ]

    print(f"--- Comparison of Individual Strategies for {item_name} ---")
    results = [simulate_strategy(s, initial_inventory, unit_cost, holding_cost, discount_rate, horizon) for s in
               strategies]
    df = pd.DataFrame(results)
    print(df.sort_values("expected_profit", ascending=False))
    print("\n" + "=" * 50 + "\n")

    print("Optimizing Mixed Allocation (Finding the best split)...")
    best_mix = optimize_allocation_mc(strategies, initial_inventory, unit_cost, holding_cost, discount_rate, horizon)

    print("\n--- RECOMMENDED STRATEGY ---")
    for i, strat in enumerate(strategies):
        units = int(best_mix['allocations'][i] * initial_inventory)
        print(f"Strategy: {strat.name:<25} | Allocate: {units:>4} units ({best_mix['allocations'][i] * 100:>3.0f}%)")

    print(f"\nExpected Total Profit: {best_mix['expected_profit']:,.2f} ISK")
    print(f"Risk (Std Dev): {best_mix['profit_std']:,.2f} ISK")

    for strat in strategies:
        mean, low, high = monte_carlo_with_ci(strat, initial_inventory, unit_cost, holding_cost, discount_rate, horizon)
        plot_profit_ci(mean, low, high, title=f"{item_name} Performance: {strat.name}")