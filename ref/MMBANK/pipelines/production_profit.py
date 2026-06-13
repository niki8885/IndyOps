from pandas.core.groupby.base import plotting_methods

from MMBANK.prices.request_prices import request_hub_prices
from MMBANK.utils.materials_imput import combine_input
from MMBANK.prices.request_prices import update_csv_with_adjusted_prices
from MMBANK.reactions.reaction_production import calculate_production
from MMBANK.analysis.profit_analysis import production_profit_analysis


def T2_react_full_cycle_profit():
    request_hub_prices(
        input_csv_path="MMBANK/data/items/moon_materials.csv",
        output_csv_path="MMBANK/data/market/jita_moon_materials.csv",
        region_id=10000002
    )
    request_hub_prices(
        input_csv_path="MMBANK/data/items/reactions_comp_1.csv",
        output_csv_path="MMBANK/data/market/jita_reactions_comp_1.csv",
        region_id=10000002
    )
    request_hub_prices(
        input_csv_path="MMBANK/data/items/reactions_comp_2.csv",
        output_csv_path="MMBANK/data/market/jita_reactions_comp_2.csv",
        region_id=10000002
    )

    materials = {
        "MMBANK/data/market/jita_moon_materials.csv": "Buy",
        "MMBANK/data/market/fuel_custom_prices.csv": "Custom"
    }

    output_path = "MMBANK/data/industry/all_prices_T1.csv"
    combine_input(materials, output_path)

    update_csv_with_adjusted_prices('MMBANK/data/industry/all_prices_T1.csv')

    calculate_production(
        input_path="MMBANK/data/BPO/reactions_comp_1_bpo.csv",
        prices_path="MMBANK/data/industry/all_prices_T1.csv",
        output_path="MMBANK/data/industry/production_costs_comp_1.csv",
        ME_structure=0.026,
        ME_BPO=0,
        system_cost_index=0.0493,
        facility_tax=0.02,
        structure_discount=0,
        activity_id=11
    )


    materials = {
        "MMBANK/data/industry/production_costs_comp_1.csv": "Production",
        "MMBANK/data/market/fuel_custom_prices.csv": "Custom"
    }

    output_path = "MMBANK/data/industry/all_prices_T2.csv"
    combine_input(materials, output_path)

    calculate_production(
        input_path="MMBANK/data/BPO/reactions_comp_2_bpo.csv",
        prices_path="MMBANK/data/industry/all_prices_T2.csv",
        output_path="MMBANK/data/industry/production_costs_comp_2.csv",
        ME_structure=0.026,
        ME_BPO=0,
        system_cost_index=0.0493,
        facility_tax=0.02,
        structure_discount=0,
        activity_id=11
    )

    production_profit_analysis(
        production_csv="MMBANK/data/industry/production_costs_comp_2.csv",
        market_csv="MMBANK/data/market/jita_reactions_comp_2.csv",
        output_csv="MMBANK/data/analysis/summary/profit_analysis_T2_reactions_full_cycle.csv",
        top_n=10,
        plot_name="T2_reactions_full_cycle"
    )


def T2_comp_full_cycle_profit(method: str):

    request_hub_prices(
        input_csv_path="MMBANK/data/items/t2_comp.csv",
        output_csv_path="MMBANK/data/market/jita_t2_comp.csv",
        region_id=10000002
    )

    request_hub_prices(
        input_csv_path="MMBANK/data/items/reactions_comp_2.csv",
        output_csv_path="MMBANK/data/market/jita_reactions_comp_2.csv",
        region_id=10000002
    )

    if method == "Buy" or method == "Sell":
        if method == "Buy":

            materials = {
                "MMBANK/data/market/jita_reactions_comp_2.csv": "Buy",
            }

            output_path = "MMBANK/data/industry/all_prices_comp_T2.csv"
            combine_input(materials, output_path)

            update_csv_with_adjusted_prices('MMBANK/data/industry/all_prices_comp_T2.csv')

        elif method == "Sell":

            materials = {
                "MMBANK/data/market/jita_reactions_comp_2.csv": "Sell",
            }

            output_path = "MMBANK/data/industry/all_prices_comp_T2.csv"
            combine_input(materials, output_path)

            update_csv_with_adjusted_prices('MMBANK/data/industry/all_prices_comp_T2.csv')

    elif method == "Full":

        request_hub_prices(
            input_csv_path="MMBANK/data/items/moon_materials.csv",
            output_csv_path="MMBANK/data/market/jita_moon_materials.csv",
            region_id=10000002
        )
        request_hub_prices(
            input_csv_path="MMBANK/data/items/reactions_comp_1.csv",
            output_csv_path="MMBANK/data/market/jita_reactions_comp_1.csv",
            region_id=10000002
        )

        materials = {
            "MMBANK/data/market/jita_moon_materials.csv": "Buy",
            "MMBANK/data/market/fuel_custom_prices.csv": "Custom"
        }

        output_path = "MMBANK/data/industry/all_prices_T1.csv"
        combine_input(materials, output_path)

        update_csv_with_adjusted_prices('MMBANK/data/industry/all_prices_T1.csv')

        calculate_production(
            input_path="MMBANK/data/BPO/reactions_comp_1_bpo.csv",
            prices_path="MMBANK/data/industry/all_prices_T1.csv",
            output_path="MMBANK/data/industry/production_costs_comp_1.csv",
            ME_structure=0.026,
            ME_BPO=0,
            system_cost_index=0.0493,
            facility_tax=0.02,
            structure_discount=0,
            activity_id=11
        )

        materials = {
            "MMBANK/data/industry/production_costs_comp_1.csv": "Production",
            "MMBANK/data/market/fuel_custom_prices.csv": "Custom"
        }

        output_path = "MMBANK/data/industry/all_prices_T2.csv"
        combine_input(materials, output_path)

        calculate_production(
            input_path="MMBANK/data/BPO/reactions_comp_2_bpo.csv",
            prices_path="MMBANK/data/industry/all_prices_T2.csv",
            output_path="MMBANK/data/industry/production_costs_comp_2.csv",
            ME_structure=0.026,
            ME_BPO=0,
            system_cost_index=0.0493,
            facility_tax=0.02,
            structure_discount=0,
            activity_id=11
        )

        materials = {
            "MMBANK/data/industry/production_costs_comp_2.csv": "Production",
        }

        output_path = "MMBANK/data/industry/all_prices_comp_T2.csv"
        combine_input(materials, output_path)

        update_csv_with_adjusted_prices('MMBANK/data/industry/all_prices_comp_T2.csv')

    else:
        raise Exception("Invalid method")

    calculate_production(
        input_path="MMBANK/data/BPO/t2_comp_bpo.csv",
        prices_path="MMBANK/data/industry/all_prices_comp_T2.csv",
        output_path="MMBANK/data/industry/production_costs_T2_comp.csv",
        ME_structure=0.06,
        ME_BPO=0.1,
        system_cost_index=0.0245,
        facility_tax=0.01,
        structure_discount=0.03,
        activity_id=1
    )

    plot_method_name = f"T2_comp_production_method_{method}"

    production_profit_analysis(
        production_csv="MMBANK/data/industry/production_costs_T2_comp.csv",
        market_csv="MMBANK/data/market/jita_t2_comp.csv",
        output_csv="MMBANK/data/analysis/summary/profit_analysis_T2_comp.csv",
        top_n=10,
        plot_name=plot_method_name
    )