"""
Deterministic Trennkost Rule Engine.

Takes a DishAnalysis (extracted + normalized items) and applies rules from rules.json.
NO LLM calls. Pure logic.
"""
import json
import logging
from pathlib import Path
from typing import List, Dict, Set, Optional, Tuple, Union
from collections import defaultdict

from trennkost.models import (
    CombinationGroup,
    EvaluationMode,
    FoodGroup,
    FoodSubgroup,
    RiskSeverity,
    TrafficLight,
    Verdict,
    Severity,
    FoodItem,
    DishAnalysis,
    ItemRiskFact,
    RuleProblem,
    RequiredQuestion,
    GuidanceFact,
    TrennkostResult,
    RuleDefinition,
    RuleCondition,
)
from trennkost.ontology import (
    STRICT_FRUIT_GROUPS,
    combination_group_to_display_group,
    get_ontology,
    resolve_combination_group,
)
from trennkost.health_recommendations import build_health_recommendation_problems
from trennkost.protein_rules import build_r018_mixed_protein_problem


def build_r_fried_problem(all_items: List[FoodItem]) -> Optional[RuleProblem]:
    fried_items = [item for item in all_items if "FRIED" in item.risk_codes]
    if not fried_items:
        return None
    affected = [
        f"{item.raw_name} → {item.canonical}" if item.canonical else item.raw_name
        for item in fried_items
    ]
    return RuleProblem(
        rule_id="R_FRIED",
        description="Frittierte Zubereitung — hohe Fettlast",
        severity=Severity.CRITICAL,
        affected_items=affected,
        affected_groups=["KH"],
        source_ref="modul-1.1",
        explanation=(
            "Frittierte Lebensmittel haben eine extreme Fettlast und sind "
            "im Trennkost-System grundsätzlich nicht empfohlen."
        ),
    )

logger = logging.getLogger(__name__)

RULES_JSON = Path(__file__).parent / "data" / "rules.json"

# Subgroups that are OK in smoothies (for smoothie exception)
# BLATTGRUEN is the main component, KRAEUTER (spices/herbs/water) are neutral
SMOOTHIE_SAFE_SUBGROUPS = {
    FoodSubgroup.BLATTGRUEN,
    FoodSubgroup.KRAEUTER,  # Spices, herbs, water don't affect digestion
}

FAT_GUIDANCE_NEUTRAL_SMALL_AMOUNT = "FAT_WITH_NEUTRAL_SMALL_AMOUNT"
FAT_GUIDANCE_CONFLICT_TINY_AMOUNT = "FAT_WITH_CONFLICT_GROUP_TINY_AMOUNT"
FAT_OIL_BUTTER_SUBGROUPS = {
    FoodSubgroup.OEL,
    FoodSubgroup.TIERISCHES_FETT,
}
FAT_FOOD_SUBGROUPS = {
    FoodSubgroup.NUSS_SAMEN,
}
CONCENTRATED_NON_FRUIT_GROUPS = {
    CombinationGroup.KH.value,
    CombinationGroup.PROTEIN.value,
    CombinationGroup.HUELSENFRUECHTE.value,
    CombinationGroup.MILCH.value,
}

SUMMARY_GROUP_LABELS = {
    CombinationGroup.FRUIT_WATERY.value: "wasserreiches Obst",
    CombinationGroup.FRUIT_DENSE.value: "dichtes Obst",
    CombinationGroup.DRIED_FRUIT.value: "Trockenobst",
    CombinationGroup.NEUTRAL.value: "stärkearmes Gemüse/Salat",
    CombinationGroup.KH.value: "Kohlenhydrate",
    CombinationGroup.HUELSENFRUECHTE.value: "Hülsenfrüchte",
    CombinationGroup.PROTEIN.value: "Proteine",
    CombinationGroup.MILCH.value: "Milchprodukte",
    CombinationGroup.FETT.value: "Fette",
}

# TODO(vollwert-mode): legacy "light" naming left in place intentionally; rename fully later without changing logic.
VOLLWERT_MODE_RELAXATION_CODE = "LIGHT_MODE_RELAXED"


class TrennkostEngine:
    """Deterministic rule engine for food combination checking."""

    def __init__(self):
        self.rules: List[RuleDefinition] = []
        self.rule_priority: List[str] = []
        self._load_rules()

    def _load_rules(self):
        """Load rules from rules.json."""
        if not RULES_JSON.exists():
            logger.error(f"Rules file not found: {RULES_JSON}")
            return

        with open(RULES_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)

        for r in data.get("rules", []):
            rule = RuleDefinition(
                rule_id=r["rule_id"],
                description=r["description"],
                condition=RuleCondition(**r["condition"]),
                verdict=Verdict(r["verdict"]),
                severity=Severity(r["severity"]),
                source_ref=r["source_ref"],
                explanation=r["explanation"],
                exception_note=r.get("exception_note"),
            )
            self.rules.append(rule)

        self.rule_priority = data.get("rule_priority", [r.rule_id for r in self.rules])
        logger.info(f"Loaded {len(self.rules)} rules")

    def evaluate(
        self,
        analysis: DishAnalysis,
        mode: Union[str, EvaluationMode] = EvaluationMode.STRICT,
    ) -> TrennkostResult:
        """
        Evaluate a DishAnalysis against all rules.

        Returns TrennkostResult with verdict, problems, and required questions.
        """
        active_mode = mode if isinstance(mode, EvaluationMode) else EvaluationMode(mode)
        all_items = analysis.items + analysis.assumed_items

        strict_result = self._evaluate_mode(analysis, mode=EvaluationMode.STRICT)
        active_result = (
            strict_result
            if active_mode == EvaluationMode.STRICT
            else self._evaluate_mode(analysis, mode=active_mode)
        )

        # ── Build structured risk / ampel ───────────────────────────
        risk_facts = self._build_risk_facts(all_items)
        risk_codes = list(dict.fromkeys(fact.risk_code for fact in risk_facts))
        traffic_light = self._aggregate_traffic_light(risk_facts)

        mode_relaxation_applied = (
            active_mode == EvaluationMode.VOLLWERT
            and active_result["verdict"] != strict_result["verdict"]
        )
        mode_delta_codes = [VOLLWERT_MODE_RELAXATION_CODE] if mode_relaxation_applied else []

        return TrennkostResult(
            dish_name=analysis.dish_name,
            verdict=active_result["verdict"],
            active_mode=active_mode,
            strict_verdict=strict_result["verdict"],
            active_mode_verdict=active_result["verdict"],
            mode_relaxation_applied=mode_relaxation_applied,
            mode_delta_codes=mode_delta_codes,
            traffic_light=traffic_light,
            summary=active_result["summary"],
            problems=active_result["problems"],
            health_hints=active_result.get("health_hints", []),
            required_questions=active_result["required_questions"],
            risk_codes=risk_codes,
            risk_facts=risk_facts,
            guidance_codes=active_result["guidance_codes"],
            guidance_facts=active_result["guidance_facts"],
            ok_combinations=active_result["ok_notes"],
            groups_found=active_result["display_groups_found"],
            strict_groups_found=strict_result["combination_groups_found"],
            debug={
                "rules_checked": len(self.rules),
                "rules_triggered": active_result["rules_triggered"],
                "unknown_items": analysis.unknown_items,
                "assumed_items": [it.raw_name for it in analysis.assumed_items],
                "group_set": sorted(active_result["group_set"]),
                "display_group_set": sorted(active_result["display_groups_found"].keys()),
                "strict_group_set": sorted(strict_result["group_set"]),
                "active_mode": active_mode.value,
                "strict_verdict": strict_result["verdict"].value,
                "active_mode_verdict": active_result["verdict"].value,
                "mode_delta_codes": mode_delta_codes,
                "traffic_light": traffic_light.value,
                "risk_codes": risk_codes,
                "guidance_codes": active_result["guidance_codes"],
            },
        )

    def _evaluate_mode(
        self,
        analysis: DishAnalysis,
        mode: EvaluationMode,
    ) -> Dict[str, object]:
        all_items = analysis.items + analysis.assumed_items

        # ── Build group sets ────────────────────────────────────────
        display_groups_found: Dict[str, List[str]] = defaultdict(list)
        combination_groups_found: Dict[str, List[str]] = defaultdict(list)
        subgroups_found: Dict[str, Set[FoodSubgroup]] = defaultdict(set)

        for item in all_items:
            combination_group = resolve_combination_group(item, mode=mode)
            display_group = combination_group_to_display_group(combination_group, fallback=item.group)
            label = self._format_item_label(item)
            combination_groups_found[combination_group.value].append(label)
            display_groups_found[display_group.value].append(label)
            if item.subgroup:
                subgroups_found[combination_group.value].add(item.subgroup)

        group_set = set(combination_groups_found.keys())
        has_unknown = bool(analysis.unknown_items)
        has_assumed = bool(analysis.assumed_items)

        # ── Check rules in priority order ───────────────────────────
        problems: List[RuleProblem] = []
        ok_notes: List[str] = []
        triggered_pairs: Set[Tuple[str, str]] = set()  # Track which pairs already handled

        for rule_id in self.rule_priority:
            rule = self._get_rule(rule_id)
            if rule is None:
                continue

            fired, detail = self._check_rule(
                rule, group_set, subgroups_found, display_groups_found,
                combination_groups_found,
                has_unknown, has_assumed, triggered_pairs
            )

            if not fired:
                continue

            if rule.verdict == Verdict.OK:
                ok_notes.append(f"{rule.description}")
                if detail.get("pair"):
                    triggered_pairs.add(tuple(sorted(detail["pair"])))
            elif rule.verdict in (Verdict.NOT_OK, Verdict.CONDITIONAL):
                affected_items = []
                affected_groups = []
                if detail.get("pair"):
                    for g in detail["pair"]:
                        affected_groups.append(g)
                        for item_label in combination_groups_found.get(g, []):
                            affected_items.append(f"{item_label} ({g})")
                    triggered_pairs.add(tuple(sorted(detail["pair"])))
                elif detail.get("group"):
                    matched_groups = detail.get("matched_groups") or [detail["group"]]
                    for g in matched_groups:
                        affected_groups.append(g)
                        for item_label in combination_groups_found.get(g, []):
                            affected_items.append(f"{item_label} ({g})")

                problems.append(RuleProblem(
                    rule_id=rule.rule_id,
                    description=rule.description,
                    severity=rule.severity,
                    affected_items=affected_items,
                    affected_groups=affected_groups,
                    source_ref=rule.source_ref,
                    explanation=rule.explanation,
                ))

        # ── Special health recommendations (not Trennkost rules) ────
        health_hints = build_health_recommendation_problems(all_items)

        # ── Special deterministic protein rules ─────────────────────
        r018_problem = build_r018_mixed_protein_problem(all_items, mode=mode)
        if r018_problem is not None:
            problems.append(r018_problem)

        # ── Fried food verdict ───────────────────────────────────────
        r_fried = build_r_fried_problem(all_items)
        if r_fried is not None:
            problems.append(r_fried)

        # ── Build required questions ────────────────────────────────
        required_questions = self._build_questions(
            analysis, display_groups_found, has_unknown, has_assumed
        )

        # ── Build structured guidance ───────────────────────────────
        fat_guidance_facts = self._build_guidance(analysis, combination_groups_found, mode=mode)
        profile_guidance_facts = self._build_profile_guidance_facts(
            all_items=all_items,
            mode=mode,
            existing_fat_guidance=bool(fat_guidance_facts),
        )
        guidance_facts = fat_guidance_facts + profile_guidance_facts
        guidance_codes = list(dict.fromkeys(fact.code for fact in guidance_facts))

        # ── Determine final verdict ─────────────────────────────────
        verdict = self._determine_verdict(problems, required_questions, has_unknown)

        # ── Build summary ───────────────────────────────────────────
        summary = self._build_summary(analysis.dish_name, verdict, problems, required_questions)
        return {
            "verdict": verdict,
            "summary": summary,
            "problems": problems,
            "health_hints": health_hints,
            "required_questions": required_questions,
            "guidance_codes": guidance_codes,
            "guidance_facts": guidance_facts,
            "ok_notes": ok_notes,
            "display_groups_found": dict(display_groups_found),
            "combination_groups_found": dict(combination_groups_found),
            "group_set": group_set,
            "rules_triggered": len(problems) + len(ok_notes),
        }

    def _get_rule(self, rule_id: str) -> Optional[RuleDefinition]:
        for r in self.rules:
            if r.rule_id == rule_id:
                return r
        return None

    def _check_rule(
        self,
        rule: RuleDefinition,
        group_set: Set[str],
        subgroups_found: Dict[str, Set[FoodSubgroup]],
        groups_found: Dict[str, List[str]],
        strict_groups_found: Dict[str, List[str]],
        has_unknown: bool,
        has_assumed: bool,
        triggered_pairs: Set[Tuple[str, str]],
    ) -> Tuple[bool, dict]:
        """
        Check if a rule fires.
        Returns (fired: bool, detail: dict with context).
        """
        cond = rule.condition

        # ── Pair check ──────────────────────────────────────────────
        if cond.pair:
            g1, g2 = cond.pair[0], cond.pair[1]

            # Same-group pair (e.g. KH+KH) → check if multiple items in that group
            if g1 == g2:
                matched = self._matching_groups(group_set, g1)
                if len(matched) == 1 and len(strict_groups_found.get(next(iter(matched)), [])) >= 2:
                    pair_key = tuple(sorted([g1, g2]))
                    if pair_key not in triggered_pairs:
                        return True, {"pair": sorted(matched)}
                return False, {}

            matched_g1 = self._matching_groups(group_set, g1)
            matched_g2 = self._matching_groups(group_set, g2)

            # Check if both groups present
            if not matched_g1 or not matched_g2:
                return False, {}

            pair_key = tuple(sorted([g1, g2]))

            # Already handled by a higher-priority rule?
            if pair_key in triggered_pairs:
                return False, {}

            # ── Smoothie exception: OBST + NEUTRAL ──────────────────
            # R012 checks if NEUTRAL items are ALL BLATTGRUEN → OK
            # R013 fires if NOT all BLATTGRUEN → NOT_OK
            if cond.except_subgroups:
                # This is R012: OBST + NEUTRAL where NEUTRAL is BLATTGRUEN
                allowed_subs = {FoodSubgroup(s) for s in cond.except_subgroups}
                neutral_subs = subgroups_found.get(CombinationGroup.NEUTRAL.value, set())
                if neutral_subs and neutral_subs.issubset(allowed_subs):
                    return True, {"pair": sorted(matched_g1 | matched_g2)}
                return False, {}

            # For R013 (OBST + NEUTRAL without exception): only fire if NOT all smoothie-safe
            if rule.rule_id == "R013":
                neutral_subs = subgroups_found.get(CombinationGroup.NEUTRAL.value, set())
                if neutral_subs and neutral_subs.issubset(SMOOTHIE_SAFE_SUBGROUPS):
                    return False, {}  # R012 handles this case (smoothie exception)

            return True, {"pair": sorted(matched_g1 | matched_g2)}

        # ── Single group check ──────────────────────────────────────
        if cond.group_present:
            matched = self._matching_groups(group_set, cond.group_present)
            if matched:
                return True, {"group": cond.group_present, "matched_groups": sorted(matched)}
            return False, {}

        # ── Unknown check ───────────────────────────────────────────
        if cond.has_unknown is not None:
            if cond.has_unknown == has_unknown:
                return True, {"unknown": True}
            return False, {}

        # ── Assumed check ───────────────────────────────────────────
        if cond.has_assumed is not None:
            if cond.has_assumed == has_assumed:
                return True, {"assumed": True}
            return False, {}

        return False, {}

    def _matching_groups(self, group_set: Set[str], rule_token: str) -> Set[str]:
        """Resolve which strict evaluation groups satisfy a rule token."""
        if rule_token == FoodGroup.OBST.value:
            return {
                group for group in group_set
                if group in {strict_group.value for strict_group in STRICT_FRUIT_GROUPS}
            }

        if rule_token == FoodGroup.TROCKENOBST.value:
            return {
                group for group in group_set
                if group == CombinationGroup.DRIED_FRUIT.value
            }

        return {group for group in group_set if group == rule_token}

    def _build_risk_facts(self, all_items: List[FoodItem]) -> List[ItemRiskFact]:
        """Build structured item-level risk facts from ontology metadata."""
        ontology = get_ontology()
        risk_profiles = ontology.risk_profiles
        facts: List[ItemRiskFact] = []

        for item in all_items:
            for risk_code in item.risk_codes:
                profile = risk_profiles.get(risk_code)
                if not profile:
                    logger.warning("Ignoring unknown risk code '%s' on item '%s'", risk_code, item.raw_name)
                    continue
                facts.append(ItemRiskFact(
                    item=self._format_item_label(item),
                    risk_code=risk_code,
                    severity=profile.severity,
                    title=profile.title,
                    description=profile.description,
                ))

        return facts

    def _aggregate_traffic_light(self, risk_facts: List[ItemRiskFact]) -> TrafficLight:
        if any(fact.severity == RiskSeverity.RED for fact in risk_facts):
            return TrafficLight.RED
        if any(fact.severity == RiskSeverity.YELLOW for fact in risk_facts):
            return TrafficLight.YELLOW
        return TrafficLight.GREEN

    def _build_guidance(
        self,
        analysis: DishAnalysis,
        groups_found: Dict[str, List[str]],
        mode: EvaluationMode = EvaluationMode.STRICT,
    ) -> List[GuidanceFact]:
        """Build structured, verdict-independent guidance facts."""
        all_items = analysis.items + analysis.assumed_items
        fat_items = [
            item for item in all_items
            if resolve_combination_group(item, mode=mode) == CombinationGroup.FETT
        ]
        if not fat_items:
            return []

        group_set = set(groups_found.keys())
        if group_set & {strict_group.value for strict_group in STRICT_FRUIT_GROUPS}:
            return []

        concentrated_groups = sorted(group_set & CONCENTRATED_NON_FRUIT_GROUPS)
        if concentrated_groups:
            return [GuidanceFact(
                code=FAT_GUIDANCE_CONFLICT_TINY_AMOUNT,
                affected_groups=["FETT", *concentrated_groups],
                affected_items=[self._format_item_label(item) for item in fat_items],
                amount_hint="max. ca. 1-2 TL",
                fat_category="ANY_FAT",
            )]

        if "NEUTRAL" not in group_set or not group_set.issubset({"FETT", "NEUTRAL"}):
            return []

        oil_butter_items = []
        fat_food_items = []
        condiment_items = []

        for item in fat_items:
            category = self._classify_fat_guidance_category(item)
            label = self._format_item_label(item)
            if category == "OIL_BUTTER":
                oil_butter_items.append(label)
            elif category == "NUT_SEED_AVOCADO":
                fat_food_items.append(label)
            else:
                condiment_items.append(label)

        facts: List[GuidanceFact] = []
        if oil_butter_items:
            facts.append(GuidanceFact(
                code=FAT_GUIDANCE_NEUTRAL_SMALL_AMOUNT,
                affected_groups=["FETT", "NEUTRAL"],
                affected_items=oil_butter_items,
                amount_hint="ca. 1-2 EL",
                fat_category="OIL_BUTTER",
            ))
        if fat_food_items:
            facts.append(GuidanceFact(
                code=FAT_GUIDANCE_NEUTRAL_SMALL_AMOUNT,
                affected_groups=["FETT", "NEUTRAL"],
                affected_items=fat_food_items,
                amount_hint="bis ca. 1/2 Tasse",
                fat_category="NUT_SEED_AVOCADO",
            ))
        if condiment_items:
            facts.append(GuidanceFact(
                code=FAT_GUIDANCE_NEUTRAL_SMALL_AMOUNT,
                affected_groups=["FETT", "NEUTRAL"],
                affected_items=condiment_items,
                amount_hint="ca. 1-2 EL",
                fat_category="CONDIMENT",
            ))

        return facts

    def _classify_fat_guidance_category(self, item: FoodItem) -> str:
        if item.high_fat or item.modifier_policy == "CONDIMENT_ONLY":
            return "CONDIMENT"
        if item.subgroup in FAT_OIL_BUTTER_SUBGROUPS:
            return "OIL_BUTTER"
        if item.subgroup in FAT_FOOD_SUBGROUPS:
            return "NUT_SEED_AVOCADO"
        return "CONDIMENT"

    def _format_item_label(self, item: FoodItem) -> str:
        if item.canonical and item.canonical != item.raw_name:
            return f"{item.raw_name} → {item.canonical}"
        return item.raw_name

    def _build_profile_guidance_facts(
        self,
        all_items: List[FoodItem],
        mode: EvaluationMode,
        existing_fat_guidance: bool = False,
    ) -> List[GuidanceFact]:
        """
        Translate ontology guidance codes into structured guidance facts.
        """
        ontology = get_ontology()
        guidance_profiles = ontology.guidance_profiles
        grouped: Dict[str, Dict[str, object]] = {}

        for item in all_items:
            item_group = resolve_combination_group(item, mode=mode)
            # Fat-only combos already use the dedicated synthetic fat guidance path.
            if existing_fat_guidance and item_group == CombinationGroup.FETT:
                continue

            label = self._format_item_label(item)
            for code in item.guidance_codes:
                profile = guidance_profiles.get(code)
                if not profile:
                    logger.warning("Ignoring unknown guidance code '%s' on item '%s'", code, item.raw_name)
                    continue

                bucket = grouped.setdefault(
                    code,
                    {
                        "groups": set(),
                        "items": [],
                        "hint": profile.title,
                    },
                )
                bucket["groups"].add(item_group.value)
                if label not in bucket["items"]:
                    bucket["items"].append(label)

        facts: List[GuidanceFact] = []
        for code, bucket in grouped.items():
            facts.append(
                GuidanceFact(
                    code=code,
                    affected_groups=sorted(bucket["groups"]),
                    affected_items=bucket["items"],
                    amount_hint=bucket["hint"],
                )
            )
        return facts

    def _build_questions(
        self,
        analysis: DishAnalysis,
        groups_found: Dict[str, List[str]],
        has_unknown: bool,
        has_assumed: bool,
    ) -> List[RequiredQuestion]:
        """Build clarification questions."""
        questions = []

        # Unknown items
        if has_unknown:
            questions.append(RequiredQuestion(
                question=f"Folgende Zutaten konnte ich nicht eindeutig zuordnen: {', '.join(analysis.unknown_items)}. Kannst du diese näher beschreiben?",
                reason="Unbekannte Zutaten verhindern eine vollständige Bewertung.",
                affects_items=analysis.unknown_items,
            ))

        # Assumed items
        if has_assumed:
            assumed_names = [it.raw_name for it in analysis.assumed_items]
            questions.append(RequiredQuestion(
                question=f"Ich vermute folgende zusätzliche Zutaten: {', '.join(assumed_names)}. Stimmt das?",
                reason="Vermutete Zutaten müssen bestätigt werden für eine sichere Bewertung.",
                affects_items=assumed_names,
            ))

        # Ambiguous items
        from trennkost.ontology import get_ontology
        ontology = get_ontology()
        all_items = analysis.items + analysis.assumed_items
        ambiguous = ontology.get_ambiguous_entries(all_items)
        for item, note in ambiguous:
            questions.append(RequiredQuestion(
                question=f"'{item.raw_name}' ist mehrdeutig: {note}",
                reason="Mehrdeutige Zutat erfordert Klärung für korrekte Zuordnung.",
                affects_items=[item.raw_name],
            ))

        # Compound clarification - but ONLY if no explicit ingredients provided
        # If user said "Burger mit Tempeh, Salat", they already answered the clarification
        compound = ontology.get_compound(analysis.dish_name)
        has_explicit_items = len(analysis.items) > 0 and not all(item.assumed for item in analysis.items)
        if compound and compound.get("needs_clarification") and not has_explicit_items:
            questions.append(RequiredQuestion(
                question=compound["needs_clarification"],
                reason="Details zum Gericht nötig für vollständige Analyse.",
                affects_items=[analysis.dish_name],
            ))

        return questions

    def _determine_verdict(
        self,
        problems: List[RuleProblem],
        questions: List[RequiredQuestion],
        has_unknown: bool,
    ) -> Verdict:
        """
        Determine final verdict from problems and questions.

        Priority: NOT_OK > CONDITIONAL > UNKNOWN > OK
        """
        has_critical = any(p.severity == Severity.CRITICAL for p in problems)
        has_not_ok = any(
            (p.rule_id.startswith("R0") or p.rule_id == "R_FRIED") and p.severity == Severity.CRITICAL
            for p in problems
        )

        if has_not_ok:
            return Verdict.NOT_OK

        if questions or has_unknown:
            return Verdict.CONDITIONAL

        has_warning = any(p.severity == Severity.WARNING for p in problems)
        if has_warning:
            return Verdict.CONDITIONAL

        return Verdict.OK

    def _build_summary(
        self,
        dish_name: str,
        verdict: Verdict,
        problems: List[RuleProblem],
        questions: List[RequiredQuestion],
    ) -> str:
        """Build a one-line human-readable summary."""
        if verdict == Verdict.OK:
            return f"{dish_name}: Kombination ist OK nach Trennkost-Prinzip."

        if verdict == Verdict.NOT_OK:
            critical = [p for p in problems if p.severity == Severity.CRITICAL]
            if critical:
                groups = set()
                for p in critical:
                    groups.update(p.affected_groups)
                group_str = " + ".join(
                    SUMMARY_GROUP_LABELS.get(group, group) for group in sorted(groups)
                )
                return f"{dish_name}: NICHT OK — {group_str} sollten nicht kombiniert werden."
            return f"{dish_name}: NICHT OK nach Trennkost-Prinzip."

        if verdict == Verdict.CONDITIONAL:
            if questions:
                return f"{dish_name}: Bedingt OK — Rückfragen nötig ({len(questions)} offene Fragen)."
            return f"{dish_name}: Bedingt OK — hängt von Mengen/Details ab."

        return f"{dish_name}: Kann nicht sicher bewertet werden (unbekannte Zutaten)."


# Module-level singleton
_engine: Optional[TrennkostEngine] = None


def get_engine() -> TrennkostEngine:
    """Get or create the singleton engine instance."""
    global _engine
    if _engine is None:
        _engine = TrennkostEngine()
    return _engine


def evaluate_dish(
    analysis: DishAnalysis,
    mode: Union[str, EvaluationMode] = EvaluationMode.STRICT,
) -> TrennkostResult:
    """Convenience: evaluate a DishAnalysis using the singleton engine."""
    return get_engine().evaluate(analysis, mode=mode)
