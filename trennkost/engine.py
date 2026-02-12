"""
Deterministic Trennkost Rule Engine.

Takes a DishAnalysis (extracted + normalized items) and applies rules from rules.json.
NO LLM calls. Pure logic.
"""
import json
import logging
from pathlib import Path
from typing import List, Dict, Set, Optional, Tuple
from collections import defaultdict

from trennkost.models import (
    FoodGroup,
    FoodSubgroup,
    Verdict,
    Severity,
    FoodItem,
    DishAnalysis,
    RuleProblem,
    RequiredQuestion,
    TrennkostResult,
    RuleDefinition,
    RuleCondition,
)

logger = logging.getLogger(__name__)

RULES_JSON = Path(__file__).parent / "data" / "rules.json"

# Subgroups that are OK in smoothies (for smoothie exception)
# BLATTGRUEN is the main component, KRAEUTER (spices/herbs/water) are neutral
SMOOTHIE_SAFE_SUBGROUPS = {
    FoodSubgroup.BLATTGRUEN,
    FoodSubgroup.KRAEUTER,  # Spices, herbs, water don't affect digestion
}


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

    def evaluate(self, analysis: DishAnalysis) -> TrennkostResult:
        """
        Evaluate a DishAnalysis against all rules.

        Returns TrennkostResult with verdict, problems, and required questions.
        """
        all_items = analysis.items + analysis.assumed_items

        # ── Build group sets ────────────────────────────────────────
        groups_found: Dict[str, List[str]] = defaultdict(list)
        subgroups_found: Dict[str, Set[FoodSubgroup]] = defaultdict(set)

        for item in all_items:
            label = f"{item.raw_name}"
            if item.canonical and item.canonical != item.raw_name:
                label = f"{item.raw_name} → {item.canonical}"
            groups_found[item.group.value].append(label)
            if item.subgroup:
                subgroups_found[item.group.value].add(item.subgroup)

        group_set = set(groups_found.keys())
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
                rule, group_set, subgroups_found, groups_found,
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
                        for item_label in groups_found.get(g, []):
                            affected_items.append(f"{item_label} ({g})")
                    triggered_pairs.add(tuple(sorted(detail["pair"])))
                elif detail.get("group"):
                    g = detail["group"]
                    affected_groups.append(g)
                    for item_label in groups_found.get(g, []):
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
        # Zucker (refined white sugar) is Trennkost-conform but not recommended
        zucker_items = [
            item for item in all_items
            if item.canonical and item.canonical.lower() == "zucker"
        ]
        if zucker_items:
            zucker_labels = [f"{item.raw_name} → Zucker" for item in zucker_items]
            problems.append(RuleProblem(
                rule_id="H001",  # H = Health recommendation (not Trennkost rule)
                description="Zucker (weißer Industriezucker) sollte vermieden werden",
                severity=Severity.INFO,
                affected_items=zucker_labels,
                affected_groups=["KH"],
                source_ref="modul-1.1,modul-1.2",
                explanation="Zucker ist zwar Trennkost-konform als Kohlenhydrat, wird aber im Kursmaterial als schädlich beschrieben. Besser: Honig, Ahornsirup oder Kokosblütenzucker verwenden.",
            ))

        # ── Check for multiple PROTEIN subgroups (R018) ─────────────
        # Different protein sources (FLEISCH, FISCH, EIER) should not be combined
        protein_subgroups = subgroups_found.get("PROTEIN", set())
        if len(protein_subgroups) >= 2:
            # Group items by subgroup to show which protein types are mixed
            subgroup_items = defaultdict(list)
            for item in all_items:
                if item.group == FoodGroup.PROTEIN and item.subgroup:
                    label = f"{item.raw_name}"
                    if item.canonical and item.canonical != item.raw_name:
                        label = f"{item.raw_name} → {item.canonical}"
                    subgroup_items[item.subgroup.value].append(label)

            # Build affected items list showing subgroups
            affected_items = []
            for subgroup in sorted(subgroup_items.keys()):
                for item in subgroup_items[subgroup]:
                    affected_items.append(f"{item} ({subgroup})")

            problems.append(RuleProblem(
                rule_id="R018",
                description="Verschiedene Proteinquellen nicht kombinieren",
                severity=Severity.CRITICAL,
                affected_items=affected_items,
                affected_groups=["PROTEIN"],
                source_ref="modul-1.1/page-004,modul-1.1/page-001",
                explanation="Pro Mahlzeit sollte nur EINE Art von konzentriertem Lebensmittel gewählt werden. Fisch/Fleisch/Eier sind unterschiedliche Proteinquellen und sollten nicht miteinander kombiniert werden. Das Verdauungssystem ist nicht dafür geschaffen, mehr als ein konzentriertes Lebensmittel gleichzeitig zu verdauen.",
            ))

        # ── Build required questions ────────────────────────────────
        required_questions = self._build_questions(
            analysis, groups_found, has_unknown, has_assumed
        )

        # ── Determine final verdict ─────────────────────────────────
        verdict = self._determine_verdict(problems, required_questions, has_unknown)

        # ── Build summary ───────────────────────────────────────────
        summary = self._build_summary(analysis.dish_name, verdict, problems, required_questions)

        return TrennkostResult(
            dish_name=analysis.dish_name,
            verdict=verdict,
            summary=summary,
            problems=problems,
            required_questions=required_questions,
            ok_combinations=ok_notes,
            groups_found=dict(groups_found),
            debug={
                "rules_checked": len(self.rules),
                "rules_triggered": len(problems) + len(ok_notes),
                "unknown_items": analysis.unknown_items,
                "assumed_items": [it.raw_name for it in analysis.assumed_items],
                "group_set": sorted(group_set),
            },
        )

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
                if g1 in group_set and len(groups_found.get(g1, [])) >= 2:
                    pair_key = tuple(sorted([g1, g2]))
                    if pair_key not in triggered_pairs:
                        return True, {"pair": [g1, g2]}
                return False, {}

            # Check if both groups present
            if g1 not in group_set or g2 not in group_set:
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
                neutral_subs = subgroups_found.get("NEUTRAL", set())
                if neutral_subs and neutral_subs.issubset(allowed_subs):
                    return True, {"pair": [g1, g2]}
                return False, {}

            # For R013 (OBST + NEUTRAL without exception): only fire if NOT all smoothie-safe
            if rule.rule_id == "R013":
                neutral_subs = subgroups_found.get("NEUTRAL", set())
                if neutral_subs and neutral_subs.issubset(SMOOTHIE_SAFE_SUBGROUPS):
                    return False, {}  # R012 handles this case (smoothie exception)

            return True, {"pair": [g1, g2]}

        # ── Single group check ──────────────────────────────────────
        if cond.group_present:
            if cond.group_present in group_set:
                return True, {"group": cond.group_present}
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

        # Fat quantity question
        if "FETT" in groups_found and len(groups_found) > 1:
            fett_items = groups_found["FETT"]
            other_concentrated = set(groups_found.keys()) - {"FETT", "NEUTRAL", "UNKNOWN"}
            if other_concentrated:
                questions.append(RequiredQuestion(
                    question=f"Wie viel Fett ({', '.join(fett_items)}) ist enthalten? Kleine Mengen (1-2 TL) sind mit allem OK, größere nur mit Gemüse/Salat.",
                    reason="Die Fettmenge beeinflusst die Bewertung.",
                    affects_items=fett_items,
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
        has_not_ok = any(p.rule_id.startswith("R0") and p.severity == Severity.CRITICAL for p in problems)

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
                group_str = " + ".join(sorted(groups))
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


def evaluate_dish(analysis: DishAnalysis) -> TrennkostResult:
    """Convenience: evaluate a DishAnalysis using the singleton engine."""
    return get_engine().evaluate(analysis)
