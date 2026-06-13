import os
import numpy as np
import pandas as pd
import json
import matplotlib.pyplot as plt
import requests
import time
from MMBANK.utils.bp_request import request_bpo_data_fuzzwork
from MMBANK.prices.request_prices import request_hub_prices
from MMBANK.utils.items_request import *

TEMP_DIR = "MMBANK/temp"
os.makedirs(TEMP_DIR, exist_ok=True)
ANAL_DIR = "MMBANK/data/analysis"
os.makedirs(ANAL_DIR, exist_ok=True)
PLOTS_DIR = os.path.join(ANAL_DIR, "plots")


def production_material_pie(name: str, ME_BPO: float = 0, ME_structure: float = 0, region_id: int = 10000002):
    name_to_id = get_type_ids([name])
    item_id = name_to_id.get(name)
    if not item_id:
        print(f"Error: {name} not found")
        return

    temp_items_csv = os.path.join(TEMP_DIR, "items.csv")
    temp_bpo_csv = os.path.join(TEMP_DIR, "bpo_results.csv")
    temp_prices_csv = os.path.join(TEMP_DIR, "prices.csv")

    volume = get_type_volume(item_id)
    pd.DataFrame([{"name": name, "item_id": item_id, "volume_m3": volume}]).to_csv(temp_items_csv, index=False)

    request_bpo_data_fuzzwork(temp_items_csv, temp_bpo_csv, activity=1)

    try:
        bpo_df = pd.read_csv(temp_bpo_csv)
        materials = json.loads(bpo_df.iloc[0]["materials"])
    except (pd.errors.EmptyDataError, IndexError):
        print(f"Error: No BPO data for {name}")
        return

    mat_list = [{"name": str(m["type_id"]), "item_id": m["type_id"], "volume_m3": 1} for m in materials]
    pd.DataFrame(mat_list).to_csv(temp_prices_csv, index=False)
    request_hub_prices(temp_prices_csv, temp_prices_csv, region_id=region_id)

    prices_df = pd.read_csv(temp_prices_csv)
    price_map = prices_df.set_index("item_id")["sellAvgFivePercent"].to_dict()

    id_to_name = get_type_names([m["type_id"] for m in materials])

    mat_costs = {}
    for mat in materials:
        m_id = mat["type_id"]
        qty_eff = max(1, round(mat["quantity"] * (1 - ME_BPO) * (1 - ME_structure), 0))
        cost = qty_eff * price_map.get(m_id, 0)
        m_name = id_to_name.get(m_id, f"ID {m_id}")
        mat_costs[m_name] = cost

    _draw_and_save_pie(name, mat_costs)


def _draw_and_save_pie(item_name, mat_costs):
    total = sum(mat_costs.values())
    if total == 0: return

    sorted_costs = dict(sorted(mat_costs.items(), key=lambda x: x[1], reverse=True))

    labels, sizes = [], []
    other_sum = 0
    for n, c in sorted_costs.items():
        if c / total >= 0.02:
            labels.append(n)
            sizes.append(c)
        else:
            other_sum += c

    if other_sum > 0:
        labels.append("Other Materials")
        sizes.append(other_sum)

    num_elements = len(sizes)
    colors = plt.get_cmap('tab20')(np.linspace(0, 1, num_elements))

    if "Other Materials" in labels:
        colors[-1] = [0.6, 0.6, 0.6, 1.0]  # Grey

    plt.style.use('ggplot')
    fig, ax = plt.subplots(figsize=(12, 8))

    wedges, texts, autotexts = ax.pie(
        sizes,
        labels=None,
        autopct='%1.1f%%',
        startangle=140,
        pctdistance=0.85,
        textprops=dict(color="w", weight="bold", fontsize=10),
        explode=[0.03] * len(sizes),
        colors=colors
    )

    ax.add_artist(plt.Circle((0, 0), 0.70, fc='white'))

    legend_labels = []
    for i, l in enumerate(labels):
        cost = sizes[i]
        legend_labels.append(f'{l}: {cost:,.0f} ISK')

    ax.legend(wedges, legend_labels, title="Materials & Cost", loc="center left", bbox_to_anchor=(0.9, 0, 0.5, 1))

    ax.set_title(f"Cost Distribution: {item_name}\nTotal: {total:,.2f} ISK", fontsize=16, pad=20)

    safe_name = item_name.replace(" ", "_")
    save_path = os.path.join(PLOTS_DIR, f"{safe_name}_prod_pie_{int(time.time())}.png")
    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.show()