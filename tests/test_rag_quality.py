#!/usr/bin/env python3
"""
RAG Quality Regression Tests
Standard test questions to verify retrieval quality and grounding.
Run regularly: python tests/test_rag_quality.py
"""
import requests
import json
from typing import Dict, List
from datetime import datetime

BASE_URL = "http://127.0.0.1:8000"

# Standard test cases: (question, expected_keywords_in_answer, max_sources, should_have_fallback)
TEST_CASES = [
    {
        "id": "trennkost_definition",
        "question": "Was ist Trennkost und warum brauch ich das?",
        "expect_keywords": ["verdauung", "kombinat"],  # More flexible: accept variants
        "min_sources": 2,
        "should_have_fallback": False,
        "description": "Concept alias test: 'Trennkost' should map to 'Lebensmittelkombinationen'"
    },
    {
        "id": "kohlenhydrate_protein",
        "question": "Welche Lebensmittel sind Kohlenhydrate und welche Proteine?",
        "expect_keywords": ["kohlenhydrate", "protein"],  # Exact - but case-insensitive
        "min_sources": 2,
        "should_have_fallback": False,
        "description": "Core content test: should find multiple sources"
    },
    {
        "id": "verdauung_milieus",
        "question": "Wie funktioniert die Verdauung und Milieus?",
        "expect_keywords": ["verdauung", "milieu"],
        "min_sources": 1,
        "should_have_fallback": False,
        "description": "Multi-part question: should ground in material"
    },
    {
        "id": "nonexistent_topic",
        "question": "Was steht im Kursmaterial über Quantenmechanik?",
        "expect_keywords": ["nicht im bereitgestellten"],
        "min_sources": 0,
        "should_have_fallback": True,
        "description": "Fallback test: out-of-scope question should use fallback"
    },
    {
        "id": "diversification_test",
        "question": "Nenne mir alle Regeln für richtige Lebensmittelkombinationen",
        "expect_keywords": ["regel", "kombinat"],
        "min_sources": 2,
        "should_have_fallback": False,
        "description": "Diversification test: sources should be from different pages (max 2 per page)"
    },
    {
        "id": "partial_question_edge_case",
        "question": "Nenne mir 3 wichtige Lebensmittelkombinations-Regeln",
        "expect_keywords": ["regel", "kombinat"],
        "min_sources": 1,
        "should_have_fallback": False,
        "description": "Simple multi-fact test: should ground in material"
    },
    {
        "id": "specific_food_burger_fries",
        "question": "Sind Burger und Pommes zusammen gut?",
        "expect_keywords": ["kohlenhydrat", "protein", "nicht optimal"],
        "min_sources": 2,
        "should_have_fallback": False,
        "description": "Generalization test: specific foods should map to general principles (Fallback 1)"
    },
    {
        "id": "specific_food_fish_rice",
        "question": "Sind Fisch und Reis eine gute Kombination?",
        "expect_keywords": ["protein", "kohlenhydrat"],
        "min_sources": 1,
        "should_have_fallback": False,
        "description": "Specific food pairing: should find relevant principles in material"
    },
]


def test_rag_quality():
    """Run all test cases and report results."""
    print("=" * 80)
    print(f"RAG Quality Test Suite - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    print()

    passed = 0
    failed = 0
    results = []

    for test_case in TEST_CASES:
        test_id = test_case["id"]
        question = test_case["question"]
        expect_keywords = test_case["expect_keywords"]
        min_sources = test_case["min_sources"]
        should_have_fallback = test_case["should_have_fallback"]
        description = test_case["description"]

        print(f"TEST: {test_id}")
        print(f"  Question: {question}")
        print(f"  Description: {description}")

        try:
            response = requests.post(
                f"{BASE_URL}/chat",
                json={"message": question},
                timeout=30  # Increased: LLM calls can take time
            )

            if response.status_code != 200:
                print(f"  ❌ FAILED: HTTP {response.status_code}")
                failed += 1
                results.append({
                    "id": test_id,
                    "status": "FAILED",
                    "reason": f"HTTP {response.status_code}"
                })
                print()
                continue

            data = response.json()
            answer = data.get("answer", "").lower()
            sources = data.get("sources", [])
            num_sources = len(sources)

            # Check 1: Fallback expectation
            has_fallback = "nicht im bereitgestellten" in answer
            fallback_ok = has_fallback == should_have_fallback

            # Check 2: Keyword presence
            keywords_found = [kw.lower() in answer for kw in expect_keywords]
            keywords_ok = all(keywords_found)

            # Check 3: Source count
            sources_ok = num_sources >= min_sources

            # Check 4: Source diversity (if multiple sources, should be from different pages)
            source_paths = {}
            if num_sources > 0:
                for source in sources:
                    path = source.get("path", "")
                    source_paths[path] = source_paths.get(path, 0) + 1
            diversity_ok = all(count <= 2 for count in source_paths.values()) if source_paths else True

            # Overall result
            all_ok = fallback_ok and keywords_ok and sources_ok and diversity_ok

            if all_ok:
                print(f"  ✅ PASSED")
                passed += 1
                results.append({"id": test_id, "status": "PASSED"})
            else:
                print(f"  ❌ FAILED")
                failed += 1
                results.append({"id": test_id, "status": "FAILED", "reason": "Check details below"})

            # Detail output
            print(f"    Sources: {num_sources} (expected ≥{min_sources}) {'✓' if sources_ok else '✗'}")
            if sources:
                print(f"    Source paths: {dict(source_paths)} {'✓' if diversity_ok else '✗ (not diverse)'}")

            print(f"    Fallback in answer: {has_fallback} (expected {should_have_fallback}) {'✓' if fallback_ok else '✗'}")

            keywords_status = ", ".join(
                [f"'{kw}': {'✓' if found else '✗'}" for kw, found in zip(expect_keywords, keywords_found)]
            )
            print(f"    Keywords: {keywords_status}")

            print(f"    Answer preview: {answer[:100]}...")

        except requests.exceptions.ConnectionError:
            print(f"  ❌ FAILED: Cannot connect to {BASE_URL}")
            failed += 1
            results.append({"id": test_id, "status": "FAILED", "reason": "Connection error"})
        except Exception as e:
            print(f"  ❌ FAILED: {str(e)}")
            failed += 1
            results.append({"id": test_id, "status": "FAILED", "reason": str(e)})

        print()

    # Summary
    print("=" * 80)
    print(f"SUMMARY: {passed} passed, {failed} failed out of {len(TEST_CASES)} tests")
    print("=" * 80)

    # Save results to file
    with open("tests/test_results.json", "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "summary": {"passed": passed, "failed": failed, "total": len(TEST_CASES)},
            "results": results
        }, f, indent=2)
    print(f"Results saved to tests/test_results.json")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(test_rag_quality())
