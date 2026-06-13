import pandas as pd
import os

ITEMS_CSV = "items.csv"
PRICES_JITA = r"prices/prices_jita.csv"
PRICES_CJ6MT = r"prices/prices_C-J6MT.csv"

def compare_buy_prices_with_shipping(shipping_cost_per_m3=1200):
    # --- Load data ---
    items_df = pd.read_csv(ITEMS_CSV)
    jita_df = pd.read_csv(PRICES_JITA)
    cj6_df = pd.read_csv(PRICES_CJ6MT)

    # --- Keep only latest price per item ---
    if "Timestamp" in jita_df.columns:
        jita_df["Timestamp"] = pd.to_datetime(jita_df["Timestamp"], errors="coerce")
        jita_df = jita_df.sort_values("Timestamp").groupby("Item").tail(1)
    if "Timestamp" in cj6_df.columns:
        cj6_df["Timestamp"] = pd.to_datetime(cj6_df["Timestamp"], errors="coerce")
        cj6_df = cj6_df.sort_values("Timestamp").groupby("Item").tail(1)

    jita_df = jita_df[["Item", "Buy_Max"]].rename(columns={"Buy_Max": "Buy_Jita"})
    cj6_df = cj6_df[["Item", "Buy_Max"]].rename(columns={"Buy_Max": "Buy_CJ6MT"})

    # --- Merge with item data ---
    merged = (
        items_df
        .merge(jita_df, on="Item", how="inner")
        .merge(cj6_df, on="Item", how="inner")
    )

    # --- Calculate shipping & net Jita price ---
    merged["Shipping_Cost"] = merged["Volume"] * shipping_cost_per_m3
    merged["Net_Jita"] = merged["Buy_Jita"] - merged["Shipping_Cost"]

    # --- Compare ---
    merged["Better_Buy_Location"] = merged.apply(
        lambda x: "Buy Locally (C-J6MT)" if x["Buy_CJ6MT"] > x["Net_Jita"] else "Ship from Jita",
        axis=1
    )
    merged["Profit_Difference"] = (merged["Buy_CJ6MT"] - merged["Net_Jita"]).round(2)

    # --- Result table ---
    result = (
        merged[
            [
                "Item",
                "Volume",
                "Buy_Jita",
                "Buy_CJ6MT",
                "Shipping_Cost",
                "Net_Jita",
                "Profit_Difference",
                "Better_Buy_Location",
            ]
        ]
        .sort_values(by="Profit_Difference", ascending=False)
        .reset_index(drop=True)
    )

    pd.set_option("display.float_format", lambda x: f"{x:,.2f}")
    print("\n=== PROFIT COMPARISON (Latest Prices Only) ===")
    print(result.to_string(index=False))

    return result


if __name__ == "__main__":
    compare_buy_prices_with_shipping(shipping_cost_per_m3=1200)
