import pandas as pd


METHOD_TO_COLUMN = {
    "Buy": "buyAvgFivePercent",
    "Sell": "sellAvgFivePercent",
    "Production": "Total_production_price",
    "Custom": "Price",
}


def combine_input(materials: dict, output_path: str) -> pd.DataFrame:
    frames = []

    for csv_path, method in materials.items():
        if method not in METHOD_TO_COLUMN:
            raise ValueError(f"Unknown pricing method: {method}")

        price_column = METHOD_TO_COLUMN[method]

        df = pd.read_csv(csv_path)

        required = {"name", "item_id", price_column}
        if not required.issubset(df.columns):
            raise ValueError(
                f"{csv_path} must contain columns {required}"
            )

        tmp = (
            df[["name", "item_id", price_column]]
            .rename(columns={price_column: "price"})
        )

        frames.append(tmp)

    all_materials = (
        pd.concat(frames, ignore_index=True)
        .dropna(subset=["price"])
        .drop_duplicates(subset=["item_id"], keep="last")
    )

    all_materials.to_csv(output_path, index=False)

    return all_materials

