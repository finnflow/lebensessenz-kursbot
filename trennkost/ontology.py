"""
Ontology loader and lookup.

Loads ontology.csv into memory and provides fast synonym-based lookup.
Unknown items are logged for iterative growth.
"""
import csv
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from trennkost.models import (
    FoodGroup,
    FoodSubgroup,
    OntologyEntry,
    FoodItem,
)

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
ONTOLOGY_CSV = DATA_DIR / "ontology.csv"
COMPOUNDS_JSON = DATA_DIR / "compounds.json"
UNKNOWN_LOG = Path(__file__).parent.parent / "storage" / "trennkost_unknowns.log"


class Ontology:
    """In-memory food ontology with synonym lookup."""

    def __init__(self):
        self._entries: List[OntologyEntry] = []
        self._synonym_index: Dict[str, OntologyEntry] = {}  # lowercase → entry
        self._compounds: Dict[str, dict] = {}
        self._load_ontology()
        self._load_compounds()

    def _load_ontology(self):
        """Load ontology.csv and build synonym index."""
        if not ONTOLOGY_CSV.exists():
            logger.warning(f"Ontology file not found: {ONTOLOGY_CSV}")
            return

        with open(ONTOLOGY_CSV, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Skip comments
                if row.get("canonical", "").startswith("#"):
                    continue

                synonyms_raw = row.get("synonyms", "")
                synonyms = [s.strip() for s in synonyms_raw.split(",") if s.strip()]

                group_str = row.get("group", "UNKNOWN").strip()
                try:
                    group = FoodGroup(group_str)
                except ValueError:
                    group = FoodGroup.UNKNOWN

                subgroup_str = row.get("subgroup", "").strip()
                subgroup = None
                if subgroup_str:
                    try:
                        subgroup = FoodSubgroup(subgroup_str)
                    except ValueError:
                        pass

                entry = OntologyEntry(
                    canonical=row["canonical"].strip(),
                    synonyms=synonyms,
                    group=group,
                    subgroup=subgroup,
                    ambiguity_flag=row.get("ambiguity_flag", "false").lower() == "true",
                    ambiguity_note=row.get("ambiguity_note", "").strip() or None,
                    notes=row.get("notes", "").strip() or None,
                )
                self._entries.append(entry)

                # Index canonical name
                self._synonym_index[entry.canonical.lower()] = entry
                # Index all synonyms
                for syn in synonyms:
                    self._synonym_index[syn.lower()] = entry

        logger.info(f"Ontology loaded: {len(self._entries)} entries, {len(self._synonym_index)} synonyms")

    def _load_compounds(self):
        """Load compounds.json for compound dish lookup."""
        if not COMPOUNDS_JSON.exists():
            return
        with open(COMPOUNDS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
            self._compounds = data.get("compounds", {})
        logger.info(f"Compounds loaded: {len(self._compounds)} dishes")

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
                canonical=entry.canonical,
                group=entry.group,
                subgroup=entry.subgroup,
                confidence=0.7 if entry.ambiguity_flag else 1.0,
                assumed=assumed,
                assumption_reason=assumption_reason,
            )
        else:
            self._log_unknown(raw_name)
            return FoodItem(
                raw_name=raw_name,
                canonical=None,
                group=FoodGroup.UNKNOWN,
                subgroup=None,
                confidence=0.0,
                assumed=assumed,
                assumption_reason=assumption_reason,
            )

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


# Module-level singleton
_ontology: Optional[Ontology] = None


def get_ontology() -> Ontology:
    """Get or create the singleton Ontology instance."""
    global _ontology
    if _ontology is None:
        _ontology = Ontology()
    return _ontology
