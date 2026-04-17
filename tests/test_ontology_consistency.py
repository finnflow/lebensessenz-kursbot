"""
Focused ontology consistency checks for PR3 smoothing.
"""
from trennkost.models import CombinationGroup, FoodGroup
from trennkost.ontology import Ontology


def test_variant_rows_stay_explicitly_unknown_and_cautious():
    ontology = Ontology()
    entries = {entry.canonical: entry for entry in ontology.entries}

    variant_canonicals = [
        "Veganes Patty",
        "Vegetarisches Patty",
        "Vegane Wurst",
        "Vegetarische Wurst",
        "Veganes Schnitzel",
        "Vegetarisches Schnitzel",
    ]

    for canonical in variant_canonicals:
        entry = entries[canonical]
        assert entry.group == FoodGroup.UNKNOWN
        assert entry.group_strict == CombinationGroup.UNKNOWN
        assert entry.modifier_policy == "VARIANT_UNCLEAR"
        assert entry.risk_codes == ["UNKNOWN_BINDERS"]
        assert entry.guidance_codes == ["CHECK_BINDERS"]


def test_fruit_wait_and_light_model_is_globally_consistent():
    ontology = Ontology()

    for entry in ontology.entries:
        if entry.group not in {FoodGroup.OBST, FoodGroup.TROCKENOBST}:
            continue

        if entry.canonical == "Banane":
            assert entry.group_strict == CombinationGroup.FRUIT_DENSE
            assert entry.post_meal_wait_profile == "FRUIT_DENSE_OR_DRIED_45_60"
            continue

        if entry.group == FoodGroup.TROCKENOBST:
            assert entry.group_strict == CombinationGroup.DRIED_FRUIT
            assert entry.post_meal_wait_profile == "FRUIT_DENSE_OR_DRIED_45_60"
            continue

        assert entry.group_strict == CombinationGroup.FRUIT_WATERY
        assert entry.post_meal_wait_profile == "FRUIT_WATERY_20_30"


def test_condiment_family_rows_use_consistent_metadata():
    ontology = Ontology()
    entries = {entry.canonical: entry for entry in ontology.entries}

    neutral_condiments = [
        "Senf",
        "Essig",
        "Zitronensaft",
        "Sojasauce",
        "Ketchup",
        "Reisessig",
        "Fischsauce",
    ]

    for canonical in neutral_condiments:
        entry = entries[canonical]
        assert entry.group == FoodGroup.NEUTRAL
        assert entry.food_family == "condiment"
        assert entry.group_strict == CombinationGroup.NEUTRAL
        assert entry.modifier_policy == "CONDIMENT"

    mayonnaise = entries["Mayonnaise"]
    assert mayonnaise.group == FoodGroup.NEUTRAL
    assert mayonnaise.food_family == "condiment"
    assert mayonnaise.group_strict == CombinationGroup.FETT
    assert mayonnaise.modifier_policy == "CONDIMENT_ONLY"
    assert mayonnaise.high_fat is True
