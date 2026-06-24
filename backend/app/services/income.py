"""Pure aggregation for the Tracking income ledgers (Mission + Ratting).

Operates on already-filtered plain dict rows (the router does the SQL filtering by
character + date + ref_type) so this stays pure stdlib and trivially testable. See
[[indyops-service-layering]].

Mission rewards come from the wallet journal as two ref_types: ``agent_mission_reward``
(the main reward) and ``agent_mission_time_bonus_reward`` (the time bonus). The journal
does not carry the mission *name*, only the agent (``first_party_id``); a "mission" is
counted as one main-reward entry. Ratting income is ``bounty_prizes`` (NPC bounties) +
``ess_escrow_transfer`` (ESS payouts), plus user-pasted loot value.
"""
from __future__ import annotations
from typing import Optional

MAIN_REWARD = "agent_mission_reward"
BONUS_REWARD = "agent_mission_time_bonus_reward"
BOUNTY = "bounty_prizes"
ESS = "ess_escrow_transfer"

MISSION_REF_TYPES = (MAIN_REWARD, BONUS_REWARD)
RATTING_REF_TYPES = (BOUNTY, ESS)


def _day(value) -> Optional[str]:
    """ISO date (``YYYY-MM-DD``) of a datetime, or None."""
    return value.date().isoformat() if value is not None else None


def summarize_missions(entries: list[dict]) -> dict:
    """Summarize mission-reward journal entries.

    ``entries`` are dicts with ``ref_type``, ``amount``, ``date`` (datetime|None) and
    ``first_party_id`` (the agent). Returns totals, a per-agent breakdown and a per-day
    series. ``count`` is the number of main-reward entries (≈ missions completed)."""
    main_total = bonus_total = 0.0
    count = 0
    by_agent: dict = {}
    series: dict = {}

    for e in entries:
        rt = e.get("ref_type")
        amt = e.get("amount") or 0.0
        agent = e.get("first_party_id")
        is_main = rt == MAIN_REWARD
        is_bonus = rt == BONUS_REWARD
        if not (is_main or is_bonus):
            continue

        if is_main:
            count += 1
            main_total += amt
        else:
            bonus_total += amt

        a = by_agent.setdefault(agent, {"agent_id": agent, "count": 0,
                                        "main": 0.0, "bonus": 0.0, "total": 0.0})
        if is_main:
            a["count"] += 1
            a["main"] += amt
        else:
            a["bonus"] += amt
        a["total"] += amt

        day = _day(e.get("date"))
        if day:
            s = series.setdefault(day, {"date": day, "main": 0.0, "bonus": 0.0, "total": 0.0})
            if is_main:
                s["main"] += amt
            else:
                s["bonus"] += amt
            s["total"] += amt

    for a in by_agent.values():
        for k in ("main", "bonus", "total"):
            a[k] = round(a[k], 2)
    for s in series.values():
        for k in ("main", "bonus", "total"):
            s[k] = round(s[k], 2)

    return {
        "count": count,
        "main_total": round(main_total, 2),
        "bonus_total": round(bonus_total, 2),
        "total": round(main_total + bonus_total, 2),
        "by_agent": sorted(by_agent.values(), key=lambda x: x["total"], reverse=True),
        "series": sorted(series.values(), key=lambda x: x["date"]),
    }


def summarize_ratting(wallet_entries: list[dict], loot_rows: list[dict]) -> dict:
    """Summarize ratting income: bounty + ESS journal entries plus saved loot value.

    ``wallet_entries`` are dicts with ``ref_type`` (``bounty_prizes``/``ess_escrow_transfer``),
    ``amount`` and ``date``. ``loot_rows`` are dicts with ``value_isk`` and ``date``.
    Returns per-source totals, the grand total, counts and a per-day series."""
    bounty_total = ess_total = loot_total = 0.0
    counts = {"bounty": 0, "ess": 0, "loot": 0}
    series: dict = {}

    def bucket(day):
        return series.setdefault(day, {"date": day, "bounty": 0.0, "ess": 0.0,
                                       "loot": 0.0, "total": 0.0})

    for e in wallet_entries:
        rt = e.get("ref_type")
        amt = e.get("amount") or 0.0
        day = _day(e.get("date"))
        if rt == BOUNTY:
            bounty_total += amt
            counts["bounty"] += 1
            if day:
                b = bucket(day); b["bounty"] += amt; b["total"] += amt
        elif rt == ESS:
            ess_total += amt
            counts["ess"] += 1
            if day:
                b = bucket(day); b["ess"] += amt; b["total"] += amt

    for l in loot_rows:
        amt = l.get("value_isk") or 0.0
        loot_total += amt
        counts["loot"] += 1
        day = _day(l.get("date"))
        if day:
            b = bucket(day); b["loot"] += amt; b["total"] += amt

    for s in series.values():
        for k in ("bounty", "ess", "loot", "total"):
            s[k] = round(s[k], 2)

    return {
        "bounty_total": round(bounty_total, 2),
        "ess_total": round(ess_total, 2),
        "loot_total": round(loot_total, 2),
        "grand_total": round(bounty_total + ess_total + loot_total, 2),
        "counts": counts,
        "series": sorted(series.values(), key=lambda x: x["date"]),
    }
