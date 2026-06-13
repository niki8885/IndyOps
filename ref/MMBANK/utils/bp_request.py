import pandas as pd
import json


def request_bpo_data_fuzzwork(
    items_csv: str,
    output_csv: str,
    products_csv: str = "MMBANK/data/fuzzwork/industryActivityProducts.csv",
    materials_csv: str = "MMBANK/data/fuzzwork/industryActivityMaterials.csv",
    activity_csv: str = "MMBANK/data/fuzzwork/industryActivity.csv",
    activity: int = 1
):
    items_df = pd.read_csv(items_csv)
    products_df = pd.read_csv(products_csv)
    materials_df = pd.read_csv(materials_csv)
    activity_df = pd.read_csv(activity_csv)

    products_df = products_df[products_df["activityID"] == activity]
    materials_df = materials_df[materials_df["activityID"] == activity]
    activity_df = activity_df[activity_df["activityID"] == activity]

    product_to_bpo = products_df.set_index("productTypeID")["typeID"].to_dict()

    materials_grouped = (
        materials_df.groupby("typeID")
        .apply(
            lambda x: x[["materialTypeID", "quantity"]]
            .rename(columns={"materialTypeID": "type_id", "quantity": "quantity"})
            .to_dict(orient="records")
        )
        .to_dict()
    )

    quantity_map = products_df.set_index("typeID")["quantity"].to_dict()

    time_map = activity_df.set_index("typeID")["time"].to_dict()

    rows = []

    for _, row in items_df.iterrows():
        item_id = int(row["item_id"])
        bpo_id = product_to_bpo.get(item_id)

        if bpo_id is None:
            continue

        rows.append({
            "name": row["name"],
            "item_id": item_id,
            "volume_m3": row["volume_m3"],
            "BPO_name": None,
            "BPO_id": bpo_id,
            "materials": json.dumps(materials_grouped.get(bpo_id, [])),
            "base_time": time_map.get(bpo_id),
            "quantity": quantity_map.get(bpo_id, 1)
        })

    pd.DataFrame(rows).to_csv(output_csv, index=False)
