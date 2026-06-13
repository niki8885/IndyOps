import pandas as pd
from datetime import datetime
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick

INVENTORY_CSV = "inventory.csv"
ITEMS_CSV = "items.csv"

pd.set_option('display.max_rows', None)
pd.set_option('display.max_columns', None)
pd.set_option('display.max_colwidth', None)
pd.set_option('display.width', None)


def add_inventory_entry(item, operation, quantity, region, price, target):
    df = pd.read_csv(INVENTORY_CSV)
    items_df = pd.read_csv(ITEMS_CSV)

    item_volume_map = dict(zip(items_df["Item"], items_df["Volume"]))

    today = datetime.today().strftime("%m/%d/%Y")

    #OperationID
    if df.empty:
        operation_id = 1
    else:
        operation_id = df["OperationID"].max() + 1

    # Fees per unit
    volume_per_unit = item_volume_map.get(item, 0)
    if region == "C-J6MT":
        fee_per_unit = 80 * volume_per_unit
    elif region == "Jita" and target == "RYC":
        fee_per_unit = 1280 * volume_per_unit
    else:  # Anyed
        fee_per_unit = 0

    price_per_unit = float(price)
    total_per_unit = price_per_unit + fee_per_unit
    grant_total = total_per_unit * quantity

    new_row = {
        "OperationID": operation_id,
        "Date": today,
        "Item": item,
        "Operation": operation,
        "Quantity": quantity,
        "Region": region,
        "Price": price_per_unit,
        "Fees": fee_per_unit,
        "Volume": volume_per_unit * quantity,
        "Target": target,
        "Total": total_per_unit,
        "Grant Total": grant_total
    }

    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)

    df.to_csv(INVENTORY_CSV, index=False)
    print(f"Added {operation} for {item} on {today}")
    print(df.tail(1))


def calculate_stock(target: str, method: str = "FIFO") -> pd.DataFrame:
    df = pd.read_csv(INVENTORY_CSV)
    df_target = df[df["Target"] == target].copy()

    items = df_target["Item"].unique()
    result_rows = []

    for item in items:
        incoming = df_target[(df_target["Item"] == item) &
                             (df_target["Operation"] == "Incoming goods")].sort_values("Date")
        outgoing = df_target[(df_target["Item"] == item) &
                             (df_target["Operation"] == "Outgoing goods")].sort_values("Date")

        if incoming.empty:
            continue

        if method.upper() == "AVERAGE":
            total_units = incoming["Quantity"].sum()
            avg_price = (incoming["Total"] * incoming["Quantity"]).sum() / total_units
            avg_fees = (incoming["Fees"] * incoming["Quantity"]).sum() / total_units
            unit_cost = avg_price + avg_fees
        else:
            ascending = True if method.upper() == "FIFO" else False
            incoming_sorted = incoming.sort_values("Date", ascending=ascending)
            incoming_list = incoming_sorted[["Quantity", "Total"]].to_dict("records")

            qty_total = outgoing["Quantity"].sum() if not outgoing.empty else 0
            for _, row in outgoing.iterrows():
                qty_needed = row["Quantity"]
                while qty_needed > 0 and incoming_list:
                    batch = incoming_list[0]
                    take_qty = min(batch["Quantity"], qty_needed)
                    batch["Quantity"] -= take_qty
                    qty_needed -= take_qty
                    if batch["Quantity"] == 0:
                        incoming_list.pop(0)

            remaining_qty = sum(batch["Quantity"] for batch in incoming_list)
            if remaining_qty > 0:
                total_cost = sum(batch["Quantity"] * batch["Total"] for batch in incoming_list)
                unit_cost = total_cost / remaining_qty
            else:
                remaining_qty = 0
                unit_cost = 0

        if method.upper() == "AVERAGE":
            remaining_qty = incoming["Quantity"].sum() - outgoing["Quantity"].sum() if not outgoing.empty else incoming[
                "Quantity"].sum()
            remaining_qty = max(remaining_qty, 0)
            unit_cost = unit_cost

        grant_total = remaining_qty * unit_cost
        result_rows.append({
            "Item": item,
            "Quantity": remaining_qty,
            "Unit Cost": unit_cost,
            "Grant Total": grant_total
        })

    result_df = pd.DataFrame(result_rows)
    result_df = result_df.sort_values("Item").reset_index(drop=True)
    result_df.name = f"{target}_{method.upper()}"
    return result_df


def print_pretty_df(df: pd.DataFrame, title: str):
    print(f"\n{title}")
    print("=" * 80)
    formatted = df.copy().applymap(lambda x: f"{x:,.2f}" if isinstance(x, (int, float)) else x)
    print(formatted.to_string())
    print("=" * 80 + "\n")


def plot_stock(stock_df: pd.DataFrame, title: str = None):

    if stock_df.empty:
        print("Пустой DataFrame, нечего отображать.")
        return

    stock_df_sorted = stock_df.sort_values("Grant Total", ascending=False)

    fig, ax1 = plt.subplots(figsize=(12, 8))

    items = stock_df_sorted["Item"]

    ax1.barh(items, stock_df_sorted["Quantity"], color="#4C72B0", label="Quantity")
    ax1.set_xlabel("Quantity", fontsize=11)
    ax1.set_ylabel("Items", fontsize=11)
    ax1.invert_yaxis()

    ax2 = ax1.twiny()
    ax2.plot(stock_df_sorted["Grant Total"], items, "o-", color="#C44E52", label="Grant Total (ISK)")
    ax2.xaxis.set_major_formatter(mtick.FuncFormatter(lambda x, _: f"{x/1_000_000:.1f}M"))
    ax2.set_xlabel("Grant Total (ISK, millions)", fontsize=11, color="#C44E52")
    ax2.tick_params(axis='x', colors="#C44E52")

    title = title or stock_df.name or "Stock Overview"
    plt.title(title, fontsize=14, fontweight="bold", pad=15)

    ax1.legend(loc="upper left")
    ax2.legend(loc="upper right")

    plt.tight_layout()
    plt.show()

Anyed_fifo = calculate_stock(target="Anyed", method="FIFO")
RYC_fifo = calculate_stock(target="RYC", method="FIFO")

print_pretty_df(Anyed_fifo, "Anyed FIFO Stock")
print_pretty_df(RYC_fifo, "RYC FIFO Stock")

plot_stock(Anyed_fifo, title="Anyed FIFO Stock Overview")
plot_stock(RYC_fifo, title="RYC FIFO Stock Overview")
