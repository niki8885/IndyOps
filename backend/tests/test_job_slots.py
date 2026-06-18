"""Tests for industry job-slot capacity + usage (services/skills)."""
from app.services import skills


def test_job_slots_base_with_no_skills():
    s = skills.job_slots({})
    assert s == {"manufacturing": 1, "science": 1, "reaction": 1}


def test_job_slots_from_skills():
    levels = {
        skills.SKILL_MASS_PRODUCTION: 5,
        skills.SKILL_ADVANCED_MASS_PRODUCTION: 4,        # man = 1 + 5 + 4 = 10
        skills.SKILL_LABORATORY_OPERATION: 5,
        skills.SKILL_ADVANCED_LABORATORY_OPERATION: 5,   # sci = 1 + 5 + 5 = 11
        skills.SKILL_MASS_REACTIONS: 3,                  # rea = 1 + 3 = 4
    }
    assert skills.job_slots(levels) == {"manufacturing": 10, "science": 11, "reaction": 4}


def test_job_slots_capped_at_eleven():
    levels = {skills.SKILL_MASS_PRODUCTION: 5, skills.SKILL_ADVANCED_MASS_PRODUCTION: 5}
    assert skills.job_slots(levels)["manufacturing"] == 11  # 1+5+5 = 11, not capped lower


def test_job_slot_usage_counts_only_occupying_jobs():
    levels = {
        skills.SKILL_LABORATORY_OPERATION: 5,
        skills.SKILL_ADVANCED_LABORATORY_OPERATION: 1,   # science max = 7
    }
    jobs = [
        (4, "active"),     # ME research  → science, counts
        (3, "ready"),      # TE research  → science, counts (holds slot until delivered)
        (5, "active"),     # copying      → science, counts
        (8, "paused"),     # invention    → science, counts
        (4, "delivered"),  # finished     → not counted
        (1, "active"),     # manufacturing→ manufacturing
        (9, "cancelled"),  # reaction     → not counted
    ]
    usage = skills.job_slot_usage(jobs, levels)
    assert usage["science"] == {"used": 4, "max": 7}
    assert usage["manufacturing"] == {"used": 1, "max": 1}
    assert usage["reaction"] == {"used": 0, "max": 1}
