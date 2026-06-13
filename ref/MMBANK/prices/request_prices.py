import requests
import pandas as pd
import time

EVETYCOON_BASE = "https://evetycoon.com/api/v1/market/stats"


def get_market_stats(region_id: int, type_id: int) -> dict | None:
    url = f"{EVETYCOON_BASE}/{region_id}/{type_id}"
    response = requests.get(url, timeout=15)

    if response.status_code != 200:
        return None

    return response.json()


def request_hub_prices(
    input_csv_path: str,
    output_csv_path: str,
    region_id: int,
    sleep_sec: float = 0.15
):
    df = pd.read_csv(input_csv_path)

    required_cols = {"name", "item_id", "volume_m3"}
    if not required_cols.issubset(df.columns):
        raise ValueError(f"Input CSV must contain columns: {required_cols}")

    results = []

    for _, row in df.iterrows():
        name = row["name"]
        type_id = row["item_id"]
        volume_m3 = row["volume_m3"]

        if pd.isna(type_id):
            results.append({
                "name": name,
                "item_id": None,
                "volume_m3": volume_m3,
                "buyVolume": None,
                "sellVolume": None,
                "buyOrders": None,
                "sellOrders": None,
                "sellOutliers": None,
                "buyOutliers": None,
                "buyThreshold": None,
                "sellThreshold": None,
                "buyAvgFivePercent": None,
                "sellAvgFivePercent": None,
            })
            continue

        stats = get_market_stats(region_id, int(type_id))

        if stats is None:
            time.sleep(sleep_sec)
            continue

        results.append({
            "name": name,
            "item_id": type_id,
            "volume_m3": volume_m3,
            "buyVolume": stats.get("buyVolume"),
            "sellVolume": stats.get("sellVolume"),
            "buyOrders": stats.get("buyOrders"),
            "sellOrders": stats.get("sellOrders"),
            "sellOutliers": stats.get("sellOutliers"),
            "buyOutliers": stats.get("buyOutliers"),
            "buyThreshold": stats.get("buyThreshold"),
            "sellThreshold": stats.get("sellThreshold"),
            "buyAvgFivePercent": stats.get("buyAvgFivePercent"),
            "sellAvgFivePercent": stats.get("sellAvgFivePercent"),
        })

        time.sleep(sleep_sec)

    result_df = pd.DataFrame(results)
    result_df.to_csv(output_csv_path, index=False)


def update_csv_with_adjusted_prices(csv_path: str):
    url = "https://esi.evetech.net/latest/markets/prices/?datasource=tranquility"
    response = requests.get(url)

    if response.status_code != 200:
        print(f"Error: {response.status_code}")
        return

    api_prices = response.json()
    adj_price_map = {item['type_id']: item.get('adjusted_price', 0) for item in api_prices}

    df = pd.read_csv(csv_path)

    df['adjusted_price'] = df['item_id'].map(adj_price_map).fillna(0)

    df.to_csv(csv_path, index=False)

    return adj_price_map

