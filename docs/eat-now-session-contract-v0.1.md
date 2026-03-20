# 1. Eat-now Session Contract v0.1

Dieser v0.1-Contract leitet sich aus dem heutigen Chat-Vertrag in `app/main.py`, dem Menü-Follow-up-Verhalten in `app/chat_service.py`, der aktuellen Persistenzlage in `app/database.py`, der Prompt-/Ranking-Nutzung in `app/prompt_builder.py` und dem generischen Kursbot-Client in `RicsSite` ab. In `RicsSite` gibt es heute keinen konkreten Eat-now-Client und keinen Eat-now-spezifischen Action-Contract, sondern nur den generischen Kursbot-Client und die generische `/kursbot`-Seite.

`Eat-now` bleibt additiv auf dem bestehenden Chat-Vertrag. Der Root-Request bleibt `conversationId`, `guestId`, `message`, `intent`; für Eat-now kommt optional ein verschachteltes `session`-Objekt dazu. `intent` bleibt ein grober Routing-Hinweis wie bisher. Wenn `session.sessionAction` gesetzt ist, ist diese Aktion für Eat-now maßgeblich.

**Minimaler backend-owned Session-State**

Persistiert:

| Feld | Bedeutung |
| --- | --- |
| `menuStateId` | Opaque, backend-generierte ID des aktiven Menüzustands |
| `conversationId -> aktiver menuStateId` | In v0.1 genau ein aktiver Menüzustand pro Conversation |
| `dishMatrix` als geordnete Liste | Eingefrorene Minimalmatrix der Gerichte für genau diesen Menüzustand |
| `focusDishKey` | Backend-owned aktueller Fokus innerhalb desselben `menuStateId` |

Rein ableitbar:

| Ableitung | Herleitung |
| --- | --- |
| `rank` | Aus der gespeicherten Reihenfolge der `dishMatrix`, nicht separat persistiert |
| Hauptoption | Aus `focusDishKey` plus gespeicherter Matrix |
| Ausweichoption | Aus derselben Matrix relativ zum aktuellen Fokus |
| sichtbare Folgeaktionen | Aus aktuellem Fokus, Ausweichoption und v0.1-Regeln |
| Formulierungen in `answer` | LLM-/Template-Ausgabe, nicht zustandsrelevant |

Für v0.1 ist die gespeicherte `dishMatrix` die eingefrorene Quelle der Wahrheit innerhalb eines `menuStateId`. `rank` wird strukturiert ausgegeben, aber nur aus der Listenreihenfolge berechnet. Es gibt bewusst keine zweite persistierte Rang-Quelle. Eine neue Karte oder ein neues Menü ersetzt den bisher aktiven Menüzustand derselben Conversation.

**Minimale Gerichte-Matrix**

Jeder Eintrag der eingefrorenen Matrix umfasst nur:

- `dishKey`
- `label`
- `verdict`
- `trafficLight`
- `hasOpenQuestion`

`dishKey` ist backend-generated und nur innerhalb eines `menuStateId` stabil. `rank` gehört zur Response-Struktur, aber nicht zur Persistenz. Die Matrix ist absichtlich klein: genug für Fokuswechsel, Ausweichoption und Follow-up-Kontinuität, aber ohne UI-Spiegelung, ohne Volltext-Erklärungen und ohne zusätzliche Frontend-Selektion.

**Minimale sichtbare Optionen**

Die Eat-now-Response darf maximal drei enge Folgeaktionen sichtbar machen:

- `other_option`
- `more_trennkost`
- `waiter_phrase`

Regeln:

- `other_option` ist nur sichtbar, wenn es innerhalb desselben `menuStateId` eine zweite noch empfehlbare Option gibt.
- `more_trennkost` ist sichtbar, solange ein `focusDishKey` existiert.
- `waiter_phrase` ist sichtbar, solange ein `focusDishKey` existiert.

Die Erstantwort auf eine Menüanalyse soll genau eine Hauptoption und, wenn vorhanden, genau eine Ausweichoption tragen. Die Folgeaktionen sind kein freies Menü weiterer Features, sondern nur die enge Bedienoberfläche rund um den aktuellen Menüzustand.

**Minimale Folgeaktionslogik**

Request-seitig gilt für v0.1:

- `session.type = "eat_now"`
- `session.menuStateId` fehlt beim ersten Menü-Scan und ist bei Folgeaktionen Pflicht
- `session.sessionAction` ist nur `other_option | more_trennkost | waiter_phrase`
- `targetDishKey` gehört nicht in den v0.1-Request
- `message` bleibt Teil des Transports, darf bei `sessionAction` aber leer sein

Response-seitig gilt für v0.1:

- Root bleibt `conversationId`, `answer`, `sources`
- `session` kommt nur additiv dazu
- `session.type = "eat_now"`
- `session.menuStateId` identifiziert den aktiven Menüzustand
- `session.focusDishKey` macht den backend-owned Fokus explizit
- `session.dishMatrix` trägt die Minimalmatrix
- `session.visibleOptions` trägt nur die sichtbaren Aktions-IDs und Labels

Aktionssemantik:

- `other_option`: Der Backend-Fokus springt auf die beste andere noch empfehlbare Option innerhalb desselben `menuStateId`. Gibt es keine solche Option, bleibt der Fokus unverändert und die Antwort sagt das klar.
- `more_trennkost`: Der Backend sucht innerhalb desselben `menuStateId` die trennkost-näheste noch empfehlbare Option. Ist das bereits der aktuelle Fokus, vertieft die Antwort nur die Begründung. Ist es eine andere Option, darf der Fokus auf diese Option wechseln und die Antwort erklärt den Wechsel.
- `waiter_phrase`: Liefert eine kurze Bestellformulierung für den aktuellen backend-owned Fokus. Kein Re-Ranking, kein neuer Menüzustand, kein Frontend-Zielparameter.

# 2. Minimaler Backend-Frontend-Vertrag

**Was strukturiert sein MUSS**

Damit Frontend und Backend denselben Menüzustand referenzieren können, ohne Antworttext parsen zu müssen, müssen diese Felder strukturiert übertragen werden:

| Ort | Felder |
| --- | --- |
| Request | `conversationId`, `guestId`, `message`, `intent`, optional `session` |
| Request `session` | `type`, optional `menuStateId`, optional `sessionAction` |
| Response Root | `conversationId`, `answer`, `sources` |
| Response `session` | `type`, `menuStateId`, `focusDishKey`, `dishMatrix`, `visibleOptions` |
| Response `dishMatrix[]` | `dishKey`, `label`, `rank`, `verdict`, `trafficLight`, `hasOpenQuestion` |
| Response `visibleOptions[]` | `id`, `label` |

Dabei gilt explizit:

- `dishMatrix` ist in der Response geordnet.
- `rank` wird aus dieser Reihenfolge berechnet und nur zur Klarheit mitgegeben.
- `visibleOptions` benennt nur die möglichen Folgeaktionen, nicht die UI-Darstellung.
- `focusDishKey` ist nötig, damit der aktuelle Backend-Fokus nicht aus der UI geraten werden muss.

Frontend-seitige Ist-Lage:

- `RicsSite/website/src/lib/api/kursbotClient.ts` kennt heute nur generische `ChatRequest`, `ImageChatRequest` und `ChatResponse`.
- `RicsSite/website/src/app/pages/Kursbot.tsx` rendert heute generische Chat-Nachrichten.
- Ein konkreter Eat-now-Client oder eine Eat-now-spezifische Action-Schicht ist dort aktuell nicht vorhanden.

**Was Text bleiben darf**

Text darf bewusst unstrukturiert bleiben, solange daraus keine Zustandskoppelung entsteht:

- `answer` als ruhige Empfehlung in natürlicher Sprache
- kurze Begründung, warum diese Option passt oder weniger passt
- Formulierung für `waiter_phrase`
- erläuternde Übergänge bei `other_option` oder `more_trennkost`

`sources` sind für Eat-now v0.1 nicht tragend. Sie bleiben Teil des bestehenden Root-Vertrags, sind aber weder für Fokuskontinuität noch für das Auslösen der Folgeaktionen maßgeblich.

# 3. Harte Non-Goals

- Kein neuer großer API-Zweig, keine Eat-now-Sonderroute, kein zweites Chat-Protokoll
- Keine Ausweitung auf `learn`, `need` oder `plan`
- Kein allgemeiner Ernährungschat und keine freie Ernährungsberatung außerhalb akuter Essensmomente
- Keine UI-gesteuerte Dish-Selektion per `targetDishKey` im v0.1-Request
- Keine Persistenz von UI-Zustand wie ausgewählter Karte, offener Sektion oder Button-Hervorhebung
- Keine Multi-Menu-Historie innerhalb einer Conversation; in v0.1 gibt es genau einen aktiven Menüzustand
- Keine neue Regel-Diskussion, kein Öffnen des Core-/Rule-Trust-Stands
- Keine Forderung, `sources` für Eat-now inhaltstragend oder vollständig zu machen

# 4. Beispiel-Payloads

**Erste Menüanalyse**

Konzeptionell über den bestehenden Bild-Chat-Endpunkt. Der Request bleibt Multipart/Form-Data; `session` ist hier noch nicht nötig.

```json
{
  "transport": "POST /api/v1/chat/image (multipart/form-data)",
  "fields": {
    "conversationId": "conv_123",
    "guestId": "guest_123",
    "message": "Was kann ich hier gerade essen?",
    "intent": "eat",
    "image": "<menu-photo>"
  }
}
```

```json
{
  "conversationId": "conv_123",
  "answer": "Am ruhigsten wirkt hier der Seetangsalat. Wenn du eine Ausweichoption möchtest, wäre die Miso-Tofu-Suppe die nächstliegende Wahl.",
  "sources": [],
  "session": {
    "type": "eat_now",
    "menuStateId": "menu_9f2a",
    "focusDishKey": "dish_seetangsalat",
    "dishMatrix": [
      {
        "dishKey": "dish_seetangsalat",
        "label": "Seetangsalat",
        "rank": 1,
        "verdict": "OK",
        "trafficLight": "GREEN",
        "hasOpenQuestion": false
      },
      {
        "dishKey": "dish_miso_tofu_suppe",
        "label": "Miso Tofu Suppe",
        "rank": 2,
        "verdict": "CONDITIONAL",
        "trafficLight": "YELLOW",
        "hasOpenQuestion": true
      },
      {
        "dishKey": "dish_udon",
        "label": "Udon mit Huhn",
        "rank": 3,
        "verdict": "NOT_OK",
        "trafficLight": "RED",
        "hasOpenQuestion": false
      }
    ],
    "visibleOptions": [
      { "id": "other_option", "label": "Andere Option" },
      { "id": "more_trennkost", "label": "Mehr Trennkost" },
      { "id": "waiter_phrase", "label": "Formulierung für den Kellner" }
    ]
  }
}
```

**other_option**

```json
{
  "conversationId": "conv_123",
  "guestId": "guest_123",
  "message": "",
  "intent": "eat",
  "session": {
    "type": "eat_now",
    "menuStateId": "menu_9f2a",
    "sessionAction": "other_option"
  }
}
```

```json
{
  "conversationId": "conv_123",
  "answer": "Als Ausweichoption würde ich in diesem Menü eher die Miso-Tofu-Suppe nehmen als die übrigen Gerichte.",
  "sources": [],
  "session": {
    "type": "eat_now",
    "menuStateId": "menu_9f2a",
    "focusDishKey": "dish_miso_tofu_suppe",
    "dishMatrix": [
      {
        "dishKey": "dish_seetangsalat",
        "label": "Seetangsalat",
        "rank": 1,
        "verdict": "OK",
        "trafficLight": "GREEN",
        "hasOpenQuestion": false
      },
      {
        "dishKey": "dish_miso_tofu_suppe",
        "label": "Miso Tofu Suppe",
        "rank": 2,
        "verdict": "CONDITIONAL",
        "trafficLight": "YELLOW",
        "hasOpenQuestion": true
      },
      {
        "dishKey": "dish_udon",
        "label": "Udon mit Huhn",
        "rank": 3,
        "verdict": "NOT_OK",
        "trafficLight": "RED",
        "hasOpenQuestion": false
      }
    ],
    "visibleOptions": [
      { "id": "more_trennkost", "label": "Mehr Trennkost" },
      { "id": "waiter_phrase", "label": "Formulierung für den Kellner" }
    ]
  }
}
```

**more_trennkost**

```json
{
  "conversationId": "conv_123",
  "guestId": "guest_123",
  "message": "",
  "intent": "eat",
  "session": {
    "type": "eat_now",
    "menuStateId": "menu_9f2a",
    "sessionAction": "more_trennkost"
  }
}
```

```json
{
  "conversationId": "conv_123",
  "answer": "Wenn du es noch trennkost-näher halten möchtest, bleib in diesem Menü lieber beim Seetangsalat. Er ist die klarere Option als die Suppe, weil dort keine offene Klärung mitläuft.",
  "sources": [],
  "session": {
    "type": "eat_now",
    "menuStateId": "menu_9f2a",
    "focusDishKey": "dish_seetangsalat",
    "dishMatrix": [
      {
        "dishKey": "dish_seetangsalat",
        "label": "Seetangsalat",
        "rank": 1,
        "verdict": "OK",
        "trafficLight": "GREEN",
        "hasOpenQuestion": false
      },
      {
        "dishKey": "dish_miso_tofu_suppe",
        "label": "Miso Tofu Suppe",
        "rank": 2,
        "verdict": "CONDITIONAL",
        "trafficLight": "YELLOW",
        "hasOpenQuestion": true
      },
      {
        "dishKey": "dish_udon",
        "label": "Udon mit Huhn",
        "rank": 3,
        "verdict": "NOT_OK",
        "trafficLight": "RED",
        "hasOpenQuestion": false
      }
    ],
    "visibleOptions": [
      { "id": "other_option", "label": "Andere Option" },
      { "id": "more_trennkost", "label": "Mehr Trennkost" },
      { "id": "waiter_phrase", "label": "Formulierung für den Kellner" }
    ]
  }
}
```

**waiter_phrase**

```json
{
  "conversationId": "conv_123",
  "guestId": "guest_123",
  "message": "",
  "intent": "eat",
  "session": {
    "type": "eat_now",
    "menuStateId": "menu_9f2a",
    "sessionAction": "waiter_phrase"
  }
}
```

```json
{
  "conversationId": "conv_123",
  "answer": "Du könntest zum Beispiel sagen: Ich nehme bitte den Seetangsalat.",
  "sources": [],
  "session": {
    "type": "eat_now",
    "menuStateId": "menu_9f2a",
    "focusDishKey": "dish_seetangsalat",
    "dishMatrix": [
      {
        "dishKey": "dish_seetangsalat",
        "label": "Seetangsalat",
        "rank": 1,
        "verdict": "OK",
        "trafficLight": "GREEN",
        "hasOpenQuestion": false
      },
      {
        "dishKey": "dish_miso_tofu_suppe",
        "label": "Miso Tofu Suppe",
        "rank": 2,
        "verdict": "CONDITIONAL",
        "trafficLight": "YELLOW",
        "hasOpenQuestion": true
      },
      {
        "dishKey": "dish_udon",
        "label": "Udon mit Huhn",
        "rank": 3,
        "verdict": "NOT_OK",
        "trafficLight": "RED",
        "hasOpenQuestion": false
      }
    ],
    "visibleOptions": [
      { "id": "other_option", "label": "Andere Option" },
      { "id": "more_trennkost", "label": "Mehr Trennkost" },
      { "id": "waiter_phrase", "label": "Formulierung für den Kellner" }
    ]
  }
}
```

# 5. Abnahmekriterien

- Der Contract bleibt additiv auf dem bestehenden Chat-Root und führt keinen zweiten Haupt-API-Zweig ein.
- Das Frontend kann Hauptoption, Ausweichoption, aktuellen Fokus und Folgeaktionen strukturiert rendern, ohne `answer` zu parsen.
- Der Backend-Zustand bleibt klein: `menuStateId`, geordnete Minimalmatrix, `focusDishKey`; keine UI-Spiegelung.
- Das Dokument trennt überall klar zwischen wirklich persistiert und rein ableitbar.
- `rank` ist eindeutig definiert: strukturell sichtbar, aber aus der gespeicherten Reihenfolge der Matrix abgeleitet und nicht separat persistiert.
- `other_option`, `more_trennkost` und `waiter_phrase` funktionieren innerhalb desselben `menuStateId`.
- Es ist klar, dass ein neues Menü den bisherigen aktiven Menüzustand ersetzt.
- `sources` sind für Eat-now nicht tragend; ein leeres `sources: []` verletzt den Contract nicht.
- Das Dokument verlangt weder `targetDishKey` noch Dummy-`message` noch mehrere aktive Menüzustände.

# 6. Offene Schnittstellenfallen aus dem IST-Stand

- Leere `message` ist heute nur für den `intent`-Shortcut vorgesehen. Der aktuelle `/api/v1/chat`-Pfad akzeptiert sonst keine leere Nachricht. Eat-now-Folgeaktionen mit `message: ""` sind damit ein echter Gap zwischen heutigem Code und v0.1-Contract.
- Die heutige Menü-Follow-up-Kontinuität hängt in `app/chat_service.py` an `_LAST_MENU_RESULTS_BY_CONVERSATION`, also an einem In-Memory-Cache statt an persistiertem Menüzustand.
- `sources` werden im aktuellen Backend für Antworten faktisch nur getragen, wenn `start_intent == "learn"`. Für Eat-now sind sie daher heute nicht belastbar.
- `RicsSite` hat aktuell keinen konkreten Eat-now-Client und keine Eat-now-spezifische Rendering-/Action-Schicht; vorhanden sind nur der generische Kursbot-Client und die generische `/kursbot`-Seite.
