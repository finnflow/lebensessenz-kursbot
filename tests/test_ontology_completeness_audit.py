"""
Focused completeness/integrity audit for ontology migration safety.
"""
import csv
import json
import re
from collections import Counter, defaultdict
from typing import Dict, List, Tuple

from trennkost.ontology import (
    COMPOUNDS_JSON,
    GUIDANCE_PROFILES_JSON,
    ONTOLOGY_CSV,
    RISK_PROFILES_JSON,
    WAIT_PROFILES_JSON,
    Ontology,
)

ALLOWED_MODIFIER_POLICIES = {
    "CONDIMENT",
    "CONDIMENT_ONLY",
    "VARIANT_UNCLEAR",
}

ALLOWED_INTRINSIC_CONFLICT_CODES = {
    "BREADED_PROTEIN_CONFLICT",
    "STUFFED_BREADED_PROTEIN_CONFLICT",
    "CITRUS_CONTEXTUAL",
}

STRUCTURED_FIELDS_REQUIRING_EXPLICIT_ITEM_ID = {
    "food_family",
    "group_strict",
    "post_meal_wait_profile",
    "modifier_policy",
    "base_item_id",
    "intrinsic_conflict_code",
    "risk_codes",
    "guidance_codes",
    "forced_components",
    "compound_type",
    "decompose_for_logic",
}


def _parse_csv_list(value: str) -> List[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part and part.strip()]


def _slugify(canonical: str) -> str:
    slug = canonical.lower()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    return slug or "unknown_item"


def _load_canonical_rows() -> List[Tuple[int, Dict[str, str]]]:
    rows: List[Tuple[int, Dict[str, str]]] = []
    with open(ONTOLOGY_CSV, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for line_number, row in enumerate(reader, start=2):
            normalized = {key: (value or "").strip() for key, value in row.items()}
            canonical = normalized.get("canonical", "")
            if not canonical:
                continue
            rows.append((line_number, normalized))
    return rows


def test_audit_unique_canonicals_and_item_ids():
    rows = _load_canonical_rows()

    canonical_counter = Counter(row["canonical"] for _, row in rows)
    duplicate_canonicals = sorted(
        canonical for canonical, count in canonical_counter.items() if count > 1
    )
    assert duplicate_canonicals == []

    explicit_item_ids = [
        row["item_id"]
        for _, row in rows
        if row.get("item_id")
    ]
    explicit_item_id_counter = Counter(explicit_item_ids)
    duplicate_explicit_item_ids = sorted(
        item_id for item_id, count in explicit_item_id_counter.items() if count > 1
    )
    assert duplicate_explicit_item_ids == []

    structured_missing_item_id = []
    for line_number, row in rows:
        if row.get("item_id"):
            continue
        if any(row.get(field, "") for field in STRUCTURED_FIELDS_REQUIRING_EXPLICIT_ITEM_ID):
            structured_missing_item_id.append((line_number, row["canonical"]))

    assert structured_missing_item_id == []

    effective_item_ids = [row["item_id"] or _slugify(row["canonical"]) for _, row in rows]
    effective_item_id_counter = Counter(effective_item_ids)
    duplicate_effective_item_ids = sorted(
        item_id for item_id, count in effective_item_id_counter.items() if count > 1
    )
    assert duplicate_effective_item_ids == []


def test_audit_no_ambiguous_term_collisions():
    rows = _load_canonical_rows()

    term_to_canonicals: Dict[str, set] = defaultdict(set)
    for _, row in rows:
        canonical = row["canonical"]
        terms = [canonical, *_parse_csv_list(row.get("synonyms", ""))]
        for term in terms:
            term_to_canonicals[term.lower()].add(canonical)

    collisions = {
        term: sorted(canonicals)
        for term, canonicals in term_to_canonicals.items()
        if len(canonicals) > 1
    }
    assert collisions == {}


def test_audit_reference_integrity_and_allowed_code_sets():
    rows = _load_canonical_rows()

    with open(WAIT_PROFILES_JSON, "r", encoding="utf-8") as f:
        wait_profiles = json.load(f)["wait_profiles"]
    with open(RISK_PROFILES_JSON, "r", encoding="utf-8") as f:
        risk_profiles = json.load(f)["risk_profiles"]
    with open(GUIDANCE_PROFILES_JSON, "r", encoding="utf-8") as f:
        guidance_profiles = json.load(f)["guidance_profiles"]

    canonical_set = {row["canonical"] for _, row in rows}
    effective_item_id_set = {row["item_id"] or _slugify(row["canonical"]) for _, row in rows}

    orphan_base_item_ids = []
    orphan_forced_components = []
    invalid_wait_profiles = []
    invalid_risk_codes = []
    invalid_guidance_codes = []
    invalid_modifier_policies = []
    invalid_intrinsic_codes = []

    for line_number, row in rows:
        canonical = row["canonical"]

        base_item_id = row.get("base_item_id")
        if base_item_id and base_item_id not in effective_item_id_set:
            orphan_base_item_ids.append((line_number, canonical, base_item_id))

        for forced in _parse_csv_list(row.get("forced_components", "")):
            if forced not in canonical_set:
                orphan_forced_components.append((line_number, canonical, forced))

        wait_profile = row.get("post_meal_wait_profile")
        if wait_profile and wait_profile not in wait_profiles:
            invalid_wait_profiles.append((line_number, canonical, wait_profile))

        for risk_code in _parse_csv_list(row.get("risk_codes", "")):
            if risk_code not in risk_profiles:
                invalid_risk_codes.append((line_number, canonical, risk_code))

        for guidance_code in _parse_csv_list(row.get("guidance_codes", "")):
            if guidance_code not in guidance_profiles:
                invalid_guidance_codes.append((line_number, canonical, guidance_code))

        modifier_policy = row.get("modifier_policy")
        if modifier_policy and modifier_policy not in ALLOWED_MODIFIER_POLICIES:
            invalid_modifier_policies.append((line_number, canonical, modifier_policy))

        intrinsic_code = row.get("intrinsic_conflict_code")
        if intrinsic_code and intrinsic_code not in ALLOWED_INTRINSIC_CONFLICT_CODES:
            invalid_intrinsic_codes.append((line_number, canonical, intrinsic_code))

    assert orphan_base_item_ids == []
    assert orphan_forced_components == []
    assert invalid_wait_profiles == []
    assert invalid_risk_codes == []
    assert invalid_guidance_codes == []
    assert invalid_modifier_policies == []
    assert invalid_intrinsic_codes == []


def test_audit_compound_base_items_are_lookup_reachable():
    ontology = Ontology()
    with open(COMPOUNDS_JSON, "r", encoding="utf-8") as f:
        compounds = json.load(f)["compounds"]

    missing_base_items = []
    for dish_name, payload in compounds.items():
        for base_item in payload.get("base_items", []):
            if ontology.lookup(base_item) is None:
                missing_base_items.append((dish_name, base_item))

    assert missing_base_items == []
