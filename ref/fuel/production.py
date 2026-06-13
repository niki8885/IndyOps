import pandas as pd
import matplotlib.pyplot as plt
from fuel.storage import calculate_stock

pd.set_option('display.max_rows', None)
pd.set_option('display.max_columns', None)
pd.set_option('display.max_colwidth', None)
pd.set_option('display.width', None)


def calculate_block_costs(usage_df: pd.DataFrame, blocks_count: int = 8000,
                          target: str = "Anyed", method: str = "FIFO",
                          total_job_cost: dict = None, total_blueprint_cost: dict = None) -> pd.DataFrame:
    if total_job_cost is None:
        total_job_cost = {block: 0 for block in usage_df.columns}
    if total_blueprint_cost is None:
        total_blueprint_cost = {block: 0 for block in usage_df.columns}

    stock_df = calculate_stock(target=target, method=method)
    result = []

    for block in usage_df.columns:
        total_materials_cost = 0
        material_costs = {}

        for material, qty in usage_df[block].items():
            if qty == 0:
                continue
            stock_row = stock_df[stock_df["Item"] == material]
            if stock_row.empty:
                raise ValueError(f"Материал '{material}' отсутствует на складе")
            unit_cost = stock_row["Unit Cost"].values[0]
            cost = qty * unit_cost
            total_materials_cost += cost
            material_costs[material] = cost

        job_cost = total_job_cost.get(block, 0)
        blueprint_cost = total_blueprint_cost.get(block, 0)

        result.append({
            "Block": block,
            "Unit Cost": total_materials_cost / blocks_count + job_cost / blocks_count + blueprint_cost / blocks_count,
            "Materials Cost": total_materials_cost / blocks_count,
            "Job Cost": job_cost / blocks_count,
            "Blueprint Cost": blueprint_cost / blocks_count,
            "Total Materials Cost": total_materials_cost,
            "Total Job Cost": job_cost,
            "Total Blueprint Cost": blueprint_cost,
            "Total Cost": total_materials_cost + job_cost + blueprint_cost,
            **{mat: cost / blocks_count for mat, cost in material_costs.items()}
        })

    return pd.DataFrame(result).set_index("Block")


def plot_block_costs_breakdown(block_costs_df: pd.DataFrame):
    blocks = block_costs_df.index.tolist()
    n_blocks = len(blocks)
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    axes = axes.flatten()

    for i, block in enumerate(blocks):
        ax = axes[i]
        row = block_costs_df.loc[block]
        materials = [col for col in block_costs_df.columns
                     if col not in ["Unit Cost", "Materials Cost", "Job Cost",
                                    "Blueprint Cost", "Total Materials Cost",
                                    "Total Job Cost", "Total Blueprint Cost", "Total Cost"]]

        material_values = {mat: row[mat] for mat in materials if row.get(mat, 0) > 0}
        material_values["Job"] = row["Job Cost"]
        material_values["Blueprint"] = row["Blueprint Cost"]

        total = sum(material_values.values())
        threshold = 0.03 * total
        grouped = {k: v for k, v in material_values.items() if v >= threshold}
        other_sum = sum(v for k, v in material_values.items() if v < threshold)
        if other_sum > 0:
            grouped["Other"] = other_sum

        ax.pie(
            grouped.values(),
            labels=grouped.keys(),
            autopct="%1.1f%%",
            startangle=120,
            textprops={'fontsize': 8}
        )
        ax.set_title(f"{block}\n(Unit Cost: {row['Unit Cost']:,.2f})", fontsize=10, fontweight='bold')
        ax.axis('equal')

    for j in range(n_blocks, len(axes)):
        axes[j].axis("off")

    plt.suptitle("Fuel Block Cost Composition per Unit", fontsize=14, fontweight='bold')
    plt.tight_layout(rect=[0, 0, 1, 0.96])
    plt.show()


def print_pretty_df(df: pd.DataFrame, title: str):
    print(f"\n{title}")
    print("=" * 80)
    formatted = df.copy().applymap(lambda x: f"{x:,.2f}" if isinstance(x, (int, float)) else x)
    print(formatted.to_string())
    print("=" * 80 + "\n")


# ---------------------------
# Anyed
# ---------------------------
def anyed_production_cost():
    usage_data = {
        "Helium Fuel Block": [957, 392, 174, 174, 50, 15219, 7392, 870, 19567, 0, 0, 0],
        "Hydrogen Fuel Block": [957, 392, 174, 174, 50, 15219, 7392, 870, 0, 19567, 0, 0],
        "Nitrogen Fuel Block": [957, 392, 174, 174, 50, 15219, 7392, 870, 0, 0, 19567, 0],
        "Oxygen Fuel Block": [957, 392, 174, 174, 50, 15219, 7392, 870, 0, 0, 0, 19567]
    }

    materials = ["Oxygen", "Coolant", "Enriched Uranium", "Mechanical Parts", "Robotics",
                 "Liquid Ozone", "Heavy Water", "Strontium Clathrates", "Helium Isotopes",
                 "Hydrogen Isotopes", "Nitrogen Isotopes", "Oxygen Isotopes"]

    usage_df = pd.DataFrame(usage_data, index=materials)
    job_costs = {
        "Helium Fuel Block": 1_494_531,
        "Hydrogen Fuel Block": 1_610_542,
        "Nitrogen Fuel Block": 1_647_672,
        "Oxygen Fuel Block": 1_629_322
    }
    blueprint_costs = {b: 50_000 for b in usage_df.columns}

    df = calculate_block_costs(usage_df, blocks_count=2000, target="Anyed",
                               total_job_cost=job_costs, total_blueprint_cost=blueprint_costs)
    print_pretty_df(df, "Anyed Production Cost per Block")
    plot_block_costs_breakdown(df)


# ---------------------------
# RYC
# ---------------------------
def ryc_production_cost():
    usage_data = {
        "Helium Fuel Block": [3723, 1523, 677, 677, 200, 59227, 28768, 3385, 76149, 0, 0, 0],
        "Hydrogen Fuel Block": [3723, 1523, 677, 677, 200, 59227, 28768, 3385, 0, 76149, 0, 0],
        "Nitrogen Fuel Block": [3723, 1523, 677, 677, 200, 59227, 28768, 3385, 0, 0, 76149, 0],
        "Oxygen Fuel Block": [3723, 1523, 677, 677, 200, 59227, 28768, 3385, 0, 0, 0, 76149]
    }

    materials = ["Oxygen", "Coolant", "Enriched Uranium", "Mechanical Parts", "Robotics",
                 "Liquid Ozone", "Heavy Water", "Strontium Clathrates", "Helium Isotopes",
                 "Hydrogen Isotopes", "Nitrogen Isotopes", "Oxygen Isotopes"]

    usage_df = pd.DataFrame(usage_data, index=materials)
    job_costs = {
        "Helium Fuel Block": 5_076_420,
        "Hydrogen Fuel Block": 5_470_470,
        "Nitrogen Fuel Block": 5_596_058,
        "Oxygen Fuel Block": 5_534_256
    }
    blueprint_costs = {
        "Helium Fuel Block": 186_361,
        "Hydrogen Fuel Block": 200_827,
        "Nitrogen Fuel Block": 205_437,
        "Oxygen Fuel Block": 203_168
    }

    df = calculate_block_costs(usage_df, blocks_count=8000, target="RYC",
                               total_job_cost=job_costs, total_blueprint_cost=blueprint_costs)
    print_pretty_df(df, "RYC Production Cost per Block")
    plot_block_costs_breakdown(df)


if __name__ == "__main__":
    anyed_production_cost()
    ryc_production_cost()
