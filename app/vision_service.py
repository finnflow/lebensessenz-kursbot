"""
Vision API integration for meal analysis.
Uses GPT-4 Vision to identify food items and categorize them.
"""
import os
from typing import Dict, List, Optional
from dotenv import load_dotenv
from openai import OpenAI

from app.image_handler import encode_image_base64, get_image_mime_type

load_dotenv()

# Configuration
VISION_MODEL = os.getenv("VISION_MODEL", "gpt-4o-mini")  # gpt-4o-mini supports vision
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# System prompt for food identification
FOOD_IDENTIFICATION_PROMPT = """Du bist ein Experte für Lebensmittelanalyse im Kontext der Trennkost-Ernährung.

Deine Aufgabe ist es, ein Mahlzeiten-Foto zu analysieren und folgendes zu identifizieren:

1. ALLE sichtbaren Lebensmittel/Komponenten
2. Zuordnung zu Lebensmittelgruppen:
   - Komplexe Kohlenhydrate (Getreide, Pseudogetreide, stärkehaltiges Gemüse, Hülsenfrüchte)
   - Proteine (Fisch, Fleisch, Eier, Milchprodukte)
   - Gesunde Fette (Nüsse, Öle, Avocado, Butter)
   - Stärkearmes Gemüse/Salat (neutral)

3. Mengenabschätzung (grob: viel, mittel, wenig)

WICHTIG:
- Sei präzise und sachlich
- Wenn unklar, sage "möglicherweise" oder "scheint zu sein"
- Keine Bewertung - nur Beschreibung und Kategorisierung
- Ausgabe als strukturiertes JSON

Beispiel-Ausgabe:
{
  "items": [
    {"name": "Quinoa", "category": "Komplexe Kohlenhydrate", "amount": "viel"},
    {"name": "Brokkoli", "category": "Stärkearmes Gemüse", "amount": "mittel"},
    {"name": "Avocado", "category": "Gesunde Fette", "amount": "wenig"}
  ],
  "summary": "Eine Quinoa-Bowl mit gedämpftem Brokkoli und Avocado-Scheiben.",
  "confidence": "high"
}
"""


class VisionAnalysisError(Exception):
    """Raised when vision analysis fails."""
    pass


def analyze_meal_image(image_path: str, user_message: Optional[str] = None) -> Dict:
    """
    Analyze meal image using GPT-4 Vision.

    Args:
        image_path: Path to the image file
        user_message: Optional user message/question about the meal

    Returns:
        Dict with analysis results:
        {
            "items": [{"name": str, "category": str, "amount": str}, ...],
            "summary": str,
            "confidence": str,
            "raw_response": str
        }

    Raises:
        VisionAnalysisError: If analysis fails
    """
    try:
        # Encode image
        base64_image = encode_image_base64(image_path)
        mime_type = get_image_mime_type(image_path)

        # Build messages
        messages = [
            {
                "role": "system",
                "content": FOOD_IDENTIFICATION_PROMPT
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{base64_image}",
                            "detail": "high"  # high detail for better food recognition
                        }
                    },
                    {
                        "type": "text",
                        "text": user_message or "Analysiere diese Mahlzeit detailliert."
                    }
                ]
            }
        ]

        # Call Vision API
        response = client.chat.completions.create(
            model=VISION_MODEL,
            messages=messages,
            temperature=0.1,  # Low temperature for consistent results
            max_tokens=1000
        )

        raw_response = response.choices[0].message.content

        # Try to parse as JSON, fallback to raw text
        import json
        try:
            parsed = json.loads(raw_response)
            return {
                "items": parsed.get("items", []),
                "summary": parsed.get("summary", raw_response),
                "confidence": parsed.get("confidence", "medium"),
                "raw_response": raw_response
            }
        except json.JSONDecodeError:
            # Fallback: Extract information from text
            return {
                "items": [],  # Could implement text parsing here
                "summary": raw_response,
                "confidence": "medium",
                "raw_response": raw_response
            }

    except Exception as e:
        raise VisionAnalysisError(f"Vision analysis failed: {str(e)}")


def categorize_food_groups(items: List[Dict]) -> Dict[str, List[str]]:
    """
    Categorize identified food items into groups.

    Args:
        items: List of food items with categories

    Returns:
        Dict with grouped items:
        {
            "carbs": [...],
            "proteins": [...],
            "fats": [...],
            "vegetables": [...]
        }
    """
    groups = {
        "carbs": [],
        "proteins": [],
        "fats": [],
        "vegetables": []
    }

    category_mapping = {
        "Komplexe Kohlenhydrate": "carbs",
        "Proteine": "proteins",
        "Gesunde Fette": "fats",
        "Stärkearmes Gemüse": "vegetables",
        "Salat": "vegetables"
    }

    for item in items:
        category = item.get("category", "")
        group = category_mapping.get(category)
        if group:
            groups[group].append(item.get("name", "Unbekannt"))

    return groups


def generate_trennkost_query(food_groups: Dict[str, List[str]]) -> str:
    """
    Generate a query for RAG system based on identified food groups.

    Args:
        food_groups: Categorized food items

    Returns:
        Query string for RAG retrieval
    """
    components = []

    if food_groups["carbs"]:
        components.append("Kohlenhydrate (" + ", ".join(food_groups["carbs"]) + ")")
    if food_groups["proteins"]:
        components.append("Proteine (" + ", ".join(food_groups["proteins"]) + ")")
    if food_groups["fats"]:
        components.append("Fette (" + ", ".join(food_groups["fats"]) + ")")
    if food_groups["vegetables"]:
        components.append("Gemüse (" + ", ".join(food_groups["vegetables"]) + ")")

    query = "Trennkost-Regeln für Kombination von: " + ", ".join(components)

    return query
