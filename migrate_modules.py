#!/usr/bin/env python3
"""
Migration script to add consistent module metadata to all course pages.
Adds module_id, module_label, submodule_id, submodule_label to YAML frontmatter.
"""

import os
import re
from pathlib import Path

# Define module mappings
MODULE_MAPPINGS = {
    "modul-1.1-optimale-lebensmittelkombinationen": {
        "submodule_id": "1.1",
        "submodule_label": "Optimale Lebensmittelkombinationen"
    },
    "modul-1.2-fruehstueck-und-obstverzehr": {
        "submodule_id": "1.2",
        "submodule_label": "Frühstück und richtiger Obstverzehr"
    },
    "modul-1.3-naehrstoffspeicher-auffuellen": {
        "submodule_id": "1.3",
        "submodule_label": "Nährstoffspeicher auffüllen"
    }
}

# Common module fields (same for all)
MODULE_ID = 1
MODULE_LABEL = "Modul 1 – Optimale Lebensmittelkombinationen"

def migrate_file(file_path: Path, submodule_id: str, submodule_label: str):
    """Migrate a single markdown file."""

    # Read file
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Split frontmatter and body
    parts = content.split('---', 2)
    if len(parts) < 3:
        print(f"  ⚠️  Skipping {file_path.name}: No valid frontmatter")
        return False

    frontmatter = parts[1]
    body = parts[2]

    # Remove existing module fields if present
    frontmatter_lines = frontmatter.split('\n')
    cleaned_lines = []
    skip_next = False

    for line in frontmatter_lines:
        # Skip existing module fields
        if line.strip().startswith(('module_id:', 'module_label:', 'submodule_id:', 'submodule_label:')):
            continue
        cleaned_lines.append(line)

    # Find insertion point (after 'type:' line)
    new_lines = []
    inserted = False

    for line in cleaned_lines:
        new_lines.append(line)

        # Insert after 'type:' line
        if not inserted and line.strip().startswith('type:'):
            new_lines.append(f'module_id: {MODULE_ID}')
            new_lines.append(f'module_label: "{MODULE_LABEL}"')
            new_lines.append(f'submodule_id: "{submodule_id}"')
            new_lines.append(f'submodule_label: "{submodule_label}"')
            inserted = True

    if not inserted:
        print(f"  ⚠️  Could not find 'type:' field in {file_path.name}")
        return False

    # Reconstruct file
    new_content = '---' + '\n'.join(new_lines) + '---' + body

    # Write back
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(new_content)

    return True

def main():
    base_dir = Path('content/pages')

    print("🚀 Starting module metadata migration...\n")

    stats = {
        "total": 0,
        "success": 0,
        "skipped": 0
    }

    for folder_name, mapping in MODULE_MAPPINGS.items():
        folder_path = base_dir / folder_name

        if not folder_path.exists():
            print(f"⚠️  Directory not found: {folder_path}")
            continue

        print(f"📁 Processing: {folder_name}/")

        md_files = sorted(folder_path.glob('*.md'))

        for md_file in md_files:
            stats["total"] += 1

            success = migrate_file(
                md_file,
                mapping["submodule_id"],
                mapping["submodule_label"]
            )

            if success:
                stats["success"] += 1
                print(f"  ✅ {md_file.name}")
            else:
                stats["skipped"] += 1

        print()

    print("=" * 60)
    print("📊 Migration Summary:")
    print(f"  Total files processed: {stats['total']}")
    print(f"  Successfully migrated: {stats['success']}")
    print(f"  Skipped: {stats['skipped']}")
    print("=" * 60)
    print("\n✨ Migration complete!")

if __name__ == "__main__":
    main()
