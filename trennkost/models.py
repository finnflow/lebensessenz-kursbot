"""
Pydantic data models for the Trennkost rule engine.
"""
from __future__ import annotations
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


# ── Food Groups (from Kursmaterial Modul 1.1) ──────────────────────────

class FoodGroup(str, Enum):
    """
    Top-level food groups for Trennkost combination rules.
    Derived from Modul 1.1 "Optimale Lebensmittelkombinationen".
    """
    OBST = "OBST"                          # Fresh fruit
    TROCKENOBST = "TROCKENOBST"            # Dried fruit (dates, figs, raisins)
    NEUTRAL = "NEUTRAL"                    # Low-starch vegetables, salad, herbs, sprouts
    KH = "KH"                              # Complex carbs: grains, pseudocereals, starchy veg
    HUELSENFRUECHTE = "HUELSENFRUECHTE"    # Legumes (special rules)
    PROTEIN = "PROTEIN"                    # Animal protein: fish, meat, eggs
    MILCH = "MILCH"                        # Dairy products (separate from other protein)
    FETT = "FETT"                          # Fats: oils, nuts, avocado, butter
    UNKNOWN = "UNKNOWN"                    # Not in ontology


class CombinationGroup(str, Enum):
    """Target grouping model for future strict/vollwert combination logic."""
    FRUIT_WATERY = "FRUIT_WATERY"
    FRUIT_DENSE = "FRUIT_DENSE"
    DRIED_FRUIT = "DRIED_FRUIT"
    NEUTRAL = "NEUTRAL"
    KH = "KH"
    HUELSENFRUECHTE = "HUELSENFRUECHTE"
    PROTEIN = "PROTEIN"
    MILCH = "MILCH"
    FETT = "FETT"
    UNKNOWN = "UNKNOWN"


class FoodSubgroup(str, Enum):
    """Subgroups for finer-grained classification."""
    # OBST
    FRISCH = "FRISCH"
    BEEREN = "BEEREN"
    # TROCKENOBST
    TROCKEN = "TROCKEN"
    # NEUTRAL
    STAERKEARMES_GEMUESE = "STAERKEARMES_GEMUESE"
    SALAT = "SALAT"
    KRAEUTER = "KRAEUTER"
    SPROSSEN = "SPROSSEN"
    BLATTGRUEN = "BLATTGRUEN"              # Special: can combine with OBST (smoothie)
    ZWIEBEL_LAUCH = "ZWIEBEL_LAUCH"
    KREUZBLUETLER = "KREUZBLUETLER"
    # KH
    GETREIDE = "GETREIDE"
    PSEUDOGETREIDE = "PSEUDOGETREIDE"
    STAERKEHALTIGES_GEMUESE = "STAERKEHALTIGES_GEMUESE"
    # HUELSENFRUECHTE
    HUELSE = "HUELSE"
    # PROTEIN
    FLEISCH = "FLEISCH"
    FISCH = "FISCH"
    EIER = "EIER"
    # MILCH
    MILCHPRODUKT = "MILCHPRODUKT"
    KAESE = "KAESE"
    JOGHURT = "JOGHURT"
    FRISCHKAESE = "FRISCHKAESE"
    # FETT
    OEL = "OEL"
    NUSS_SAMEN = "NUSS_SAMEN"
    TIERISCHES_FETT = "TIERISCHES_FETT"
    # Extended ontology values
    SOJA = "SOJA"
    UNKNOWN = "UNKNOWN"


class RiskSeverity(str, Enum):
    YELLOW = "YELLOW"
    RED = "RED"


class TrafficLight(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


class EvaluationMode(str, Enum):
    STRICT = "strict"
    VOLLWERT = "light"
    # TODO(vollwert-mode): legacy "light" naming left in place intentionally; rename fully later without changing logic.
    LIGHT = "light"

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str) and value.strip().lower() == "vollwert":
            return cls.VOLLWERT
        return super()._missing_(value)


class ModifierTag(str, Enum):
    VEGAN = "VEGAN"
    VEGETARIAN = "VEGETARIAN"
    WITH_MEAT = "WITH_MEAT"
    WITH_FISH = "WITH_FISH"
    PREP_BREADED = "PREP_BREADED"
    PREP_NATUR = "PREP_NATUR"
    PREP_FRIED = "PREP_FRIED"
    HINT_CLASSIC = "HINT_CLASSIC"


# ── Verdict & Severity ─────────────────────────────────────────────────

class Verdict(str, Enum):
    OK = "OK"                    # Combination is fine
    NOT_OK = "NOT_OK"            # Combination violates rules
    CONDITIONAL = "CONDITIONAL"  # Depends on quantity/context/clarification
    UNKNOWN = "UNKNOWN"          # Cannot determine (unknown ingredients)


class Severity(str, Enum):
    CRITICAL = "CRITICAL"   # Hard rule violation (KH+Protein)
    WARNING = "WARNING"     # Soft violation or quantity-dependent
    INFO = "INFO"           # Informational (positive confirmation)


# ── Food Item (single ingredient) ──────────────────────────────────────

class FoodItem(BaseModel):
    """A single identified food item."""
    raw_name: str                              # Original name from user/vision
    item_id: Optional[str] = None
    canonical: Optional[str] = None            # Normalized name from ontology
    group: FoodGroup = FoodGroup.UNKNOWN
    subgroup: Optional[FoodSubgroup] = None
    food_family: Optional[str] = None
    group_strict: Optional[CombinationGroup] = None
    # TODO(vollwert-mode): legacy "light" naming left in place intentionally; rename fully later without changing logic.
    group_light: Optional[CombinationGroup] = None
    post_meal_wait_profile: Optional[str] = None
    modifier_policy: Optional[str] = None
    base_item_id: Optional[str] = None
    intrinsic_conflict_code: Optional[str] = None
    forced_components: List[str] = Field(default_factory=list)
    compound_type: Optional[str] = None
    decompose_for_logic: bool = False
    risk_codes: List[str] = Field(default_factory=list)
    guidance_codes: List[str] = Field(default_factory=list)
    high_fat: bool = False
    recognized_modifiers: List[ModifierTag] = Field(default_factory=list)
    confidence: float = 1.0                    # 0.0-1.0 mapping confidence
    assumed: bool = False                      # True if inferred (not explicitly stated)
    assumption_reason: Optional[str] = None    # Why it was assumed


# ── Dish Analysis (output of extraction+normalization) ─────────────────

class DishAnalysis(BaseModel):
    """Result of extracting and normalizing a dish's ingredients."""
    dish_name: str
    items: List[FoodItem] = Field(default_factory=list)
    unknown_items: List[str] = Field(default_factory=list)
    assumed_items: List[FoodItem] = Field(default_factory=list)


# ── Rule Engine Output ─────────────────────────────────────────────────

class RuleProblem(BaseModel):
    """A single rule violation or warning."""
    rule_id: str
    description: str
    severity: Severity
    affected_items: List[str]       # Human-readable: ["Pasta (KH)", "Ei (PROTEIN)"]
    affected_groups: List[str]      # Machine-readable: ["KH", "PROTEIN"]
    source_ref: str                 # Course material reference
    explanation: str                # From course material


class RequiredQuestion(BaseModel):
    """A question the user must answer for a definitive verdict."""
    question: str
    reason: str
    affects_items: List[str]


class GuidanceFact(BaseModel):
    """Structured guidance emitted alongside the deterministic verdict."""
    code: str
    affected_groups: List[str]
    affected_items: List[str]
    amount_hint: str
    fat_category: Optional[str] = None


class ItemRiskFact(BaseModel):
    """Structured risk metadata emitted alongside the deterministic verdict."""
    item: str
    risk_code: str
    severity: RiskSeverity
    title: Optional[str] = None
    description: Optional[str] = None


class TrennkostResult(BaseModel):
    """Final output of the rule engine."""
    dish_name: str
    verdict: Verdict                                        # Active-mode verdict for compatibility
    active_mode: EvaluationMode = EvaluationMode.STRICT
    strict_verdict: Verdict
    active_mode_verdict: Verdict
    mode_relaxation_applied: bool = False
    mode_delta_codes: List[str] = Field(default_factory=list)
    traffic_light: TrafficLight = TrafficLight.GREEN
    summary: str                                            # One-line human summary
    problems: List[RuleProblem] = Field(default_factory=list)
    required_questions: List[RequiredQuestion] = Field(default_factory=list)
    risk_codes: List[str] = Field(default_factory=list)
    risk_facts: List[ItemRiskFact] = Field(default_factory=list)
    guidance_codes: List[str] = Field(default_factory=list)
    guidance_facts: List[GuidanceFact] = Field(default_factory=list)
    ok_combinations: List[str] = Field(default_factory=list)  # What IS ok in this dish
    groups_found: Dict[str, List[str]] = Field(default_factory=dict)  # group → [items]
    strict_groups_found: Dict[str, List[str]] = Field(default_factory=dict)  # strict group → [items]
    debug: Optional[Dict[str, Any]] = None


# ── Rule Definition (loaded from rules.json) ───────────────────────────

class RuleCondition(BaseModel):
    """Condition for a rule to fire."""
    pair: Optional[List[str]] = None          # Both groups must be present
    group_present: Optional[str] = None       # Single group present
    has_unknown: Optional[bool] = None        # Unknown items exist
    has_assumed: Optional[bool] = None        # Assumed items exist
    except_subgroups: Optional[List[str]] = None  # Exception subgroups


class RuleDefinition(BaseModel):
    """A single rule loaded from rules.json."""
    rule_id: str
    description: str
    condition: RuleCondition
    verdict: Verdict
    severity: Severity
    source_ref: str
    explanation: str
    exception_note: Optional[str] = None


# ── Ontology Entry ─────────────────────────────────────────────────────

class OntologyEntry(BaseModel):
    """A single entry in the food ontology."""
    item_id: str
    canonical: str
    synonyms: List[str] = Field(default_factory=list)
    food_family: Optional[str] = None
    group: FoodGroup = FoodGroup.UNKNOWN
    subgroup: Optional[FoodSubgroup] = None
    group_strict: Optional[CombinationGroup] = None
    # TODO(vollwert-mode): legacy "light" naming left in place intentionally; rename fully later without changing logic.
    group_light: Optional[CombinationGroup] = None
    post_meal_wait_profile: Optional[str] = None
    modifier_policy: Optional[str] = None
    ambiguity_flag: bool = False
    ambiguity_note: Optional[str] = None
    base_item_id: Optional[str] = None
    intrinsic_conflict_code: Optional[str] = None
    forced_components: List[str] = Field(default_factory=list)
    compound_type: Optional[str] = None
    decompose_for_logic: bool = False
    risk_codes: List[str] = Field(default_factory=list)
    guidance_codes: List[str] = Field(default_factory=list)
    high_fat: bool = False  # True for Mayo, Aioli, Pesto — quantity-sensitive
    notes: Optional[str] = None


class WaitProfile(BaseModel):
    profile_id: str
    min_minutes: int
    max_minutes: int
    description: str


class RiskProfile(BaseModel):
    code: str
    severity: RiskSeverity
    title: str
    description: str


class GuidanceProfile(BaseModel):
    code: str
    title: str
    description: str
