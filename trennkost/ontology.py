"""
Ontology loader and lookup.

Loads ontology.csv into memory and provides fast synonym-based lookup.
Unknown items are logged for iterative growth.
"""
import csv
import json
import logging
from pathlib import Path
import re
from typing import Dict, List, Optional, Tuple, Type, TypeVar

from trennkost.models import (
    CombinationGroup,
    FoodGroup,
    FoodSubgroup,
    FoodItem,
    GuidanceProfile,
    OntologyEntry,
    RiskProfile,
    WaitProfile,
)

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
ONTOLOGY_CSV = DATA_DIR / "ontology.csv"
COMPOUNDS_JSON = DATA_DIR / "compounds.json"
WAIT_PROFILES_JSON = DATA_DIR / "wait_profiles.json"
RISK_PROFILES_JSON = DATA_DIR / "risk_profiles.json"
GUIDANCE_PROFILES_JSON = DATA_DIR / "guidance_profiles.json"
UNKNOWN_LOG = Path(__file__).parent.parent / "storage" / "trennkost_unknowns.log"

T = TypeVar("T", WaitProfile, RiskProfile, GuidanceProfile)

STRICT_GROUP_DEFAULTS: Dict[FoodGroup, CombinationGroup] = {
    FoodGroup.OBST: CombinationGroup.FRUIT_WATERY,
    FoodGroup.TROCKENOBST: CombinationGroup.DRIED_FRUIT,
    FoodGroup.NEUTRAL: CombinationGroup.NEUTRAL,
    FoodGroup.KH: CombinationGroup.KH,
    FoodGroup.HUELSENFRUECHTE: CombinationGroup.HUELSENFRUECHTE,
    FoodGroup.PROTEIN: CombinationGroup.PROTEIN,
    FoodGroup.MILCH: CombinationGroup.MILCH,
    FoodGroup.FETT: CombinationGroup.FETT,
    FoodGroup.UNKNOWN: CombinationGroup.UNKNOWN,
}

LIGHT_GROUP_DEFAULTS: Dict[FoodGroup, CombinationGroup] = {
    FoodGroup.OBST: CombinationGroup.FRUIT_WATERY,
    FoodGroup.TROCKENOBST: CombinationGroup.KH,
    FoodGroup.NEUTRAL: CombinationGroup.NEUTRAL,
    FoodGroup.KH: CombinationGroup.KH,
    FoodGroup.HUELSENFRUECHTE: CombinationGroup.HUELSENFRUECHTE,
    FoodGroup.PROTEIN: CombinationGroup.PROTEIN,
    FoodGroup.MILCH: CombinationGroup.MILCH,
    FoodGroup.FETT: CombinationGroup.FETT,
    FoodGroup.UNKNOWN: CombinationGroup.UNKNOWN,
}

STRICT_COMBINATION_TO_LEGACY_GROUP: Dict[CombinationGroup, FoodGroup] = {
    CombinationGroup.FRUIT_WATERY: FoodGroup.OBST,
    CombinationGroup.FRUIT_DENSE: FoodGroup.OBST,
    CombinationGroup.DRIED_FRUIT: FoodGroup.TROCKENOBST,
    CombinationGroup.NEUTRAL: FoodGroup.NEUTRAL,
    CombinationGroup.KH: FoodGroup.KH,
    CombinationGroup.HUELSENFRUECHTE: FoodGroup.HUELSENFRUECHTE,
    CombinationGroup.PROTEIN: FoodGroup.PROTEIN,
    CombinationGroup.MILCH: FoodGroup.MILCH,
    CombinationGroup.FETT: FoodGroup.FETT,
    CombinationGroup.UNKNOWN: FoodGroup.UNKNOWN,
}

# Explicit stability seam: these items already carry future-facing target mappings,
# but deterministic evaluation must stay legacy-compatible until follow-up PRs land.
STRICT_EVALUATION_LEGACY_OVERRIDES: Dict[str, FoodGroup] = {
    "tofu": FoodGroup.HUELSENFRUECHTE,
    "tempeh": FoodGroup.HUELSENFRUECHTE,
}


def resolve_effective_group(item: FoodItem, mode: str = "strict") -> FoodGroup:
    """
    Central resolver for the group used in deterministic evaluation.

    Strict mode is the only supported mode for now. It uses strict ontology groups
    where that is behaviorally safe, while preserving explicit legacy overrides for
    known split items until later PRs intentionally change verdict behavior.
    """
    if mode != "strict":
        raise NotImplementedError(f"Evaluation group mode '{mode}' is not activated yet")

    if item.group == FoodGroup.UNKNOWN:
        return FoodGroup.UNKNOWN

    if item.item_id and item.item_id in STRICT_EVALUATION_LEGACY_OVERRIDES:
        return STRICT_EVALUATION_LEGACY_OVERRIDES[item.item_id]

    strict_group = item.group_strict or STRICT_GROUP_DEFAULTS.get(item.group, CombinationGroup.UNKNOWN)
    return STRICT_COMBINATION_TO_LEGACY_GROUP.get(strict_group, item.group)


class Ontology:
    """In-memory food ontology with synonym lookup."""

    def __init__(
        self,
        ontology_csv: Path = ONTOLOGY_CSV,
        compounds_json: Path = COMPOUNDS_JSON,
        wait_profiles_json: Path = WAIT_PROFILES_JSON,
        risk_profiles_json: Path = RISK_PROFILES_JSON,
        guidance_profiles_json: Path = GUIDANCE_PROFILES_JSON,
    ):
        self._ontology_csv = Path(ontology_csv)
        self._compounds_json = Path(compounds_json)
        self._wait_profiles_json = Path(wait_profiles_json)
        self._risk_profiles_json = Path(risk_profiles_json)
        self._guidance_profiles_json = Path(guidance_profiles_json)
        self._entries: List[OntologyEntry] = []
        self._synonym_index: Dict[str, OntologyEntry] = {}  # lowercase → entry
        self._compounds: Dict[str, dict] = {}
        self._wait_profiles: Dict[str, WaitProfile] = {}
        self._risk_profiles: Dict[str, RiskProfile] = {}
        self._guidance_profiles: Dict[str, GuidanceProfile] = {}
        self._validation_issues: List[str] = []
        self._load_profiles()
        self._load_ontology()
        self._load_compounds()

    def _load_profiles(self):
        """Load sidecar profile registries."""
        self._wait_profiles = self._load_profile_registry(
            path=self._wait_profiles_json,
            container_key="wait_profiles",
            key_field="profile_id",
            model_cls=WaitProfile,
        )
        self._risk_profiles = self._load_profile_registry(
            path=self._risk_profiles_json,
            container_key="risk_profiles",
            key_field="code",
            model_cls=RiskProfile,
        )
        self._guidance_profiles = self._load_profile_registry(
            path=self._guidance_profiles_json,
            container_key="guidance_profiles",
            key_field="code",
            model_cls=GuidanceProfile,
        )

    def _load_profile_registry(
        self,
        path: Path,
        container_key: str,
        key_field: str,
        model_cls: Type[T],
    ) -> Dict[str, T]:
        if not path.exists():
            logger.info("Profile file not found: %s", path)
            return {}

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            self._record_issue(f"Failed to load profile file {path}: {exc}")
            return {}

        raw_profiles = data.get(container_key, {})
        profiles: Dict[str, T] = {}
        for key, raw in raw_profiles.items():
            if not isinstance(raw, dict):
                self._record_issue(f"Ignoring malformed profile {key} in {path}")
                continue
            payload = dict(raw)
            payload.setdefault(key_field, key)
            try:
                profile = model_cls(**payload)
            except Exception as exc:
                self._record_issue(f"Ignoring invalid profile {key} in {path}: {exc}")
                continue
            profiles[key] = profile

        logger.info("Loaded %d %s profiles", len(profiles), container_key)
        return profiles

    def _load_ontology(self):
        """Load ontology.csv and build synonym index."""
        if not self._ontology_csv.exists():
            logger.warning(f"Ontology file not found: {self._ontology_csv}")
            return

        with open(self._ontology_csv, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f, restkey="__extra__")
            for line_number, raw_row in enumerate(reader, start=2):
                row = self._normalize_row(raw_row)
                if self._is_comment_or_empty(row):
                    continue

                entry = self._parse_entry(row, line_number)
                if entry is None:
                    continue

                self._entries.append(entry)
                self._index_entry(entry)

        logger.info(f"Ontology loaded: {len(self._entries)} entries, {len(self._synonym_index)} synonyms")

    def _normalize_row(self, row: Dict[str, Optional[str]]) -> Dict[str, str]:
        normalized: Dict[str, str] = {}
        for key, value in row.items():
            clean_key = (key or "").strip()
            if not clean_key:
                continue
            if clean_key == "__extra__":
                normalized[clean_key] = ",".join(v for v in value or [] if v)
                continue
            normalized[clean_key] = (value or "").strip()
        return normalized

    def _is_comment_or_empty(self, row: Dict[str, str]) -> bool:
        meaningful_values = [value for key, value in row.items() if key != "__extra__" and value]
        if not meaningful_values:
            return True
        first_value = meaningful_values[0].strip()
        return first_value.startswith("#")

    def _parse_entry(self, row: Dict[str, str], line_number: int) -> Optional[OntologyEntry]:
        canonical = row.get("canonical", "").strip()
        if not canonical:
            self._record_issue(f"Skipping ontology row {line_number} without canonical value")
            return None

        if row.get("__extra__"):
            self._record_issue(
                f"Ontology row {line_number} for '{canonical}' has unexpected extra columns: {row['__extra__']}"
            )

        group_raw = (row.get("group") or "").strip()
        if group_raw and group_raw not in FoodGroup._value2member_map_:
            self._record_issue(
                f"Ontology row {line_number} for '{canonical}' has unknown legacy food group '{group_raw}'"
            )

        subgroup_raw = (row.get("subgroup") or "").strip()
        if subgroup_raw and subgroup_raw not in FoodSubgroup._value2member_map_:
            self._record_issue(
                f"Ontology row {line_number} for '{canonical}' has unknown food subgroup '{subgroup_raw}'"
            )

        group_strict_raw = (row.get("group_strict") or "").strip()
        if group_strict_raw and group_strict_raw not in CombinationGroup._value2member_map_:
            self._record_issue(
                f"Ontology row {line_number} for '{canonical}' has unknown strict group '{group_strict_raw}'"
            )

        group_light_raw = (row.get("group_light") or "").strip()
        if group_light_raw and group_light_raw not in CombinationGroup._value2member_map_:
            self._record_issue(
                f"Ontology row {line_number} for '{canonical}' has unknown light group '{group_light_raw}'"
            )

        synonyms = self._parse_csv_list(row.get("synonyms"))
        group = self._parse_food_group(row.get("group"))
        subgroup = self._parse_food_subgroup(row.get("subgroup"))
        item_id = row.get("item_id") or self._build_item_id(canonical)
        group_strict = self._parse_combination_group(
            row.get("group_strict"),
            fallback=STRICT_GROUP_DEFAULTS[group],
        )
        group_light = self._parse_combination_group(
            row.get("group_light"),
            fallback=LIGHT_GROUP_DEFAULTS[group],
        )
        risk_codes = self._parse_csv_list(row.get("risk_codes"))
        guidance_codes = self._parse_csv_list(row.get("guidance_codes"))

        entry = OntologyEntry(
            item_id=item_id,
            canonical=canonical,
            synonyms=synonyms,
            food_family=row.get("food_family") or self._default_food_family(group),
            group=group,
            subgroup=subgroup,
            group_strict=group_strict,
            group_light=group_light,
            post_meal_wait_profile=row.get("post_meal_wait_profile") or None,
            modifier_policy=row.get("modifier_policy") or None,
            ambiguity_flag=self._parse_bool(row.get("ambiguity_flag")),
            ambiguity_note=row.get("ambiguity_note") or None,
            base_item_id=row.get("base_item_id") or None,
            intrinsic_conflict_code=row.get("intrinsic_conflict_code") or None,
            forced_components=self._parse_csv_list(row.get("forced_components")),
            compound_type=row.get("compound_type") or None,
            decompose_for_logic=self._parse_bool(row.get("decompose_for_logic")),
            risk_codes=risk_codes,
            guidance_codes=guidance_codes,
            high_fat=self._parse_bool(row.get("high_fat")),
            notes=row.get("notes") or None,
        )
        self._validate_references(entry, line_number)
        return entry

    def _validate_references(self, entry: OntologyEntry, line_number: int):
        if entry.post_meal_wait_profile and entry.post_meal_wait_profile not in self._wait_profiles:
            self._record_issue(
                f"Ontology row {line_number} for '{entry.canonical}' references unknown wait profile '{entry.post_meal_wait_profile}'"
            )
        for code in entry.risk_codes:
            if code not in self._risk_profiles:
                self._record_issue(
                    f"Ontology row {line_number} for '{entry.canonical}' references unknown risk code '{code}'"
                )
        for code in entry.guidance_codes:
            if code not in self._guidance_profiles:
                self._record_issue(
                    f"Ontology row {line_number} for '{entry.canonical}' references unknown guidance code '{code}'"
                )

    def _record_issue(self, message: str):
        self._validation_issues.append(message)
        logger.warning(message)

    def _index_entry(self, entry: OntologyEntry):
        for key in [entry.canonical, *entry.synonyms]:
            normalized = key.lower()
            if normalized in self._synonym_index and self._synonym_index[normalized].canonical != entry.canonical:
                logger.warning(
                    "Ontology synonym '%s' is duplicated for '%s' and '%s'; keeping first entry",
                    key,
                    self._synonym_index[normalized].canonical,
                    entry.canonical,
                )
                continue
            self._synonym_index[normalized] = entry

    def _load_compounds(self):
        """Load compounds.json for compound dish lookup."""
        if not self._compounds_json.exists():
            return
        with open(self._compounds_json, "r", encoding="utf-8") as f:
            data = json.load(f)
            self._compounds = data.get("compounds", {})
        logger.info(f"Compounds loaded: {len(self._compounds)} dishes")

    def _parse_csv_list(self, raw_value: Optional[str]) -> List[str]:
        if not raw_value:
            return []
        return [part.strip() for part in raw_value.split(",") if part and part.strip()]

    def _parse_bool(self, value: Optional[str]) -> bool:
        if not value:
            return False
        return value.strip().lower() in {"1", "true", "yes", "y"}

    def _parse_food_group(self, value: Optional[str]) -> FoodGroup:
        try:
            return FoodGroup((value or "UNKNOWN").strip() or "UNKNOWN")
        except ValueError:
            logger.warning("Unknown legacy food group '%s'; defaulting to UNKNOWN", value)
            return FoodGroup.UNKNOWN

    def _parse_food_subgroup(self, value: Optional[str]) -> Optional[FoodSubgroup]:
        raw = (value or "").strip()
        if not raw:
            return None
        try:
            return FoodSubgroup(raw)
        except ValueError:
            logger.warning("Unknown food subgroup '%s'; leaving subgroup unset", raw)
            return None

    def _parse_combination_group(
        self,
        value: Optional[str],
        fallback: CombinationGroup,
    ) -> CombinationGroup:
        raw = (value or "").strip()
        if not raw:
            return fallback
        try:
            return CombinationGroup(raw)
        except ValueError:
            logger.warning("Unknown combination group '%s'; using fallback '%s'", raw, fallback.value)
            return fallback

    def _build_item_id(self, canonical: str) -> str:
        slug = canonical.lower()
        slug = re.sub(r"[^a-z0-9]+", "_", slug)
        slug = slug.strip("_")
        return slug or "unknown_item"

    def _default_food_family(self, group: FoodGroup) -> Optional[str]:
        defaults = {
            FoodGroup.OBST: "fruit",
            FoodGroup.TROCKENOBST: "fruit",
            FoodGroup.NEUTRAL: "vegetable",
            FoodGroup.KH: "carb",
            FoodGroup.HUELSENFRUECHTE: "legume",
            FoodGroup.PROTEIN: "protein",
            FoodGroup.MILCH: "dairy",
            FoodGroup.FETT: "fat",
        }
        return defaults.get(group)

    def lookup(self, raw_name: str) -> Optional[OntologyEntry]:
        """
        Look up a food item by name (case-insensitive, synonym-aware).

        Returns OntologyEntry if found, None if unknown.
        """
        key = raw_name.strip().lower()

        # 1. Exact match
        if key in self._synonym_index:
            return self._synonym_index[key]

        # 2. Substring match: check if any synonym is contained in the raw name
        #    e.g. "gegrilltes Hähnchen" should match "Hähnchen"
        best_match = None
        best_len = 0
        for syn, entry in self._synonym_index.items():
            if syn in key and len(syn) > best_len:
                best_match = entry
                best_len = len(syn)

        if best_match and best_len >= 3:  # Minimum 3 chars to avoid false matches
            return best_match

        # 3. Check if raw_name is contained in any synonym
        #    e.g. "Lachs" should match "Räucherlachs" entry
        for syn, entry in self._synonym_index.items():
            if key in syn and len(key) >= 3:
                return entry

        return None

    def lookup_to_food_item(self, raw_name: str, assumed: bool = False,
                             assumption_reason: Optional[str] = None) -> FoodItem:
        """
        Look up and return a FoodItem. If not found, returns UNKNOWN item.
        """
        entry = self.lookup(raw_name)
        if entry:
            return FoodItem(
                raw_name=raw_name,
                item_id=entry.item_id,
                canonical=entry.canonical,
                group=entry.group,
                subgroup=entry.subgroup,
                food_family=entry.food_family,
                group_strict=entry.group_strict,
                group_light=entry.group_light,
                post_meal_wait_profile=entry.post_meal_wait_profile,
                modifier_policy=entry.modifier_policy,
                base_item_id=entry.base_item_id,
                intrinsic_conflict_code=entry.intrinsic_conflict_code,
                forced_components=list(entry.forced_components),
                compound_type=entry.compound_type,
                decompose_for_logic=entry.decompose_for_logic,
                risk_codes=list(entry.risk_codes),
                guidance_codes=list(entry.guidance_codes),
                high_fat=entry.high_fat,
                confidence=0.7 if entry.ambiguity_flag else 1.0,
                assumed=assumed,
                assumption_reason=assumption_reason,
            )
        else:
            self._log_unknown(raw_name)
            return FoodItem(
                raw_name=raw_name,
                item_id=None,
                canonical=None,
                group=FoodGroup.UNKNOWN,
                subgroup=None,
                food_family=None,
                group_strict=CombinationGroup.UNKNOWN,
                group_light=CombinationGroup.UNKNOWN,
                post_meal_wait_profile=None,
                modifier_policy=None,
                base_item_id=None,
                intrinsic_conflict_code=None,
                forced_components=[],
                compound_type=None,
                decompose_for_logic=False,
                risk_codes=[],
                guidance_codes=[],
                high_fat=False,
                confidence=0.0,
                assumed=assumed,
                assumption_reason=assumption_reason,
            )

    def expand_item_for_logic(self, item: FoodItem) -> List[FoodItem]:
        """
        Return deterministic internal components for intrinsic-conflict items.

        The canonical item remains present; this only provides additional logic items.
        """
        if not item.decompose_for_logic or not item.forced_components:
            return []

        components: List[FoodItem] = []
        for component_name in item.forced_components:
            component_item = self.lookup_to_food_item(component_name)
            components.append(component_item)
        return components

    def get_compound(self, dish_name: str) -> Optional[dict]:
        """
        Check if a dish is a known compound.
        Returns compound dict or None.
        """
        key = dish_name.strip()
        # Exact match first
        if key in self._compounds:
            return self._compounds[key]
        # Case-insensitive
        for name, compound in self._compounds.items():
            if name.lower() == key.lower():
                return compound
        return None

    def get_ambiguous_entries(self, items: List[FoodItem]) -> List[Tuple[FoodItem, str]]:
        """
        Return items that have ambiguity flags with their notes.
        """
        result = []
        for item in items:
            entry = self.lookup(item.raw_name)
            if entry and entry.ambiguity_flag and entry.ambiguity_note:
                result.append((item, entry.ambiguity_note))
        return result

    def _log_unknown(self, raw_name: str):
        """Log unknown items for iterative ontology growth."""
        try:
            with open(UNKNOWN_LOG, "a", encoding="utf-8") as f:
                f.write(f"{raw_name}\n")
        except OSError:
            logger.warning(f"Could not log unknown item: {raw_name}")

    @property
    def entries(self) -> List[OntologyEntry]:
        return self._entries

    @property
    def compounds(self) -> Dict[str, dict]:
        return self._compounds

    @property
    def wait_profiles(self) -> Dict[str, WaitProfile]:
        return self._wait_profiles

    @property
    def risk_profiles(self) -> Dict[str, RiskProfile]:
        return self._risk_profiles

    @property
    def guidance_profiles(self) -> Dict[str, GuidanceProfile]:
        return self._guidance_profiles

    @property
    def validation_issues(self) -> List[str]:
        return list(self._validation_issues)

    def assert_valid(self):
        if self._validation_issues:
            raise ValueError("Ontology validation failed:\n" + "\n".join(self._validation_issues))


# Module-level singleton
_ontology: Optional[Ontology] = None


def get_ontology() -> Ontology:
    """Get or create the singleton Ontology instance."""
    global _ontology
    if _ontology is None:
        _ontology = Ontology()
    return _ontology
