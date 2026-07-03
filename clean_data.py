"""
clean_data.py — Post-scrape validation pass.

Removes false-positive jobs from data.json and data_central.json using the
same multi-layer validation logic as the scraper. This script is automatically
run after every scrape (chained in scraper.py __main__), but can also be
invoked manually to clean up the existing data files without re-scraping.

Usage:
    python clean_data.py
"""
import json
import os

# Import the full validation suite from scraper.py
# This ensures clean_data.py always stays in sync with the scraper's logic.
from scraper import (
    is_excluded,
    is_teaching_job,
    is_employment_type_job,
    title_confidence_score,
    get_doc_type,
)

# Minimum title confidence to keep a cached job.
# 0.30 rejects single-word or very generic titles (e.g. "Recruitment", "Notice")
# while keeping moderately specific titles that passed scraping.
MIN_TITLE_CONFIDENCE = 0.30


def clean_file(json_file: str):
    """
    Reads a job data JSON file, re-validates every entry, removes non-teaching
    false positives, and writes the cleaned data back to both .json and .js.
    """
    if not os.path.exists(json_file):
        print(f"[SKIP] {json_file} not found.")
        return

    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    original_count = len(data.get("jobs", []))
    valid_jobs = []
    removed = []

    for job in data.get("jobs", []):
        title = job.get("title", "")
        title_lower = title.lower().strip()

        # ── Layer 1: Hard exclusion ──
        if is_excluded(title_lower):
            removed.append((title, "hard_exclusion"))
            continue

        # ── Layer 2: Must contain a core teaching keyword ──
        if not is_teaching_job(title):
            removed.append((title, "no_teaching_keyword"))
            continue

        # ── Layer 3: Must contain an employment type keyword ──
        if not is_employment_type_job(title):
            removed.append((title, "no_employment_type"))
            continue

        # ── Layer 4: Title confidence check ──
        conf = title_confidence_score(title)
        if conf < MIN_TITLE_CONFIDENCE:
            removed.append((title, f"low_confidence({conf:.2f})"))
            continue

        # ── Layer 5: Reject bare/single-word generic titles ──
        if title_lower.strip() in {"recruitment", "vacancy", "notification",
                                    "notice", "advertisement", "advt",
                                    "भर्ती", "रिक्ति", "सूचना", "विज्ञापन"}:
            removed.append((title, "vague_title"))
            continue

        job["doc_type"] = get_doc_type(title)
        valid_jobs.append(job)

    kept_count = len(valid_jobs)
    removed_count = original_count - kept_count

    data["jobs"] = valid_jobs

    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # Also overwrite the .js file for local file:// access
    js_file = json_file.replace('.json', '.js')
    var_name = "STATE_DATA" if "central" not in json_file else "CENTRAL_DATA"
    with open(js_file, 'w', encoding='utf-8') as f:
        f.write(f"window.{var_name} = ")
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write(";")

    print(f"[{json_file}] Kept {kept_count} / {original_count} jobs. Removed {removed_count}.")

    if removed_count > 0:
        print(f"  ── Removed entries (reason: title) ──")
        for title, reason in removed[:20]:  # show first 20 for brevity
            print(f"    [{reason}] {title[:80]}")
        if len(removed) > 20:
            print(f"    ... and {len(removed) - 20} more.")


if __name__ == "__main__":
    clean_file("data.json")
    clean_file("data_central.json")
    print("\nPost-scrape clean complete. Restart or refresh your server to see changes.")
