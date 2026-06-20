"""Guards the invention-probability SDE fix: invention success probabilities live in
their own fuzzwork table (industryActivityProbabilities) and must be merged onto the
activity-product rows AFTER they exist, else invention success chance reads 0."""
from app.tasks import update_sde


def test_probabilities_step_runs_after_products():
    names = [name for name, _ in update_sde.STEPS]
    assert "activity_products" in names
    assert "activity_probabilities" in names
    assert names.index("activity_probabilities") > names.index("activity_products")


def test_probabilities_updater_exists_and_is_distinct():
    assert callable(update_sde.update_activity_probabilities)
    assert update_sde.update_activity_probabilities is not update_sde.update_activity_products
