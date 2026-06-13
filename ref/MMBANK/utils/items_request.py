import requests
import pandas as pd
import time

ESI_BASE = "https://esi.evetech.net/latest"
HEADERS = {"Content-Type": "application/json"}


def get_type_ids(names):
    url = f"{ESI_BASE}/universe/ids/"
    response = requests.post(url, json=names, headers=HEADERS)
    response.raise_for_status()
    data = response.json()
    return {item["name"]: item["id"] for item in data.get("inventory_types", [])}


def get_type_volume(type_id):
    url = f"{ESI_BASE}/universe/types/{type_id}/"
    response = requests.get(url)
    response.raise_for_status()
    return response.json().get("volume")


def request_items_data(input_csv_path, output_csv_path):
    df = pd.read_csv(input_csv_path)

    if "name" not in df.columns:
        raise ValueError("Input should include 'name'")

    names = df["name"].dropna().unique().tolist()

    name_to_id = get_type_ids(names)

    results = []

    for name in names:
        type_id = name_to_id.get(name)
        if type_id is None:
            results.append({
                "name": name,
                "item_id": None,
                "volume_m3": None
            })
            continue

        volume = get_type_volume(type_id)

        results.append({
            "name": name,
            "item_id": type_id,
            "volume_m3": volume
        })

        time.sleep(0.1)

    result_df = pd.DataFrame(results)
    result_df.to_csv(output_csv_path, index=False)


def get_type_names(type_ids):
    if not type_ids:
        return {}

    url = "https://esi.evetech.net/latest/universe/names/"
    clean_ids = list(set(int(tid) for tid in type_ids if pd.notna(tid)))

    response = requests.post(url, json=clean_ids)
    if response.status_code != 200:
        return {tid: str(tid) for tid in clean_ids}

    return {item["id"]: item["name"] for item in response.json()}