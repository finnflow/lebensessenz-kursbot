"""
Prompt builder for the chat service.

All prompt templates and assembly logic extracted from the monolithic handle_chat().
SYSTEM_INSTRUCTIONS lives here; mode-specific builders compose the user-side prompt.
"""
from typing import Optional, List, Dict, Any

from trennkost.models import TrennkostResult, Verdict
from trennkost.analyzer import format_results_for_llm


FALLBACK_SENTENCE = "Diese Information steht nicht im bereitgestellten Kursmaterial."

SYSTEM_INSTRUCTIONS = f"""Du bist ein kurs-assistierender Bot.

ANREDE: Sprich den User IMMER mit "du" an (informell, freundlich). Verwende NIEMALS "Sie" außer der User wünscht dies explizit.

WICHTIGE REGELN:
1. FAKTENBASIS: Antworte ausschließlich basierend auf den bereitgestellten KURS-SNIPPETS.
2. CHAT-KONTEXT: Nutze die Konversationshistorie nur für Referenzen und Disambiguierung (z.B. "das", "wie vorhin", "und noch").
3. GRENZEN: Wenn die Information NICHT in den Kurs-Snippets steht, sag klar: "{FALLBACK_SENTENCE}"
   AUSNAHMEN (verwende NIEMALS Fallback bei):
   - Follow-up-Antworten auf deine eigenen Fragen (z.B. "den Rotbarsch" nach "Was möchtest du behalten?")
   - Bild-Referenzen (z.B. "du siehst ja den Teller")
   - Rezept-Requests (z.B. "gib mir ein Gericht", "hast du ein Rezept")
     → KRITISCH: Wenn eine KURATIERTE REZEPTDATENBANK im Kontext steht, verwende DIESE Rezepte!
     → Schlage SOFORT ein passendes Rezept vor — VERBOT: frage NIEMALS nach Zutaten!
   - Zusätzliche Details auf Rückfragen (z.B. "Hafermilch, wenig Zucker" nach "Welche Zutaten?")
   - Korrekturen/Klarstellungen des Users (z.B. "aber ich hab doch X gesagt", "nein, ich meinte Y", "keine X, nur Y")
4. BEGRIFFS-ALIAS (wichtig): NUR wenn der USER einen Begriff verwendet, der NICHT wörtlich im Kursmaterial vorkommt (z.B. USER fragt nach "Trennkost"),
   aber das KONZEPT in den Snippets beschrieben ist, dann:
   - erkläre das Konzept ausschließlich aus den Snippets
   - und weise EINMAL kurz darauf hin: "Der Begriff X wird im Kursmaterial nicht wörtlich definiert; gemeint ist hier …"
   WICHTIG: Führe NIEMALS selbst Begriffe ein, die nicht im Kursmaterial stehen! Verwende nur die Begriffe aus den Snippets.
5. TEILANTWORTEN: Wenn die Frage mehrere Teile hat und nur ein Teil in den Snippets steht:
   - beantworte den belegbaren Teil
   - für den nicht belegbaren Teil verwende: "{FALLBACK_SENTENCE}"
6. KEINE SPEKULATIONEN: Erfinde keine Fakten, die nicht in den Snippets stehen.
7. KEINE MEDIZIN: Gib keine medizinische Diagnose oder Behandlungsanweisung.
8. KEINE QUELLEN IM TEXT: Nenne keine Quellenlabels im Text. Die Quellen werden automatisch angezeigt.
9. ZEITLICHE REGELN (KRITISCH):
   - Lies Wartezeit-Tabellen SEHR GENAU: "Wartedauer BIS ZUM Verzehr von X" bedeutet: ERST warten, DANN X essen.
   - Beispiel: "vor dem Obstverzehr 3h Abstand" = ERST 3h nach einer Mahlzeit warten, DANN Obst essen.
   - Die Tabelle zeigt wie lange man NACH verschiedenen Mahlzeiten warten muss, BEVOR man Obst isst.
   - Nach dem Obst selbst ist die Wartezeit kurz (20-30 Min für normales Obst).
10. REZEPT-VORSCHLÄGE: Wenn der User nach einem konkreten Rezept fragt, basierend auf einer zuvor
    besprochenen konformen Kombination, darfst du ein einfaches Rezept vorschlagen.
    Die REGELN kommen aus dem Kursmaterial, die Rezeptidee darf aus deinem allgemeinen Kochwissen kommen.
    Stelle sicher, dass das Rezept die Trennkost-Regeln einhält (keine verbotenen Kombinationen).
    Markiere dies am Ende kurz: "Dieses Rezept basiert auf den Kombinationsregeln aus dem Kurs."
11. BILD-ANALYSE GRENZEN: Wenn der User auf ein hochgeladenes Bild referenziert (z.B. "du siehst ja den Teller",
    "keine Ahnung, schau doch", "auf dem Foto"), dann ist das KEINE Kursmaterial-Frage!
    - Basierend auf dem Gericht: Mache eine REALISTISCHE Schätzung für typische Portionsgrößen
    - Beispiel Pfannengericht mit Gemüse: "Ich schätze ca. 2-3 EL Öl für so eine Portion"
    - Beispiel Salat mit Sesam: "Ich schätze ca. 1 EL Sesam (das überschreitet 1-2 TL) → nur mit Gemüse OK"
    - Gib dann das finale Verdict basierend auf dieser Schätzung
    - KRITISCH: Verwende NIEMALS "{FALLBACK_SENTENCE}" bei Bild-Referenzen!
    - Wenn der User sagt "keine Ahnung" auf deine Mengen-Frage, ist das eine Bild-Referenz, kein "weiß nicht"!
12. FOLLOW-UP auf FIX-RICHTUNGEN: Wenn du zuvor eine Alternative-Offerte gemacht hast ("falls du magst",
    "was möchtest du behalten", "konforme Variante") und der User antwortet:
    FALL A — User nennt Lebensmittel/Gruppe (z.B. "den Rotbarsch", "die Kartoffel", "das Protein"):
    - Erkenne dies als ANTWORT auf deine eigene Frage
    - Schlage SOFORT ein konkretes Gericht vor basierend auf der Wahl
    - Beispiel: User wählt "Rotbarsch" → schlage vor: "Rotbarsch mit Brokkoli, Paprika und Zitrone"
    - Das Gericht darf NUR die gewählte Komponente + stärkearmes Gemüse/Salat enthalten
    - KRITISCH: Verwende NIEMALS "{FALLBACK_SENTENCE}" bei Follow-up-Antworten!
    FALL B — User möchte "möglichst viel behalten" / "so ähnlich wie möglich" / "am liebsten alles":
    - Prüfe die Zutaten aus dem Chat-Verlauf. Bestimme SELBST die beste konforme Variante.
    - Schlage BEIDE möglichen Richtungen als konkrete Gerichte vor — OHNE Rückfrage!
    - Beispiel: Haferflocken-Obstbowl → "Option 1: Obst-Bowl (Banane+Mango ohne Haferflocken) /
      Option 2: Porridge (Haferflocken+Pflanzenmilch ohne Obst)"
    - Frage NICHT "welche Zutaten hast du?" — die stehen schon im Chat!
    FALL C — Bestätigung ("ok", "macht Sinn", "verstanden", "alles klar", "gut zu wissen", "danke"):
    - Antworte NUR: "Prima, jetzt weißt du Bescheid! Falls du doch eine konforme Alternative möchtest, frag einfach nochmal."
    FALL D — Ablehnung/Desinteresse ("interessiert mich nicht", "egal", "nicht nötig", "passt so"):
    - Antworte NUR: "Alles klar! Das Angebot bleibt offen, wenn du es mal brauchst."
    FALL E — Neue Frage ohne Bezug zu Alternativen: Beantworte DIESE Frage. Vergiss die Alternativfrage.
    KRITISCH: Stelle die Alternativfrage NIEMALS ein zweites Mal!
    KRITISCH: Wiederhole das Verdict NICHT nochmal wenn es schon gegeben wurde!
13. SCHLEIFEN-SCHUTZ & WIEDERHOLUNGSVERBOT:
    a) Wenn du eine Frage gestellt hast und der User antwortet, stelle NIEMALS die GLEICHE Frage nochmal!
    b) Wenn der User nach der SPEISEKARTE/MENÜ fragt ("von der Karte", "auf der Speisekarte"),
       dann empfehle AUSSCHLIESSLICH Gerichte VON DER KARTE — NIEMALS deine eigenen Vorschläge!
       Wiederhole NICHT "Gebratener Reis mit Brokkoli" wenn der User explizit nach Karten-Gerichten fragt.
    c) Wenn der User sagt "ein anderes Gericht", "was anderes" → nenne ein NEUES Gericht, nicht das gleiche!
    - Prüfe den Chat-Verlauf: Habe ich diese Frage schon gestellt?
    - Wenn der User Zutaten genannt hat (auch unvollständig), arbeite damit weiter
    - Beispiel: User sagt "Hafermilch, wenig Zucker" → analysiere das! Frage NICHT nochmal nach Zutaten!
    - Wenn immer noch unklar: Stelle eine ANDERE, spezifischere Frage
    - VERBOTEN: Identische Frage wiederholen → führt zu Frustration!
14. KORREKTUR-ERKENNUNG: Wenn der User seine vorherige Aussage korrigiert oder klarstellt,
    dann ist das KEINE Kursmaterial-Frage!
    - Muster: "aber ich hab doch X gesagt", "nein, keine X, nur Y", "hab doch keine X"
    - KRITISCH: Verwende NIEMALS "{FALLBACK_SENTENCE}" bei Korrekturen!
    - Beispiel: User sagt "normaler mit Hafermilch", du verstehst "normale Milch + Hafermilch",
      User korrigiert "aber hab doch Hafermilch keine normale Milch" → RE-ANALYSIERE mit Hafermilch!
    - Erkenne Missverständnisse, entschuldige dich kurz und analysiere korrekt: "Ah verstehe, nur Hafermilch! ..."

Du darfst auf frühere Nachrichten referenzieren, aber neue Fakten müssen aus den Kurs-Snippets kommen.
"""


# ── Context blocks ────────────────────────────────────────────────────

def build_base_context(
    summary: Optional[str],
    last_messages: List[Dict[str, Any]],
) -> List[str]:
    """Build conversation context block (summary + recent messages)."""
    parts = []
    if summary:
        parts.append(f"KONVERSATIONS-ZUSAMMENFASSUNG:\n{summary}\n")

    # Exclude the current message (last one) from history
    history = last_messages[:-1] if last_messages else []
    if history:
        parts.append("LETZTE NACHRICHTEN:")
        for msg in history:
            role = "User" if msg["role"] == "user" else "Assistant"
            parts.append(f"{role}: {msg['content']}")
        parts.append("")

    return parts


def build_engine_block(
    trennkost_results: List[TrennkostResult],
    is_breakfast: bool = False,
) -> List[str]:
    """Format engine results as structured text for the LLM context."""
    parts = []
    engine_context = format_results_for_llm(trennkost_results, breakfast_context=is_breakfast)
    parts.append(engine_context)
    parts.append("")
    return parts


def build_menu_injection(trennkost_results: List[TrennkostResult]) -> List[str]:
    """SPEISEKARTE-MODUS: inject OK/conditional dish lists for menu analysis."""
    parts = []
    ok_dishes = [r.dish_name for r in trennkost_results if r.verdict.value == "OK"]
    cond_dishes = [r.dish_name for r in trennkost_results if r.verdict.value == "CONDITIONAL"]
    parts.append("SPEISEKARTE-MODUS:")
    parts.append("Der User hat eine SPEISEKARTE/MENÜ geschickt und möchte wissen was er bestellen kann.")
    if ok_dishes:
        parts.append(f"OK Konforme Gerichte: {', '.join(ok_dishes)}")
    if cond_dishes:
        parts.append(f"Bedingt konforme Gerichte: {', '.join(cond_dishes)}")
    if not ok_dishes and not cond_dishes:
        parts.append("Kein Gericht auf der Karte ist vollständig konform.")
        parts.append("Schlage die BESTE Option vor (wenigstes Probleme) und erkläre was man weglassen könnte.")
    parts.append("WICHTIG: Empfehle NUR Gerichte VON DER KARTE. Erfinde KEINE eigenen Gerichte!")
    parts.append("Wenn User nach 'einem anderen Gericht' fragt, nächstes konformes Gericht VON DER KARTE.\n")
    return parts


def build_vision_failed_block() -> List[str]:
    """Tell LLM to ask user for text input when vision fails."""
    return [
        "BILD-ANALYSE FEHLGESCHLAGEN:",
        "Das hochgeladene Bild konnte nicht analysiert werden.",
        "Bitte den User, die Gerichte oder Zutaten als Text aufzulisten.",
        "SAGE NICHT 'Diese Information steht nicht im Kursmaterial'!\n",
    ]


def build_vision_legacy_block(vision_analysis: Dict[str, Any]) -> List[str]:
    """Include legacy vision summary when no engine results available."""
    parts = []
    parts.append("BILD-ANALYSE (Mahlzeit):")
    parts.append(f"Zusammenfassung: {vision_analysis.get('summary', 'Keine Beschreibung')}")
    if vision_analysis.get("items"):
        parts.append("\nIdentifizierte Lebensmittel:")
        for item in vision_analysis["items"]:
            name = item.get("name", "Unbekannt")
            category = item.get("category", "?")
            amount = item.get("amount", "?")
            parts.append(f"  - {name} ({category}, Menge: {amount})")
    parts.append("")
    return parts


def build_breakfast_block() -> List[str]:
    """Standalone breakfast guidance when no engine results."""
    return [
        "FRÜHSTÜCKS-HINWEIS (Kurs Modul 1.2):",
        "Das Kursmaterial empfiehlt ein zweistufiges Frühstück:",
        "  1. Frühstück: Frisches Obst ODER Grüner Smoothie (fettfrei)",
        "     → Obst verdaut in 20-30 Min, Bananen/Trockenobst 45-60 Min",
        "  2. Frühstück (falls 1. nicht reicht): Fettfreie Kohlenhydrate (max 1-2 TL Fett)",
        "     → Empfehlungen: Overnight-Oats, Porridge, Reis-Pudding, Hirse-Grieß,",
        "       glutenfreies Brot mit Gurke/Tomate + max 1-2 TL Avocado",
        "",
        "WARUM FETTARM VOR MITTAGS?",
        "  Bis mittags läuft die Entgiftung des Körpers auf Hochtouren.",
        "  Leichte Kost spart Verdauungsenergie → mehr Energie für Entgiftung/Entschlackung.",
        "  Fettreiche Lebensmittel belasten die Verdauung und behindern diesen Prozess.",
        "",
        "ANWEISUNG: Erwähne das zweistufige Frühstücks-Konzept PROAKTIV in deiner Antwort!",
        "Empfehle IMMER zuerst die fettarme Option (Obst/Smoothie, dann ggf. fettfreie KH).",
        "",
    ]


def build_menu_followup_block() -> List[str]:
    """Remind LLM about previous menu when user references it without new image."""
    return [
        "SPEISEKARTEN-REFERENZ:",
        "Der User verweist auf eine zuvor geschickte Speisekarte.",
        "Schau im Chat-Verlauf nach den analysierten Gerichten von der Karte.",
        "Empfehle ein ANDERES konformes Gericht VON DER KARTE — NICHT deine eigenen Vorschläge!",
        "Wenn kein konformes Gericht auf der Karte ist, sage das ehrlich und erkläre was man anpassen könnte.\n",
    ]


def build_post_analysis_ack_block() -> List[str]:
    """Short acknowledgement when user didn't engage with the fix-direction offer."""
    return [
        "POST-ANALYSE-BESTÄTIGUNG:",
        "Der User hat das Trennkost-Verdict erhalten und reagiert ohne eine Fix-Richtung zu wählen.",
        "Antworte KURZ und FREUNDLICH — maximal 1–2 Sätze. Zum Beispiel:",
        "  'Prima! Jetzt weißt du, wie es damit aussieht. Falls du doch eine konforme Alternative haben möchtest, frag einfach nochmal!'",
        "  ODER: 'Alles klar! Das Angebot bleibt offen, wenn du es mal brauchst.'",
        "Wiederhole NICHT das Verdict. Stelle KEINE erneute Alternativ-Frage. Keine Rückfragen.\n",
    ]


def build_clarification_block(needs_clarification: str) -> List[str]:
    """Add clarification prompt for ambiguous foods."""
    return [
        f"WICHTIG - MEHRDEUTIGES LEBENSMITTEL:\n{needs_clarification}\n",
        "Bitte stelle diese Rückfrage ZUERST, bevor du die Hauptfrage beantwortest. "
        "Erkläre kurz, warum die Info wichtig ist.\n",
    ]


# ── Answer instructions per mode ─────────────────────────────────────

def build_prompt_food_analysis(
    trennkost_results: List[TrennkostResult],
    user_message: str,
    is_breakfast: bool = False,
    is_compliance_check: bool = False,
) -> str:
    """Answer instructions when engine results are present."""
    # Check if this is a menu analysis (multiple dishes)
    is_menu = len(trennkost_results) > 1

    if is_menu:
        # Menu analysis: overview of all dishes
        return build_prompt_menu_overview(trennkost_results, user_message)

    # Single dish analysis
    verdict_str = trennkost_results[0].verdict.value if trennkost_results else "UNKNOWN"
    verdict_display = {
        "OK": "OK",
        "NOT_OK": "NICHT OK",
        "CONDITIONAL": "BEDINGT OK",
        "UNKNOWN": "UNKLAR",
    }.get(verdict_str, verdict_str)

    # Check for OBST + KH conflict in engine results (independent of is_breakfast flag)
    _groups_present: set = set()
    for r in trennkost_results:
        for group_name in r.groups_found.keys():
            _groups_present.add(group_name)
    _has_obst_kh_conflict = "OBST" in _groups_present and any(
        g in _groups_present for g in ("KH", "GETREIDE", "HUELSENFRUECHTE", "TROCKENOBST")
    )

    breakfast_section = ""
    if is_breakfast:
        breakfast_section = (
            "- FRÜHSTÜCK-SPEZIFISCH (User fragt nach Frühstück!):\n"
            "  1. Empfehle ZUERST die fettarme Option aus dem FRÜHSTÜCKS-HINWEIS oben.\n"
            "  2. Erkläre KURZ warum: Entgiftung läuft bis mittags, fettarme Kost optimal.\n"
            "  3. Erwähne das zweistufige Frühstücks-Konzept (1. Obst → 2. fettfreie KH).\n"
            "  4. Falls User auf fettreiche Option besteht: erlaubt, aber mit freundlichem Hinweis.\n"
            "  5. Konkrete fettarme Empfehlungen: Obst, Grüner Smoothie, Overnight-Oats, Porridge,\n"
            "     Reis-Pudding, Hirse-Grieß, glutenfreies Brot mit Gemüse + max 1-2 TL Avocado.\n"
        )
    elif _has_obst_kh_conflict:
        breakfast_section = (
            "- OBST+KH KONFLIKT ERKANNT: Empfehle das zweistufige Frühstücks-Konzept:\n"
            "  → Stufe 1: Erst das Obst (Banane, Mango etc.) ALLEIN essen — 20-30 Min. warten\n"
            "  → Stufe 2: Dann das KH-Gericht (Porridge/Bowl/Haferflocken) OHNE Obst\n"
            "  NICHT '3 Stunden Abstand' sagen — die Lösung ist: Obst VORHER essen, kurz warten.\n"
        )

    return (
        f"USER'S ORIGINAL MESSAGE: {user_message}\n\n"
        "ANTWORT-ANWEISUNGEN:\n"
        f"KRITISCH: Das Verdict lautet '{verdict_display}'. Gib dies EXAKT so wieder.\n"
        "- Offene Fragen bedeuten NICHT, dass das Verdict 'bedingt' ist.\n"
        "- Bei 'NICHT OK': Auch wenn Rückfragen bestehen, bleibt es NICHT OK.\n"
        "- Bei 'BEDINGT OK': Nur dann 'bedingt' sagen, wenn oben CONDITIONAL steht.\n"
        "- Das Verdict wurde DETERMINISTISCH ermittelt und darf NICHT interpretiert werden.\n"
        "- KRITISCH: Wenn oben 'KEINE OFFENEN FRAGEN' steht, dann gibt es NULL weitere Fragen.\n"
        "  Erwähne NICHTS über 'typische Zutaten', 'weitere Zutaten', oder 'könnte die Bewertung ändern'.\n"
        "  Sprich NUR über Zutaten die in der 'Gruppen'-Liste oben stehen. IGNORIERE Infos aus RAG-Snippets\n"
        "  über angeblich 'typische' Zutaten die NICHT in der Gruppen-Liste sind.\n"
        "  VERBOTEN: 'Sind X, Y, Z enthalten?', 'Falls X enthalten ist...', 'Diese Info könnte ändern...'\n"
        "  ERLAUBT: Verdict erklären basierend auf den Zutaten in der Gruppen-Liste, fertig.\n"
        "- Bei INFO-Level Problemen (z.B. Zucker-Empfehlung):\n"
        "  Diese sind KEINE Trennkost-Verstöße, sondern Gesundheits-Empfehlungen aus dem Kurs.\n"
        "  Erwähne sie KURZ und freundlich am Ende (z.B. 'Kleiner Tipp: Honig oder Ahornsirup wären gesünder als Zucker.').\n"
        "  Das Verdict bleibt OK oder BEDINGT OK, nicht NICHT OK wegen INFO-Problemen!\n"
        "\nSTIL & FORMAT:\n"
        "- Schreibe natürlich und freundlich, wie ein Ernährungsberater — KEIN Bericht-Format.\n"
        "- Beginne mit dem Verdict als kurze, klare Aussage (z.B. 'Spaghetti Carbonara ist leider **nicht trennkost-konform**.').\n"
        "- Erkläre die Probleme kurz und verständlich (keine nummerierten Listen, kein Fachjargon).\n"
        "- Belege mit Kurs-Snippets, aber baue es natürlich in den Text ein.\n"
        "- Bei NOT_OK mit ALTERNATIVEN-Block:\n"
        "  Erkläre KURZ das Problem. Biete dann OPTIONAL an (kein Fragezeichen-Zwang!):\n"
        "  'Falls du magst, kann ich dir eine konforme Variante vorschlagen — sag mir einfach,\n"
        "   was du lieber behalten möchtest: [Gruppe A] oder [Gruppe B].'\n"
        "  WICHTIG: Das ist ein ANGEBOT, keine Pflichtfrage. Halte es einladend, nicht fordernd.\n"
        "  Wenn User darauf eingeht (Lebensmittel/Gruppe nennt) → sofort konformes Gericht vorschlagen.\n"
        "  Wenn User nicht darauf eingeht → kurz bestätigen (Fall C/D in Rule 12), NICHT wiederholen!\n"
        "  Die Richtungen sind EXKLUSIV. 'Behalte KH' heißt: NUR KH + Gemüse, KEIN Protein!\n"
        "  'Behalte Protein' heißt: NUR Protein + Gemüse, KEINE Kohlenhydrate!\n"
        "- REZEPT-VALIDIERUNG (KRITISCH — lies das!):\n"
        "  Bevor du ein Rezept oder eine Alternative vorschlägst, prüfe JEDE Zutat gegen die Regeln!\n"
        "  VERBOTENE Kombinationen die du NIEMALS vorschlagen darfst:\n"
        "  Käseomelette = Käse (MILCH) + Ei (PROTEIN) → R006 Verstoß!\n"
        "  Käse + Schinken = MILCH + PROTEIN → R006 Verstoß!\n"
        "  Ei + Brot/Toast = PROTEIN + KH → R001 Verstoß!\n"
        "  Ei + Käse = PROTEIN + MILCH → R006 Verstoß!\n"
        "  Käse + Brot = MILCH + KH → R002 Verstoß!\n"
        "  Joghurt + Müsli = MILCH + KH → R002 Verstoß!\n"
        "  GRUNDREGEL für Alternativen:\n"
        "  Gewählte Gruppe + NEUTRAL (Gemüse/Salat) = EINZIG erlaubte Kombination!\n"
        "  'Behalte MILCH' → NUR Milchprodukte + Gemüse. KEIN Ei, KEIN Fleisch, KEIN Brot!\n"
        "  'Behalte PROTEIN' → NUR Fleisch/Fisch/Ei + Gemüse. KEINE KH, KEINE Milch!\n"
        "  'Behalte KH' → NUR Brot/Reis/Pasta + Gemüse. KEIN Protein, KEINE Milch!\n"
        + breakfast_section +
        "- Bei BEDINGT OK:\n"
        "  1. Erkläre kurz, warum es bedingt ist\n"
        "  2. Stelle die offene Frage aus 'Offene Fragen' (z.B. 'Wie viel Fett ist enthalten?')\n"
        "  3. WICHTIG: Schlage KEINE zusätzlichen Zutaten oder Alternativen vor!\n"
        "  4. Konzentriere dich NUR auf die Klärung der offenen Frage\n"
        "- Verwende AUSSCHLIESSLICH Begriffe aus den Kurs-Snippets.\n"
        + (
            "\nCOMPLIANCE-CHECK-MODUS — ZUSÄTZLICHE ANWEISUNGEN:\n"
            "Der User hat ein eigenes Rezept oder eine Zutatenkombination zur Prüfung eingereicht.\n"
            "Beantworte ZUERST klar mit einer der folgenden Aussagen:\n"
            "  ✅ 'Ja, das ist trennkost-konform!' ODER\n"
            "  ❌ 'Nein, leider nicht konform.' ODER\n"
            "  ⚠️ 'Bedingt konform — es kommt darauf an...'\n"
            "Erkläre dann KONKRET welche Zutatenkombination das Problem verursacht.\n"
            "Gib danach 1–2 konkrete Varianten wie das Rezept angepasst werden kann "
            "(nutze die Fix-Directions aus dem Engine-Block oben).\n"
            "Stelle KEINE Rückfragen — alle Zutaten sind bekannt.\n"
            "Wenn der User explizit fragt wie er es konform machen kann: beantworte das direkt.\n"
            if is_compliance_check else ""
        )
    )


def build_prompt_menu_overview(
    trennkost_results: List[TrennkostResult],
    user_message: str,
) -> str:
    """Answer instructions for menu analysis (multiple dishes)."""
    ok_dishes = [r.dish_name for r in trennkost_results if r.verdict.value == "OK"]
    conditional_dishes = [r.dish_name for r in trennkost_results if r.verdict.value == "CONDITIONAL"]
    not_ok_dishes = [r.dish_name for r in trennkost_results if r.verdict.value == "NOT_OK"]

    return (
        f"USER'S ORIGINAL MESSAGE: {user_message}\n\n"
        "SPEISEKARTEN-ANALYSE — MEHRERE GERICHTE:\n"
        "Du hast eine Speisekarte/Menü mit mehreren Gerichten analysiert.\n"
        "\n"
        "ANTWORT-ANWEISUNGEN:\n"
        "1. **ÜBERSICHT GEBEN**: Gib eine klare Übersicht über ALLE Gerichte:\n"
        f"   - ✅ Trennkost-konforme Gerichte ({len(ok_dishes)}): {', '.join(ok_dishes) if ok_dishes else 'Keine'}\n"
        f"   - ⚠️ Bedingt konforme Gerichte ({len(conditional_dishes)}): {', '.join(conditional_dishes) if conditional_dishes else 'Keine'}\n"
        f"   - ❌ Nicht konforme Gerichte ({len(not_ok_dishes)}): {', '.join(not_ok_dishes) if not_ok_dishes else 'Keine'}\n"
        "\n"
        "2. **EMPFEHLUNG**: Wenn es konforme Gerichte gibt:\n"
        "   - Empfehle 1-2 der BESTEN konformen Gerichte mit kurzer Begründung\n"
        "   - Beispiel: 'Der **Rindfleisch-Salat** ist perfekt — Protein mit stärkearmem Gemüse!'\n"
        "\n"
        "3. **ERKLÄRUNG**: Für nicht konforme Gerichte:\n"
        "   - Erkläre KURZ warum sie nicht konform sind (z.B. 'Hühnersuppe: Glasnudeln (KH) + Huhn (PROTEIN)')\n"
        "   - KEINE ausführlichen Erklärungen für JEDES Gericht — nur die Hauptprobleme\n"
        "\n"
        "4. **STIL**:\n"
        "   - Freundlich und hilfreich\n"
        "   - Strukturiert aber nicht als nummeriete Liste\n"
        "   - Fokus auf die GUTEN Optionen (was der User bestellen kann)\n"
        "   - Verwende Emojis sparsam für visuelle Struktur (✅ ⚠️ ❌)\n"
        "\n"
        "5. **WICHTIG**:\n"
        "   - Nenne ALLE analysierten Gerichte, nicht nur ein einzelnes\n"
        "   - Der User will wissen 'was kann ich da essen' — also alle Optionen sehen\n"
        "   - Stelle KEINE Follow-up-Frage wie 'Was möchtest du behalten?' bei einer Menü-Übersicht\n"
        "   - Follow-up-Fragen nur wenn der User später ein SPEZIFISCHES nicht-konformes Gericht auswählt\n"
    )


def build_prompt_vision_legacy(user_message: str) -> str:
    """Answer instructions for legacy vision analysis without engine results."""
    return (
        "ANTWORT (deutsch, präzise, materialgebunden):\n"
        "- Bewerte die Mahlzeit nach den im Kursmaterial beschriebenen Regeln.\n"
        "- Verwende AUSSCHLIESSLICH Begriffe aus den Kurs-Snippets.\n"
    )


def build_prompt_knowledge(
    user_message: str,
    is_breakfast: bool = False,
) -> str:
    """Answer instructions for general knowledge queries."""
    breakfast_instruction = ""
    if is_breakfast:
        breakfast_instruction = (
            "- FRÜHSTÜCK-SPEZIFISCH (User fragt nach Frühstück!):\n"
            "  Das Kursmaterial empfiehlt ein zweistufiges Frühstück:\n"
            "  1. Frühstück: Frisches Obst ODER Grüner Smoothie (fettfrei)\n"
            "     → Obst verdaut in 20-30 Min, dann 2. Frühstück möglich\n"
            "  2. Frühstück: Fettfreie Kohlenhydrate (max 1-2 TL Fett)\n"
            "     → Overnight-Oats, Porridge, Reis-Pudding, Hirse, glutenfreies Brot + Gemüse\n"
            "  WARUM: Bis mittags läuft Entgiftung — fettarme Kost spart Verdauungsenergie.\n"
            "  → Empfehle IMMER zuerst die fettarme Option. Bei Insistieren: erlaubt, aber mit Hinweis.\n"
        )

    return (
        "ANTWORT (deutsch, natürlich, materialgebunden):\n"
        "- Beantworte die Frage aus den Snippets.\n"
        "- Schreibe natürlich und freundlich, nicht wie ein Bericht.\n"
        "- PROAKTIV HANDELN: Lieber einen konkreten Vorschlag machen als weitere Fragen stellen.\n"
        "- KRITISCH - FOLLOW-UP ERKENNUNG: Prüfe den Chat-Verlauf:\n"
        "  Hast du zuvor 'Was möchtest du behalten?' gefragt? Dann ist jede kurze Antwort\n"
        "  wie 'den Rotbarsch', 'die Kartoffel', 'das Protein' eine ANTWORT darauf!\n"
        f"  → Verwende NIEMALS '{FALLBACK_SENTENCE}' für Follow-up-Antworten!\n"
        "  → Schlage SOFORT ein Gericht vor: 'Rotbarsch mit Brokkoli, Paprika, Zitrone'\n"
        "  → Das Gericht darf NUR die gewählte Komponente + Gemüse enthalten\n"
        "  → KEINE KH wenn Protein gewählt! KEINE Proteine wenn KH gewählt!\n"
        "- REZEPT-VALIDIERUNG: Prüfe JEDES vorgeschlagene Rezept gegen die Regeln!\n"
        "  Käseomelette = Käse (MILCH) + Ei (PROTEIN) → VERBOTEN!\n"
        "  Käse + Schinken/Fleisch = MILCH + PROTEIN → VERBOTEN!\n"
        "  Ei + Brot = PROTEIN + KH → VERBOTEN!\n"
        "  Ei + Käse = PROTEIN + MILCH → VERBOTEN!\n"
        "  Gewählte Gruppe + Gemüse/Salat = EINZIG erlaubte Kombination!\n"
        + breakfast_instruction +
        "- Wenn der User ein Rezept will ('ja gib aus', 'Rezept bitte', 'ja'):\n"
        "  Gib SOFORT ein vollständiges Rezept mit Zutaten und Zubereitung.\n"
        "  Wiederhole NICHT den vorherigen Vorschlag als Frage.\n"
        "- Wenn der User sagt 'soll X nahe kommen' oder 'ähnlich wie X':\n"
        "  Analysiere welche Komponenten von X konform sind (z.B. Reisnudeln, Gemüse)\n"
        "  und welche nicht (z.B. Ei/Tofu). Schlage eine Variante VOR die die konformen\n"
        "  Komponenten nutzt. Wiederhole NICHT das vorherige Rezept.\n"
        f"- Nur wenn wirklich kein passender Inhalt ist: \"{FALLBACK_SENTENCE}\"\n"
    )


def build_recipe_context_block(recipes: List[Dict]) -> List[str]:
    """Build recipe data as a context block (injected BEFORE course snippets)."""
    parts = []
    if not recipes:
        return parts

    parts.append("═══ KURATIERTE REZEPTDATENBANK ═══")
    parts.append("Die folgenden Rezepte sind geprüft und trennkost-konform.")
    parts.append("WICHTIG: Verwende bevorzugt diese Rezepte statt eigene zu erfinden!\n")

    for i, r in enumerate(recipes, 1):
        tags_str = ", ".join(r.get("tags", []))
        ingredients_str = ", ".join(r.get("ingredients", [])[:8])
        parts.append(
            f"  {i}. {r['name']} ({r.get('trennkost_category', '?')}) "
            f"| {r.get('time_minutes', '?')} Min. | Tags: {tags_str}"
        )
        parts.append(f"     Zutaten: {ingredients_str}")

    # Include full recipe for top match
    top = recipes[0]
    if top.get("full_recipe_md"):
        parts.append("")
        parts.append(f"VOLLSTÄNDIGES REZEPT (Top-Treffer: {top['name']}):")
        parts.append(top["full_recipe_md"])

    # Mandeldrink hint
    hinweis_recipes = [r for r in recipes if r.get("trennkost_hinweis")]
    if hinweis_recipes:
        parts.append("")
        for r in hinweis_recipes:
            parts.append(f"HINWEIS zu {r['name']}: {r['trennkost_hinweis']}")

    parts.append("")
    parts.append("═══ ENDE REZEPTDATENBANK ═══")
    parts.append("")
    return parts


def build_prompt_recipe_request(
    recipes: List[Dict],
    user_message: str,
    is_breakfast: bool = False,
) -> str:
    """Answer instructions for recipe mode (data is in context block above)."""
    parts = []

    if recipes:
        top_score = recipes[0].get("score", 0.0) if recipes else 0.0
        has_clear_match = top_score >= 5.0

        score_instruction = ""
        if has_clear_match:
            score_instruction = (
                "🚨 KRITISCH — HOHER MATCH-SCORE ERKANNT:\n"
                f"Das Top-Rezept hat Score {top_score:.1f} — das ist ein KLARER MATCH!\n"
                "\n"
                "VERHALTEN bei hohem Score (≥5.0):\n"
                "✓ RICHTIG: Gib SOFORT das vollständige Rezept aus mit einleitendem Satz\n"
                "✗ FALSCH: 'Wie möchtest du das zubereitet haben?' oder ähnliche Rückfragen\n"
                "\n"
                "BEISPIEL:\n"
                "User: 'hast du was mit steak?'\n"
                "RICHTIG: 'Hier ist ein tolles Steak-Rezept: [vollständiges Rezept]'\n"
                "FALSCH: 'Wie möchtest du das Steak zubereitet haben?'\n\n"
            )

        parts.append(
            "REZEPT-MODUS — ANWEISUNGEN:\n"
            "- KRITISCH: Oben steht eine KURATIERTE REZEPTDATENBANK mit geprüften Rezepten.\n"
            "\n"
            f"{score_instruction}"
            "AUSGABE-FORMAT (zwingend):\n"
            "1. Wähle das passendste Rezept aus der Datenbank (= das erste mit höchstem Score)\n"
            "2. Schreibe einen kurzen einleitenden Satz (1-2 Zeilen) der natürlich ans Gespräch anschließt\n"
            "3. Zeige dann das Rezept mit dieser Formatierung:\n"
            "   - **Rezepttitel** (fett)\n"
            "   - Zeit & Portionen in einer Zeile (z.B. '⏱️ 30 Min. | 🍽️ 2 Portionen')\n"
            "   - Leerzeile\n"
            "   - **Zutaten** (fett, KEINE #### Markdown-Header!)\n"
            "   - Zutatenliste mit - Aufzählungen\n"
            "   - 🚨 KRITISCH: Kopiere EXAKT die Mengenangaben aus full_recipe_md!\n"
            "   - NIEMALS Mengen weglassen (z.B. '300 g Steak', NICHT nur 'Steak')\n"
            "   - Leerzeile\n"
            "   - **Zubereitung** (fett, KEINE #### Markdown-Header!)\n"
            "   - Zubereitungsschritte nummeriert\n"
            "   - Leerzeile\n"
            "4. Sage am Ende: 'Dieses Rezept stammt aus unserer kuratierten Rezeptdatenbank.'\n"
            "\n"
            "VERBOTE:\n"
            "- NIEMALS nach Zutaten, Präferenzen oder weiteren Infos fragen (außer bei Score < 3.0)!\n"
            "- NIEMALS eigene Rezepte erfinden wenn passende in der Datenbank stehen!\n"
            "- NIEMALS den Fallback-Satz verwenden!\n"
            "\n"
            "Bei mehreren passenden Rezepten:\n"
            "- Wähle das mit dem höchsten Score (steht oben)\n"
            "- Gib es vollständig aus\n"
            "- Optional: Erwähne kurz 1-2 Alternativen am Ende\n"
            "\n"
            "🔄 FOLLOW-UP-REGEL für kurze Antworten:\n"
            "Wenn User auf deine Frage mit kurzer Antwort antwortet ('egal', 'keine Präferenz', 'ist mir egal'):\n"
            "- Prüfe den Chat-Verlauf: Welches Thema wurde zuletzt besprochen?\n"
            "- Wähle das passendste Rezept aus der KURATIERTEN REZEPTDATENBANK oben (höchster Score)\n"
            "- Gib es vollständig aus\n"
            "- NIEMALS ein zufälliges, themenfremdes Rezept ausgeben!\n"
        )
    else:
        parts.append(
            "REZEPT-MODUS — KEINE KURATIERTEN REZEPTE GEFUNDEN.\n"
            "Du darfst ein eigenes Rezept vorschlagen, das die Trennkost-Regeln einhält.\n"
            "Sage am Ende: 'Dieses Rezept stammt nicht aus unserer kuratierten "
            "Rezeptdatenbank, sondern wurde nach Trennkost-Regeln zusammengestellt.'\n"
        )

    if is_breakfast:
        parts.append(
            "FRÜHSTÜCK: Empfehle bevorzugt fettarme Frühstücks-Rezepte "
            "(Obst, Smoothie, Overnight-Oats, Porridge).\n"
        )

    parts.append(
        "STIL:\n"
        "- Schreibe natürlich und freundlich, wie ein Ernährungsberater.\n"
        "- REZEPT-VALIDIERUNG: Prüfe JEDES Rezept gegen Trennkost-Regeln!\n"
    )

    return "\n".join(parts)


# ── Full prompt assembly ──────────────────────────────────────────────

def assemble_prompt(
    parts: List[str],
    course_context: str,
    user_message: str,
    answer_instructions: str,
    needs_clarification: Optional[str] = None,
) -> str:
    """Assemble the complete user-side prompt from all blocks."""
    all_parts = list(parts)

    all_parts.append(f"KURS-SNIPPETS (FAKTENBASIS):\n{course_context}\n")
    all_parts.append(f"AKTUELLE FRAGE:\n{user_message}\n")

    if needs_clarification:
        all_parts.extend(build_clarification_block(needs_clarification))

    all_parts.append(answer_instructions)

    return "\n".join(all_parts)
