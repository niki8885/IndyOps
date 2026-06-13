import requests
import pandas as pd
from time import sleep

REGION_ID = 10000002  # Jita
TOP_N = 10000

ORDERS_URL = f"https://esi.evetech.net/latest/markets/{REGION_ID}/orders/"

orders = []
page = 1
while True:
    r = requests.get(f"{ORDERS_URL}?page={page}")
    if r.status_code != 200:
        break
    data = r.json()
    if not data:
        break
    orders.extend(data)
    page += 1
    sleep(0.1)

print(f"Found {len(orders)} orders")

volume_map = {}
for order in orders:
    type_id = order['type_id']
    volume = order['volume_total']
    volume_map[type_id] = volume_map.get(type_id, 0) + volume

records = []
for i, (type_id, volume) in enumerate(volume_map.items(), 1):
    try:
        r_name = requests.get(f"https://esi.evetech.net/latest/universe/types/{type_id}/")
        name = r_name.json().get("name", "") if r_name.status_code == 200 else ""
        records.append({"name": name, "type_id": type_id, "volume": volume})
    except:
        continue
    if i % 100 == 0:
        print(f"Processed {i}/{len(volume_map)}")
    sleep(0.05)


df = pd.DataFrame(records)
df = df.sort_values("volume", ascending=False).head(TOP_N)
df.to_csv("top_10000_items.csv", index=False)
print("CSV saved as top_10000_items.csv")
