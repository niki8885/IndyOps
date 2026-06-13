import pandas as pd
import json


def calculate_production(
        input_path: str,
        prices_path: str,
        output_path: str,
        ME_structure: float = 0,
        ME_BPO: float = 0,
        system_cost_index: float = 0,
        facility_tax: float = 0,
        scc_tax: float = 0.04,
        structure_discount: float = 0.05,
        activity_id: int = 1,
):
    df = pd.read_csv(input_path)
    prices_df = pd.read_csv(prices_path)

    market_price_map = prices_df.set_index("item_id")["price"].to_dict()
    adj_price_map = prices_df.set_index("item_id").get("adjusted_price", prices_df.set_index("item_id")["price"]).to_dict()

    rows = []

    for _, row in df.iterrows():
        try:
            materials = json.loads(row["materials"])
            quantity = row.get("quantity", 1)
        except (json.JSONDecodeError, TypeError):
            continue

        is_reaction = (activity_id == 11)

        material_cost = 0.0
        base_job_value_eiv = 0.0

        for mat in materials:
            mat_id = mat["type_id"]
            qty_base = mat["quantity"]

            m_price = market_price_map.get(mat_id, 0)
            a_price = adj_price_map.get(mat_id, 0)

            if is_reaction:
                qty_eff = qty_base
            else:
                qty_eff = max(1, round(qty_base * (1 - ME_BPO) * (1 - ME_structure), 0))

            material_cost += qty_eff * m_price
            base_job_value_eiv += qty_base * a_price

        job_gross_rate = system_cost_index * (1 - structure_discount)
        total_tax_rate = facility_tax + scc_tax

        job_cost = base_job_value_eiv * (job_gross_rate + total_tax_rate)
        total_price = material_cost + job_cost

        if quantity <= 0:
            quantity = 1

        rows.append({
            "name": row["name"],
            "item_id": row["item_id"],
            "EIV_value": round(base_job_value_eiv / quantity, 2),
            "Material_cost": round(material_cost / quantity, 2),
            "Job_cost": round(job_cost / quantity, 2),
            "Total_production_price": round(total_price / quantity, 2),
        })

    result_df = pd.DataFrame(rows)
    result_df.to_csv(output_path, index=False)
