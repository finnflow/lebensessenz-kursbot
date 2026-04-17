"""
Tests for additive ontology schema loading.
"""
import csv
from pathlib import Path

from trennkost.models import CombinationGroup, FoodGroup
from trennkost.ontology import ONTOLOGY_CSV, Ontology


def _write_json(path: Path, content: str):
    path.write_text(content, encoding="utf-8")


def test_target_schema_fields_load_from_canonical_ontology():
    ontology = Ontology()

    banana = ontology.lookup("Banane")
    assert banana is not None
    assert banana.item_id == "banane"
    assert banana.group == FoodGroup.OBST
    assert banana.group_strict == CombinationGroup.FRUIT_DENSE
    assert banana.post_meal_wait_profile == "FRUIT_DENSE_OR_DRIED_45_60"

    apple = ontology.lookup("Apfel")
    assert apple is not None
    assert apple.group_strict == CombinationGroup.FRUIT_WATERY
    assert apple.group_strict != banana.group_strict
    assert apple.post_meal_wait_profile == "FRUIT_WATERY_20_30"

    dried = ontology.lookup("Dattel")
    assert dried is not None
    assert dried.group == FoodGroup.TROCKENOBST
    assert dried.group_strict == CombinationGroup.DRIED_FRUIT

    tofu = ontology.lookup("Tofu")
    assert tofu is not None
    assert tofu.group == FoodGroup.HUELSENFRUECHTE
    assert tofu.group_strict == CombinationGroup.PROTEIN
    assert tofu.risk_codes == ["SOY"]
    assert tofu.guidance_codes == ["SOY_IN_MODERATION"]

    mayo = ontology.lookup("Mayonnaise")
    assert mayo is not None
    assert mayo.group == FoodGroup.NEUTRAL
    assert mayo.group_strict == CombinationGroup.FETT
    assert mayo.high_fat is True
    assert mayo.risk_codes == ["HEAVY_FAT_LOAD"]
    assert mayo.modifier_policy == "CONDIMENT_ONLY"

    seitan = ontology.lookup("Seitan")
    assert seitan is not None
    assert seitan.group == FoodGroup.PROTEIN
    assert seitan.group_strict == CombinationGroup.PROTEIN
    assert seitan.risk_codes == ["GLUTEN_HIGH"]
    assert seitan.guidance_codes == ["GLUTEN_AWARE"]

    tempeh = ontology.lookup("Tempeh")
    assert tempeh is not None
    assert tempeh.group == FoodGroup.HUELSENFRUECHTE
    assert tempeh.group_strict == CombinationGroup.PROTEIN


def test_fruit_rows_use_consistent_strict_groups_and_wait_profiles():
    ontology = Ontology()

    watery_examples = [
        "Apfel",
        "Orange",
        "Mango",
        "Ananas",
        "Weintraube",
    ]
    dense_examples = ["Banane"]
    dried_examples = [
        "Dattel",
        "Rosine",
        "Feige",
        "Trockenpflaume",
        "Trockenapfel",
    ]

    for canonical in watery_examples:
        item = ontology.lookup(canonical)
        assert item is not None
        assert item.group_strict == CombinationGroup.FRUIT_WATERY
        assert item.post_meal_wait_profile == "FRUIT_WATERY_20_30"

    for canonical in dense_examples:
        item = ontology.lookup(canonical)
        assert item is not None
        assert item.group_strict == CombinationGroup.FRUIT_DENSE
        assert item.post_meal_wait_profile == "FRUIT_DENSE_OR_DRIED_45_60"

    for canonical in dried_examples:
        item = ontology.lookup(canonical)
        assert item is not None
        assert item.group_strict == CombinationGroup.DRIED_FRUIT
        assert item.post_meal_wait_profile == "FRUIT_DENSE_OR_DRIED_45_60"

    fruit_items = [
        entry
        for entry in ontology.entries
        if entry.group in {FoodGroup.OBST, FoodGroup.TROCKENOBST}
    ]
    assert fruit_items
    assert all(item.item_id for item in fruit_items)
    assert all(item.group_strict for item in fruit_items)
    assert all(item.post_meal_wait_profile for item in fruit_items)


def test_potato_variants_have_distinct_canonicals():
    ontology = Ontology()

    generic = ontology.lookup("Kartoffeln")
    boiled = ontology.lookup("Pellkartoffeln")
    fried = ontology.lookup("Bratkartoffeln")
    fries = ontology.lookup("Pommes")
    mashed = ontology.lookup("Kartoffelbrei")

    assert generic is not None and generic.canonical == "Kartoffel"
    assert boiled is not None and boiled.canonical == "Kartoffel gekocht"
    assert fried is not None and fried.canonical == "Bratkartoffeln"
    assert fries is not None and fries.canonical == "Pommes"
    assert mashed is not None and mashed.canonical == "Kartoffelpüree"

    assert boiled.base_item_id == "kartoffel"
    assert fried.base_item_id == "kartoffel"
    assert fries.base_item_id == "kartoffel"
    assert mashed.base_item_id == "kartoffel"
    assert boiled.post_meal_wait_profile is None
    assert fried.post_meal_wait_profile is None
    assert fries.post_meal_wait_profile is None
    assert mashed.post_meal_wait_profile is None
    assert fried.risk_codes == ["FRIED"]
    assert fries.risk_codes == ["FRIED", "HEAVY_FAT_LOAD"]
    assert mashed.risk_codes == ["UNKNOWN_BINDERS"]
    assert mashed.guidance_codes == ["CHECK_BINDERS"]


def test_core_item_risk_and_guidance_references_stay_validation_clean():
    ontology = Ontology()

    expected_codes = {
        "Mayonnaise": (["HEAVY_FAT_LOAD"], ["SMALL_AMOUNT_ONLY"]),
        "Pommes": (["FRIED", "HEAVY_FAT_LOAD"], []),
        "Bratkartoffeln": (["FRIED"], []),
        "Kartoffelpüree": (["UNKNOWN_BINDERS"], ["CHECK_BINDERS"]),
        "Tofu": (["SOY"], ["SOY_IN_MODERATION"]),
        "Tempeh": (["SOY"], ["SOY_IN_MODERATION"]),
        "Seitan": (["GLUTEN_HIGH"], ["GLUTEN_AWARE"]),
        "Veganes Patty": (["UNKNOWN_BINDERS"], ["CHECK_BINDERS"]),
        "Vegetarisches Patty": (["UNKNOWN_BINDERS"], ["CHECK_BINDERS"]),
        "Vegane Wurst": (["UNKNOWN_BINDERS"], ["CHECK_BINDERS"]),
        "Vegetarische Wurst": (["UNKNOWN_BINDERS"], ["CHECK_BINDERS"]),
        "Veganes Schnitzel": (["UNKNOWN_BINDERS"], ["CHECK_BINDERS"]),
        "Vegetarisches Schnitzel": (["UNKNOWN_BINDERS"], ["CHECK_BINDERS"]),
        "Chicken Nuggets": (["UNKNOWN_BINDERS"], ["CHECK_BINDERS"]),
        "Fischstäbchen": ([], []),
        "Paniertes Schnitzel": ([], []),
        "Cordon Bleu": ([], []),
    }

    for canonical, (risk_codes, guidance_codes) in expected_codes.items():
        item = ontology.lookup(canonical)
        assert item is not None
        assert item.risk_codes == risk_codes
        assert item.guidance_codes == guidance_codes
        assert all(code in ontology.risk_profiles for code in item.risk_codes)
        assert all(code in ontology.guidance_profiles for code in item.guidance_codes)


def test_mayonnaise_keeps_legacy_group_but_exposes_target_mapping():
    ontology = Ontology()

    mayo = ontology.lookup("Mayonnaise")
    assert mayo is not None
    assert mayo.group == FoodGroup.NEUTRAL
    assert mayo.group_strict == CombinationGroup.FETT


def test_lookup_to_food_item_preserves_additive_fields():
    ontology = Ontology()

    item = ontology.lookup_to_food_item("Zitronensaft")

    assert item.item_id == "zitronensaft"
    assert item.food_family == "condiment"
    assert item.group == FoodGroup.NEUTRAL
    assert item.group_strict == CombinationGroup.NEUTRAL
    assert item.modifier_policy == "CONDIMENT"
    assert item.base_item_id == "zitrone"
    assert item.intrinsic_conflict_code == "CITRUS_CONTEXTUAL"


def test_sidecar_profiles_load():
    ontology = Ontology()

    assert set(ontology.wait_profiles) >= {
        "RAW_VEG_OR_SALAD_2H",
        "PROPER_MEAL_NO_MEAT_3H",
        "PROPER_MEAL_WITH_MEAT_4H",
        "RANDOM_MEAL_UP_TO_8H",
        "FRUIT_WATERY_20_30",
        "FRUIT_DENSE_OR_DRIED_45_60",
    }
    assert ontology.risk_profiles["GLUTEN_HIGH"].severity.value == "YELLOW"
    assert ontology.risk_profiles["FRIED"].severity.value == "RED"
    assert ontology.risk_profiles["HEAVY_FAT_LOAD"].severity.value == "RED"
    assert ontology.guidance_profiles["SMALL_AMOUNT_ONLY"].title
    assert ontology.guidance_profiles["CHECK_BINDERS"].title
    assert ontology.guidance_profiles["FAT_WITH_NEUTRAL_SMALL_AMOUNT"].title
    assert ontology.guidance_profiles["FAT_WITH_CONFLICT_GROUP_TINY_AMOUNT"].title


def test_canonical_ontology_has_no_validation_issues():
    ontology = Ontology()
    assert ontology.validation_issues == []
    ontology.assert_valid()


def test_canonical_ontology_csv_is_row_clean_and_comment_free():
    with open(ONTOLOGY_CSV, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        assert len(header) == 21

        for line_number, row in enumerate(reader, start=2):
            assert row, f"Ontology row {line_number} is unexpectedly empty"
            assert len(row) == len(header), (
                f"Ontology row {line_number} has {len(row)} columns "
                f"(expected {len(header)})"
            )
            assert row[0].strip(), f"Ontology row {line_number} has empty canonical value"
            assert not row[0].strip().startswith("#"), (
                f"Ontology row {line_number} contains a comment-style row in CSV body"
            )


def test_loader_handles_legacy_and_malformed_rows(tmp_path):
    ontology_csv = tmp_path / "ontology.csv"
    compounds_json = tmp_path / "compounds.json"
    wait_profiles_json = tmp_path / "wait_profiles.json"
    risk_profiles_json = tmp_path / "risk_profiles.json"
    guidance_profiles_json = tmp_path / "guidance_profiles.json"

    header = "canonical,synonyms,group,subgroup,ambiguity_flag,ambiguity_note,high_fat,notes,item_id,food_family,group_strict,post_meal_wait_profile,modifier_policy,base_item_id,intrinsic_conflict_code,risk_codes,guidance_codes"
    rows = [
        header,
        "# comment row should be ignored",
        ",".join(["Legacy Apple", "Legacy Apfel", "OBST", "FRISCH", "false", "", "false", "", "", "", "", "", "", "", "", "", ""]),
        ",".join(["", "", "OBST", "FRISCH", "false", "", "false", "", "", "", "", "", "", "", "", "", ""]),
        ",".join(["Broken Group", "", "NOT_A_GROUP", "", "false", "", "false", "", "", "", "", "", "", "", "", "", ""]),
        ",".join(["Broken Strict", "", "NEUTRAL", "", "false", "", "false", "", "", "", "INVALID_STRICT", "", "", "", "", "", ""]),
        ",".join(["Broken Extra", "", "NEUTRAL", "", "false", "", "false", "", "", "", "", "", "", "", "", "", "", "unexpected"]),
        ",".join(["Broken Ref", "", "NEUTRAL", "", "false", "", "false", "", "", "", "", "UNKNOWN_WAIT", "", "", "", "MISSING_RISK", "MISSING_GUIDANCE"]),
    ]
    ontology_csv.write_text("\n".join(rows), encoding="utf-8")
    _write_json(compounds_json, '{"compounds": {}}')
    _write_json(wait_profiles_json, '{"wait_profiles": {}}')
    _write_json(risk_profiles_json, '{"risk_profiles": {}}')
    _write_json(guidance_profiles_json, '{"guidance_profiles": {}}')

    ontology = Ontology(
        ontology_csv=ontology_csv,
        compounds_json=compounds_json,
        wait_profiles_json=wait_profiles_json,
        risk_profiles_json=risk_profiles_json,
        guidance_profiles_json=guidance_profiles_json,
    )

    legacy = ontology.lookup("Legacy Apple")
    assert legacy is not None
    assert legacy.item_id == "legacy_apple"
    assert legacy.group == FoodGroup.OBST
    assert legacy.group_strict == CombinationGroup.FRUIT_WATERY

    broken_group = ontology.lookup("Broken Group")
    assert broken_group is not None
    assert broken_group.group == FoodGroup.UNKNOWN
    assert broken_group.group_strict == CombinationGroup.UNKNOWN

    broken_strict = ontology.lookup("Broken Strict")
    assert broken_strict is not None
    assert broken_strict.group == FoodGroup.NEUTRAL
    assert broken_strict.group_strict == CombinationGroup.NEUTRAL

    broken_extra = ontology.lookup("Broken Extra")
    assert broken_extra is not None
    assert broken_extra.group == FoodGroup.NEUTRAL

    assert any("without canonical value" in issue for issue in ontology.validation_issues)
    assert any("unknown legacy food group 'NOT_A_GROUP'" in issue for issue in ontology.validation_issues)
    assert any("unknown strict group 'INVALID_STRICT'" in issue for issue in ontology.validation_issues)
    assert any("unexpected extra columns" in issue for issue in ontology.validation_issues)
    assert any("unknown wait profile 'UNKNOWN_WAIT'" in issue for issue in ontology.validation_issues)
    assert any("unknown risk code 'MISSING_RISK'" in issue for issue in ontology.validation_issues)
    assert any("unknown guidance code 'MISSING_GUIDANCE'" in issue for issue in ontology.validation_issues)
