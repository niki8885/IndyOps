"""
Lay a chain's production jobs out into dependency-ordered **stages**, each capped by
the available manufacturing / reaction slots — so the user can see how the build
actually runs in waves (e.g. 10 manufacturing + 10 reaction slots → stage 1 fills,
stage 2 takes the next, …) and how busy each stage is.

Pure (stdlib only): operates on duck-typed job objects (``type_id``, ``name``,
``slot_kind``, ``runs``, ``time_s`` and ``inputs`` of ``type_id``/``is_make``), so it
is unit-testable without the chain core. See [[indyops-service-layering]].
"""
from __future__ import annotations
from collections import defaultdict


def stage_schedule(jobs, man_slots: int, react_slots: int) -> dict:
    """Greedy list-scheduling of ``jobs`` into stages.

    A job can only enter a stage once every job producing its *make* inputs sits in an
    earlier stage; within a stage at most ``man_slots`` manufacturing + ``react_slots``
    reaction jobs run in parallel, and the overflow spills to the next stage. A slot
    count ``<= 0`` means "no cap" (treated as unlimited) so the schedule never deadlocks.

    Each stage's wall-clock is its longest job (parallel slots); the cumulative time
    sums the stages (they run back to back). Returns a JSON-friendly dict.
    """
    n = len(jobs)
    cap_man = man_slots if man_slots and man_slots > 0 else None
    cap_react = react_slots if react_slots and react_slots > 0 else None

    producers: dict[int, list[int]] = defaultdict(list)
    for i, j in enumerate(jobs):
        producers[j.type_id].append(i)
    deps = [
        {p for inp in j.inputs if inp.is_make for p in producers.get(inp.type_id, [])}
        for j in jobs
    ]

    scheduled: set[int] = set()
    stages: list[dict] = []
    cumulative = 0
    while len(scheduled) < n:
        ready = [i for i in range(n) if i not in scheduled and deps[i] <= scheduled]
        if not ready:                          # dependency cycle / self-ref — release the rest
            ready = [i for i in range(n) if i not in scheduled]

        man_used = react_used = 0
        picked: list[int] = []
        for i in ready:
            if jobs[i].slot_kind == "reaction":
                if cap_react is not None and react_used >= cap_react:
                    continue
                react_used += 1
            else:
                if cap_man is not None and man_used >= cap_man:
                    continue
                man_used += 1
            scheduled.add(i)
            picked.append(i)

        stage_time = max((jobs[i].time_s for i in picked), default=0)
        cumulative += stage_time
        stages.append({
            "stage": len(stages) + 1,
            "man_used": man_used,
            "react_used": react_used,
            "stage_time_s": stage_time,
            "cumulative_s": cumulative,
            "jobs": [
                {"type_id": jobs[i].type_id, "name": jobs[i].name,
                 "slot_kind": jobs[i].slot_kind, "runs": jobs[i].runs, "time_s": jobs[i].time_s}
                for i in picked
            ],
        })

    return {
        "man_slots": man_slots,
        "react_slots": react_slots,
        "stages": stages,
        "total_stages": len(stages),
        "total_time_s": cumulative,
        "peak_man": max((s["man_used"] for s in stages), default=0),
        "peak_react": max((s["react_used"] for s in stages), default=0),
    }
