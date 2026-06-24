"""Unit tests for the Tracking income services (pure, no DB/network):
``services.income`` (mission + ratting summaries) and ``services.loot`` (paste
parsing + Jita appraisal)."""
import datetime

from app.services import income, loot


def _dt(day, hour=12):
    return datetime.datetime(2026, 6, day, hour, 0, 0)


# ── income.summarize_missions ──────────────────────────────────────────────────

def test_summarize_missions_totals_and_grouping():
    entries = [
        {"ref_type": "agent_mission_reward", "amount": 500_000.0, "first_party_id": 1, "date": _dt(1)},
        {"ref_type": "agent_mission_time_bonus_reward", "amount": 250_000.0, "first_party_id": 1, "date": _dt(1)},
        {"ref_type": "agent_mission_reward", "amount": 300_000.0, "first_party_id": 2, "date": _dt(2)},
    ]
    s = income.summarize_missions(entries)
    assert s["count"] == 2                       # two main-reward entries
    assert s["main_total"] == 800_000.0
    assert s["bonus_total"] == 250_000.0
    assert s["total"] == 1_050_000.0

    by_agent = {a["agent_id"]: a for a in s["by_agent"]}
    assert by_agent[1]["count"] == 1 and by_agent[1]["total"] == 750_000.0
    assert by_agent[2]["bonus"] == 0.0 and by_agent[2]["total"] == 300_000.0
    # series sorted by day, top agent first in by_agent
    assert [x["date"] for x in s["series"]] == ["2026-06-01", "2026-06-02"]
    assert s["by_agent"][0]["agent_id"] == 1


def test_summarize_missions_ignores_non_mission_refs():
    entries = [{"ref_type": "bounty_prizes", "amount": 9.0, "first_party_id": 5, "date": _dt(1)}]
    s = income.summarize_missions(entries)
    assert s["count"] == 0 and s["total"] == 0.0 and s["by_agent"] == []


# ── income.summarize_ratting ───────────────────────────────────────────────────

def test_summarize_ratting_combines_wallet_and_loot():
    wallet = [
        {"ref_type": "bounty_prizes", "amount": 1_000_000.0, "date": _dt(1)},
        {"ref_type": "ess_escrow_transfer", "amount": 400_000.0, "date": _dt(1)},
        {"ref_type": "bounty_prizes", "amount": 600_000.0, "date": _dt(2)},
    ]
    loot = [{"value_isk": 250_000.0, "date": _dt(1)}, {"value_isk": 50_000.0, "date": _dt(2)}]
    s = income.summarize_ratting(wallet, loot)
    assert s["bounty_total"] == 1_600_000.0
    assert s["ess_total"] == 400_000.0
    assert s["loot_total"] == 300_000.0
    assert s["grand_total"] == 2_300_000.0
    assert s["counts"] == {"bounty": 2, "ess": 1, "loot": 2}
    day1 = next(x for x in s["series"] if x["date"] == "2026-06-01")
    assert day1["total"] == 1_650_000.0


# ── loot.parse_lines ───────────────────────────────────────────────────────────

def test_parse_lines_both_formats_and_warnings():
    rows = loot.parse_lines("Tritanium\t1000\n8\tMegacyte\nGarbageLineNoTab\n")
    assert rows[0] == ("Tritanium", 1000, [])
    assert rows[1] == ("Megacyte", 8, [])
    # the bare line (no tab) is flagged, not silently accepted
    assert rows[2][0] == "" and rows[2][1] == 0 and rows[2][2]


def test_parse_lines_quantity_with_separators():
    rows = loot.parse_lines("Tritanium\t1,000\nNanite Repair Paste\t1 234")
    assert rows[0] == ("Tritanium", 1000, [])
    assert rows[1] == ("Nanite Repair Paste", 1234, [])


# ── loot.appraise ──────────────────────────────────────────────────────────────

def test_appraise_sell_and_buy_bases():
    items = [{"name": "Tritanium", "type_id": 34, "qty": 10},
             {"name": "Mystery", "type_id": None, "qty": 3}]
    prices = {34: {"sell": 5.0, "buy": 4.0}}

    sell = loot.appraise(items, prices, "jita_sell")
    assert sell["total_value"] == 50.0
    assert sell["unpriced"] == ["Mystery"]
    assert sell["items"][0]["unit"] == 5.0 and sell["items"][0]["priced"] is True
    assert sell["items"][1]["priced"] is False

    buy = loot.appraise(items, prices, "jita_buy")
    assert buy["total_value"] == 40.0
    assert buy["basis"] == "jita_buy"
