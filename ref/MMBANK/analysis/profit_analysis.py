import os
import pandas as pd
import matplotlib.pyplot as plt


ANAL_DIR = "MMBANK/data/analysis"
os.makedirs(ANAL_DIR, exist_ok=True)
PLOTS_DIR = os.path.join(ANAL_DIR, "plots")


def production_profit_analysis(
        production_csv: str,
        market_csv: str,
        output_csv: str,
        top_n: int = 20,
        plot_name: str = "profit_analysis_plot.png"
):
    prod_df = pd.read_csv(production_csv)
    market_df = pd.read_csv(market_csv)

    df = pd.merge(prod_df, market_df, on="item_id", how="inner", suffixes=('_prod', '_market'))

    df["sell_profit_isk"] = df["sellAvgFivePercent"].astype(float) - df["Total_production_price"].astype(float)
    df["buy_profit_isk"] = df["buyAvgFivePercent"].astype(float) - df["Total_production_price"].astype(float)

    df["sell_margin_percent"] = (df["sell_profit_isk"] / df["Total_production_price"] * 100).fillna(0)
    df["buy_margin_percent"] = (df["buy_profit_isk"] / df["Total_production_price"] * 100).fillna(0)

    df_sorted = df.sort_values(by="sell_margin_percent", ascending=False)
    df_sorted.to_csv(output_csv, index=False)
    top_df = df_sorted.head(top_n)

    plt.style.use('seaborn-v0_8-muted')
    fig, axes = plt.subplots(2, 2, figsize=(20, 14))
    fig.suptitle(f"Profit Analysis: {plot_name} (Top {top_n} by ISK Profit)", fontsize=20,
                 fontweight='bold')

    def style_axis(ax, title, ylabel, color_theme='viridis'):
        ax.set_title(title, fontsize=14, pad=15)
        ax.set_ylabel(ylabel, fontsize=12)
        ax.grid(axis='y', linestyle='--', alpha=0.7)
        ax.tick_params(axis='x', rotation=45, labelsize=10)

    top_df.plot(x="name_prod", y="sell_profit_isk", kind="bar", ax=axes[0, 0], color='seagreen', legend=False)
    style_axis(axes[0, 0], "Absolute Sell Profit (ISK per unit)", "ISK")

    top_df.plot(x="name_prod", y="buy_profit_isk", kind="bar", ax=axes[0, 1], color='steelblue', legend=False)
    style_axis(axes[0, 1], "Absolute Buy Profit (ISK per unit)", "ISK")

    top_df.plot(x="name_prod", y="sell_margin_percent", kind="bar", ax=axes[1, 0], color='mediumseagreen', legend=False)
    style_axis(axes[1, 0], "Sell Margin %", "Percent (%)")

    top_df.plot(x="name_prod", y="buy_margin_percent", kind="bar", ax=axes[1, 1], color='dodgerblue', legend=False)
    style_axis(axes[1, 1], "Buy Margin %", "Percent (%)")

    plt.tight_layout(rect=[0, 0.03, 1, 0.95])

    plot_path = os.path.join(PLOTS_DIR, plot_name)
    plt.savefig(plot_path, dpi=300, bbox_inches='tight')
    print(f"Plot saved to: {plot_path}")

    plt.show()

    print("\nTop products by absolute sell profit:")
    print(top_df[["name_prod", "Total_production_price", "sell_profit_isk", "sell_margin_percent"]].to_string(
        index=False))
