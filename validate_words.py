#!/usr/bin/env python3
"""Validate Imposter words database schema/content."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def find_words_file(base: Path) -> Path:
    data_dir = base / "data"
    for name in ("words.json", "words.JSON"):
        p = data_dir / name
        if p.exists() and p.is_file():
            return p

    if data_dir.exists() and data_dir.is_dir():
        for p in data_dir.iterdir():
            if p.is_file() and p.name.lower() == "words.json":
                return p

    raise FileNotFoundError("Could not find data/words.json or data/words.JSON")


def norm(v: Any) -> str:
    return str(v or "").strip()


def validate(db: dict[str, Any], base: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    cats = db.get("categories")
    if not isinstance(cats, list):
        return (["Root key 'categories' must be a list."], warnings)

    seen_ids: set[str] = set()
    img_dir = base / "data" / "images" / "categories"

    for idx, raw_cat in enumerate(cats):
        where = f"categories[{idx}]"
        if not isinstance(raw_cat, dict):
            errors.append(f"{where}: must be an object")
            continue

        cid = norm(raw_cat.get("id"))
        name = norm(raw_cat.get("name"))
        name_ar = norm(raw_cat.get("name_ar"))
        img = norm(raw_cat.get("img"))
        words = raw_cat.get("words")

        if not cid:
            errors.append(f"{where}: missing non-empty 'id'")
        else:
            lid = cid.casefold()
            if lid in seen_ids:
                errors.append(f"{where}: duplicate category id '{cid}'")
            seen_ids.add(lid)

        if not name:
            warnings.append(f"{where}: empty 'name' (game will fallback to id)")
        if not name_ar:
            warnings.append(f"{where}: empty 'name_ar' (game will fallback to name)")

        if not isinstance(words, list):
            errors.append(f"{where}: 'words' must be a list")
            continue

        if not words:
            warnings.append(f"{where}: empty words list (category cannot start a game)")

        if img:
            img_path = img_dir / Path(img).name
            if not img_path.exists():
                warnings.append(f"{where}: 'img' file not found: {img_path}")

        for w_idx, raw_word in enumerate(words):
            w_where = f"{where}.words[{w_idx}]"
            if not isinstance(raw_word, dict):
                errors.append(f"{w_where}: must be an object")
                continue

            en_word = norm(raw_word.get("word"))
            ar_word = norm(raw_word.get("word_ar"))
            en_hint = norm(raw_word.get("hint"))
            ar_hint = norm(raw_word.get("hint_ar"))

            if not en_word and not ar_word:
                errors.append(f"{w_where}: both 'word' and 'word_ar' are empty")

            if not en_hint and not ar_hint:
                warnings.append(f"{w_where}: both 'hint' and 'hint_ar' are empty")

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Imposter words database.")
    parser.add_argument(
        "--base",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Project root that contains data/",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as failures.",
    )
    args = parser.parse_args()

    base = args.base.resolve()
    try:
        words_path = find_words_file(base)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        return 1

    try:
        db = json.loads(words_path.read_text(encoding="utf-8"))
    except Exception as exc:  # pylint: disable=broad-except
        print(f"ERROR: Failed to parse {words_path}: {exc}")
        return 1

    if not isinstance(db, dict):
        print(f"ERROR: {words_path} root must be an object")
        return 1

    errors, warnings = validate(db, base)

    print(f"Checked: {words_path}")
    print(f"Categories: {len(db.get('categories', [])) if isinstance(db.get('categories'), list) else 0}")
    print(f"Errors: {len(errors)}")
    print(f"Warnings: {len(warnings)}")

    for msg in errors:
        print(f"ERROR: {msg}")
    for msg in warnings:
        print(f"WARN: {msg}")

    if errors:
        return 1
    if warnings and args.strict:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
