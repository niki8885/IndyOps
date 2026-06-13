import pandas as pd
import requests
import os
import time
from datetime import datetime
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
import scipy.stats as stats
from bs4 import BeautifulSoup

INPUT_CSV = "items.csv"
OUTPUT_DIR = "prices"
REGIONS = ["C-J6MT", "UALX-3", "jita", "amarr", "dodixie"]
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
            print(f"Region tab {region} not found for item {type_id}")
            return None

        tables = tab.find_all("table")
        if not tables or len(tables) < 2:
            print(f"Missing expected tables for {region} item {type_id}")
            return None

        def extract_table_data(table):
            result = {}
            for row in table.find_all("tr"):
                th = row.find("th")
                td = row.find("td")
                if th and td:
                    key = th.text.strip()
                    val = td.text.strip().replace(",", "").replace(" ISK", "")
                    try:
                        val = float(val)
                    except:
                        val = None
                    result[key] = val
            return result

        sell_data = extract_table_data(tables[0])
        buy_data = extract_table_data(tables[1])

        combined = {}
        for k, v in sell_data.items():
            combined[f"Sell_{k}"] = v
        for k, v in buy_data.items():
            combined[f"Buy_{k}"] = v

        return combined

    except Exception as e:
        print(f"Error fetching {type_id} {region}: {e}")
        return None


def update_prices_for_region(region):
    df_items = pd.read_csv(INPUT_CSV)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    output_data = []

    print(f"\n=== Requesting data for {region} ===")

    for _, row in df_items.iterrows():
        item_name = row["Item"]
        type_id = int(row["ID"])
        print(f"→ {item_name} ({type_id})")

        prices = parse_prices_from_page(type_id, region)
        if prices:
            prices["Item"] = item_name
            prices["TypeID"] = type_id
            prices["Region"] = region
            prices["Timestamp"] = timestamp
            output_data.append(prices)

        time.sleep(0.5)

    if output_data:
        new_df = pd.DataFrame(output_data)

        output_file = os.path.join(OUTPUT_DIR, f"prices_{region}.csv")

        if os.path.exists(output_file):
            old_df = pd.read_csv(output_file)
            combined_df = pd.concat([old_df, new_df], ignore_index=True)
        else:
            combined_df = new_df

        combined_df.to_csv(output_file, index=False)
        print(f"Data saved/appended to {output_file}")
    else:
        print(f"No data collected for {region}")


def get_all_prices():
    for region in REGIONS:
        update_prices_for_region(region)
        time.sleep(1)


def analyze_market_timeline(jita_path: str, cj_path: str, save_dir: str = "market_timeline_analysis"):
    os.makedirs(save_dir, exist_ok=True)
    sns.set(style="whitegrid", context="talk")

    df_jita = pd.read_csv(jita_path)
    df_cj = pd.read_csv(cj_path)

    for df, region in [(df_jita, "Jita"), (df_cj, "C-J6MT")]:
        df["Region"] = region
        df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
        df.sort_values("Timestamp", inplace=True)

    df_all = pd.concat([df_jita, df_cj], ignore_index=True)

    df_all["Sell_Buy_Spread"] = df_all["Sell_Min"] - df_all["Buy_Max"]
    df_all["Sell_Buy_%"] = (df_all["Sell_Buy_Spread"] / df_all["Buy_Max"]) * 100
    df_all["Daily_Change_%"] = df_all.groupby(["Region", "Item"])["Sell_Min"].pct_change() * 100
    df_all["Volatility_7d"] = df_all.groupby(["Region", "Item"])["Sell_Min"].transform(
        lambda x: x.rolling(7, min_periods=2).std()
    )

    merged = pd.merge_asof(
        df_jita.sort_values("Timestamp"),
        df_cj.sort_values("Timestamp"),
        on="Timestamp",
        by="Item",
        suffixes=("_Jita", "_CJ"),
        tolerance=pd.Timedelta("12h"),
        direction="nearest"
    )

    if merged.empty:
        print("No timestamp matches even within tolerance.")
        return None

    merged["Sell_Diff"] = merged["Sell_Min_CJ"] - merged["Sell_Min_Jita"]
    merged["Buy_Diff"] = merged["Buy_Max_CJ"] - merged["Buy_Max_Jita"]

    items = sorted(df_all["Item"].unique())
    n_items = len(items)
    n_cols = 4
    n_rows = int(np.ceil(n_items / n_cols))

    fig, axs = plt.subplots(n_rows, n_cols, figsize=(18, n_rows * 4))
    axs = axs.flatten()
    for i, item in enumerate(items):
        df_item = df_all[df_all["Item"] == item]
        for region, color in [("Jita", "blue"), ("C-J6MT", "red")]:
            data = df_item[df_item["Region"] == region]["Sell_Min"].dropna()
            if len(data) == 0:
                continue
            sns.lineplot(ax=axs[i], x=range(len(data)), y=data.values, color=color, label=region)
        axs[i].set_title(item)
        axs[i].set_ylabel("Sell_Min (ISK)")
        axs[i].set_xlabel("Time index")
        axs[i].legend()
    for j in range(i+1, len(axs)):
        axs[j].axis("off")
    plt.tight_layout()
    plt.savefig(os.path.join(save_dir, "average_sell_price_grid.png"))
    plt.close()

    fig, axs = plt.subplots(n_rows, n_cols, figsize=(18, n_rows * 4))
    axs = axs.flatten()
    for i, item in enumerate(items):
        df_item = df_all[df_all["Item"] == item]
        for region, color in [("Jita", "blue"), ("C-J6MT", "red")]:
            data = df_item[df_item["Region"] == region]["Buy_Max"].dropna()
            if len(data) == 0:
                continue
            sns.lineplot(ax=axs[i], x=range(len(data)), y=data.values, color=color, label=region)
        axs[i].set_title(item)
        axs[i].set_ylabel("Buy_Max (ISK)")
        axs[i].set_xlabel("Time index")
        axs[i].legend()
    for j in range(i+1, len(axs)):
        axs[j].axis("off")
    plt.tight_layout()
    plt.savefig(os.path.join(save_dir, "average_buy_price_grid.png"))
    plt.close()

    fig, axs = plt.subplots(n_rows, n_cols, figsize=(18, n_rows * 4))
    axs = axs.flatten()
    for i, item in enumerate(items):
        df_item = df_all[df_all["Item"] == item]
        for region, color in [("Jita", "blue"), ("C-J6MT", "red")]:
            data = df_item[df_item["Region"] == region]["Sell_Min"].dropna()
            if len(data) == 0:
                continue
            if data.nunique() > 1:
                sns.kdeplot(data, ax=axs[i], color=color, fill=True, alpha=0.3, label=region, warn_singular=False)
            else:
                axs[i].axvline(data.mean(), color=color, linestyle="--", label=f"{region}: {data.mean():.0f}")
        axs[i].set_title(item)
        axs[i].set_xlabel("Sell_Min (ISK)")
        axs[i].set_ylabel("Density")
        axs[i].legend()
    for j in range(i+1, len(axs)):
        axs[j].axis("off")
    plt.tight_layout()
    plt.savefig(os.path.join(save_dir, "distribution_grid.png"))
    plt.close()

    fig, axs = plt.subplots(n_rows, n_cols, figsize=(18, n_rows * 4))
    axs = axs.flatten()
    for i, item in enumerate(items):
        df_item_jita = df_jita[df_jita["Item"] == item]["Sell_Min"].dropna()
        df_item_cj = df_cj[df_cj["Item"] == item]["Sell_Min"].dropna()
        min_len = min(len(df_item_jita), len(df_item_cj))
        if min_len < 2:
            axs[i].text(0.5, 0.5, "Not enough data", ha="center", va="center")
            continue
        stats.probplot(df_item_jita.iloc[:min_len], dist="norm", plot=axs[i])
        axs[i].set_title(item)
    for j in range(i+1, len(axs)):
        axs[j].axis("off")
    plt.tight_layout()
    plt.savefig(os.path.join(save_dir, "qqplot_grid.png"))
    plt.close()

    fig, axs = plt.subplots(n_rows, n_cols, figsize=(18, n_rows * 4))
    axs = axs.flatten()
    for i, item in enumerate(items):
        df_item = df_all[df_all["Item"] == item]
        for region, color in [("Jita", "blue"), ("C-J6MT", "red")]:
            data = df_item[df_item["Region"] == region]["Sell_Buy_Spread"].dropna()
            if len(data) == 0:
                continue
            sns.lineplot(ax=axs[i], x=range(len(data)), y=data.values, color=color, label=region)
        axs[i].set_title(item)
        axs[i].set_xlabel("Time index")
        axs[i].set_ylabel("Spread (ISK)")
        axs[i].legend()
    for j in range(i+1, len(axs)):
        axs[j].axis("off")
    plt.tight_layout()
    plt.savefig(os.path.join(save_dir, "spread_grid.png"))
    plt.close()

    corr_data = merged.pivot_table(index="Timestamp", columns="Item",
                                   values=["Sell_Min_Jita", "Sell_Min_CJ"]).dropna()
    corr_jita = corr_data["Sell_Min_Jita"].corr()
    corr_cj = corr_data["Sell_Min_CJ"].corr()

    plt.figure(figsize=(12, 10))
    sns.heatmap(corr_jita, cmap="coolwarm", annot=False, square=True)
    plt.title("Item-to-Item Correlation (Jita Sell_Min, pearson)")
    plt.xticks(rotation=45, ha="right")
    plt.yticks(rotation=0)
    plt.tight_layout()
    plt.savefig(os.path.join(save_dir, "correlation_matrix_jita.png"))
    plt.close()

    plt.figure(figsize=(12, 10))
    sns.heatmap(corr_cj, cmap="coolwarm", annot=False, square=True)
    plt.title("Item-to-Item Correlation (C-J6MT Sell_Min, pearson)")
    plt.xticks(rotation=45, ha="right")
    plt.yticks(rotation=0)
    plt.tight_layout()
    plt.savefig(os.path.join(save_dir, "correlation_matrix_cj.png"))
    plt.close()

    merged.to_csv(os.path.join(save_dir, "region_comparison_timeline.csv"), index=False)
    df_all.to_csv(os.path.join(save_dir, "full_timeseries.csv"), index=False)

    print(f"Market analysis complete. Results saved to: {save_dir}")

    return {
        "merged": merged,
        "full_data": df_all,
        "corr_jita": corr_jita,
        "corr_cj": corr_cj
    }


if __name__ == "__main__":
    get_all_prices()
    result = analyze_market_timeline(
        jita_path="prices/prices_jita.csv",
        cj_path="prices/prices_C-J6MT.csv"
    )