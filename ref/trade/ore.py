import pandas as pd
import requests
import os
import time
from datetime import datetime
from bs4 import BeautifulSoup
import matplotlib.pyplot as plt


ORES_CSV = "ores.csv"
MINERALS_CSV = "minerals.csv"
OUTPUT_DIR = "prices"
REGIONS = ["jita", "C-J6MT"]
BASE_URL = "https://appraise.gnf.lt/item/{}#{}"

os.makedirs(OUTPUT_DIR, exist_ok=True)


def parse_prices_from_page(type_id, region):
    url = BASE_URL.format(type_id, region)
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        tab = soup.find("div", id=region)
        if not tab:
            print(f"[WARN] Region tab {region} not found for item {type_id}")
            return None

        tables = tab.find_all("table")
        if not tables or len(tables) < 2:
            print(f"[WARN] Missing expected tables for {region} item {type_id}")
            return None

        def extract_sell_price(table):
            for row in table.find_all("tr"):
                th = row.find("th")
                td = row.find("td")
                if th and th.text.strip().lower() == "min":
                    val = td.text.strip().replace(",", "").replace(" ISK", "")
                    try:
                        return float(val)
                    except:
                        return None
            return None

        def extract_buy_price(table):
            for row in table.find_all("tr"):
                th = row.find("th")
                td = row.find("td")
                if th and th.text.strip().lower() == "max":
                    val = td.text.strip().replace(",", "").replace(" ISK", "")
                    try:
                        return float(val)
                    except:
                        return None
            return None

        sell_price = extract_sell_price(tables[0])
        buy_price = extract_buy_price(tables[1])

        return {
            "Sell_Min": sell_price,
            "Buy_Max": buy_price
        }

    except Exception as e:
        print(f"[ERROR] Fetch failed for {type_id} ({region}): {e}")
        return None


def fetch_prices(input_csv, name_column, id_column, prefix, region):
    df = pd.read_csv(input_csv)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    output_data = []

    print(f"\n=== Fetching {prefix} prices for region: {region} ===")

    for _, row in df.iterrows():
        item_name = row[name_column]
        type_id = row[id_column]

        if pd.isna(type_id):
            print(f"[SKIP] No Type ID for {item_name}")
            continue

        try:
            type_id = int(type_id)
        except:
            print(f"[SKIP] Invalid Type ID for {item_name}")
            continue

        print(f"→ {item_name} (ID: {type_id})")

        prices = parse_prices_from_page(type_id, region)
        if prices:
            prices.update({
                "Name": item_name,
                "TypeID": type_id,
                "Region": region,
                "Timestamp": timestamp
            })
            output_data.append(prices)

        time.sleep(0.5)

    if output_data:
        df_out = pd.DataFrame(output_data)
        output_file = os.path.join(OUTPUT_DIR, f"{prefix}_min_prices_{region}.csv")
        df_out.to_csv(output_file, index=False)
        print(f"[OK] Saved {len(df_out)} entries → {output_file}")
    else:
        print(f"[WARN] No data collected for {prefix} ({region})")


def get_all_prices():
    for region in REGIONS:
        fetch_prices(ORES_CSV, "Ore Type", "Type ID", "ore", region)
        fetch_prices(MINERALS_CSV, "Mineral", "Type_ID", "mineral", region)
        time.sleep(1)


DELIVERY_COST_PER_M3 = 1200
MIN_PROCESS_QUANTITY = 100


def compare_buy_profit(minerals_csv, jita_csv, cj_csv):
    df_minerals = pd.read_csv(minerals_csv)
    df_jita = pd.read_csv(jita_csv)
    df_cj = pd.read_csv(cj_csv)

    df = df_minerals.merge(df_jita[['Name','Buy_Max']], left_on='Mineral', right_on='Name', how='left')
    df = df.merge(df_cj[['Name','Buy_Max']], left_on='Mineral', right_on='Name', how='left', suffixes=('_Jita','_C_J'))

    df['Total_CJ_to_Jita'] = df['Buy_Max_C_J'] + DELIVERY_COST_PER_M3 * df['Volume']
    df['Total_Jita_to_CJ'] = df['Buy_Max_Jita'] + DELIVERY_COST_PER_M3 * df['Volume']

    df['Profit_CJ_to_Jita'] = df['Buy_Max_Jita'] - df['Total_CJ_to_Jita']
    df['Profit_Jita_to_CJ'] = df['Buy_Max_C_J'] - df['Total_Jita_to_CJ']

    def best_scenario(row):
        if pd.isna(row['Profit_CJ_to_Jita']) or pd.isna(row['Profit_Jita_to_CJ']):
            return "No data"
        if row['Profit_CJ_to_Jita'] > row['Profit_Jita_to_CJ']:
            return "Buy in C-J → Jita"
        else:
            return "Buy in Jita → C-J"

    df['Best_Scenario'] = df.apply(best_scenario, axis=1)

    display_cols = [
        'Mineral','Buy_Max_Jita','Buy_Max_C_J','Volume',
        'Total_CJ_to_Jita','Total_Jita_to_CJ',
        'Profit_CJ_to_Jita','Profit_Jita_to_CJ','Best_Scenario'
    ]
    print(df[display_cols].to_string(index=False))

    plt.figure(figsize=(12,6))
    x = df['Mineral']
    plt.bar(x, df['Profit_CJ_to_Jita'], alpha=0.7, label='CJ → Jita', color='blue')
    plt.bar(x, df['Profit_Jita_to_CJ'], alpha=0.7, label='Jita → CJ', color='orange')
    plt.ylabel("Profit per unit (ISK)")
    plt.title("Profit Scenarios Based on Buy Prices + Delivery")
    plt.xticks(rotation=45)
    plt.axhline(0, color='black', linewidth=0.8)
    plt.legend()
    plt.tight_layout()
    plt.show()



def ores_profit_analysis(ores_csv, minerals_csv, ore_jita_csv, mineral_cj_csv):
    df_ores = pd.read_csv(ores_csv)
    df_minerals = pd.read_csv(minerals_csv)
    df_ore_jita = pd.read_csv(ore_jita_csv)
    df_mineral_cj = pd.read_csv(mineral_cj_csv)

    mineral_map = {
        'Trit': 'Tritanium',
        'Pye': 'Pyerite',
        'Mex': 'Mexallon',
        'Iso': 'Isogen',
        'Nocx': 'Nocxium',
        'Zyd': 'Zydrine',
        'Mega': 'Megacyte',
        'Morph': 'Morphite'
    }

    df_ore_jita.rename(columns={'Ore Type':'Name'}, inplace=True, errors='ignore')
    df_mineral_cj.rename(columns={'Mineral':'Name'}, inplace=True, errors='ignore')

    results = []

    for _, ore in df_ores.iterrows():
        ore_name = ore['Ore Type']
        ore_volume = ore['Compressed m3'] * MIN_PROCESS_QUANTITY

        buy_price_jita_row = df_ore_jita[df_ore_jita['Name'] == ore_name]
        if buy_price_jita_row.empty or pd.isna(buy_price_jita_row['Buy_Max'].values[0]) or buy_price_jita_row['Buy_Max'].values[0] <= 0:
            print(f"[WARN] No valid Buy price in Jita for ore: {ore_name}, skipping")
            continue
        buy_price_jita = buy_price_jita_row['Buy_Max'].values[0]

        cost_ore = (buy_price_jita * MIN_PROCESS_QUANTITY) + (ore_volume * DELIVERY_COST_PER_M3)

        minerals_value_cj = 0
        for mineral_code, mineral_name in mineral_map.items():
            amount = ore.get(mineral_code, 0)
            if amount > 0:
                mineral_row = df_mineral_cj[df_mineral_cj['Name'] == mineral_name]
                if mineral_row.empty or pd.isna(mineral_row['Buy_Max'].values[0]) or mineral_row['Buy_Max'].values[0] <= 0:
                    continue
                sell_price_cj = mineral_row['Buy_Max'].values[0]
                minerals_value_cj += amount * 0.8 * sell_price_cj

        profit = minerals_value_cj - cost_ore

        results.append({
            'Ore': ore_name,
            'Ore_Buy_Cost_Jita': cost_ore,
            'Minerals_Value_CJ': minerals_value_cj,
            'Profit': profit,
            'Profit_per_ore_unit': profit / MIN_PROCESS_QUANTITY,
            'Margin_%': (profit / minerals_value_cj * 100) if minerals_value_cj > 0 else 0,
            'ROI_%': (profit / cost_ore * 100) if cost_ore > 0 else 0,
            'Decision': 'Profitable' if profit > 0 else 'Not profitable'
        })

    if not results:
        print("No valid data to calculate profit. Check ore names and Jita/C-J prices.")
        return

    df_result = pd.DataFrame(results)

    pd.set_option('display.float_format', '{:,.0f}'.format)
    print(df_result.to_string(index=False))

    plt.figure(figsize=(14,6))
    colors = df_result['Profit'].apply(lambda x: 'green' if x>0 else 'red')
    plt.bar(df_result['Ore'], df_result['Profit'], color=colors)
    plt.ylabel('Profit (ISK)')
    plt.title('Profit from buying ore in Jita, transporting & refining in C-J')
    plt.axhline(0, color='black', linewidth=0.8)
    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()
    plt.show()


ores_profit_analysis(
    ores_csv="ores.csv",
    minerals_csv="minerals.csv",
    ore_jita_csv="prices/ore_min_prices_jita.csv",
    mineral_cj_csv="prices/mineral_min_prices_C-J6MT.csv"
)

# compare_buy_profit(
#     minerals_csv="minerals.csv",
#     jita_csv="prices/mineral_min_prices_jita.csv",
#     cj_csv="prices/mineral_min_prices_C-J6MT.csv"
# )

# get_all_prices()
