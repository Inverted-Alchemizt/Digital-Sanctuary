import io
import requests
import fitz  # pymupdf
from pdf2image import convert_from_bytes
import pytesseract
import json
import os
import hashlib
from datetime import datetime, timezone, timedelta
import threading
import atexit


CACHE_FILE = "pdf_cache.json"
_memory_cache = {}
_cache_lock = threading.Lock()
_cache_loaded = False

def _ensure_cache_loaded():
    global _cache_loaded, _memory_cache
    if not _cache_loaded:
        with _cache_lock:
            if not _cache_loaded:
                if os.path.exists(CACHE_FILE):
                    try:
                        with open(CACHE_FILE, "r", encoding="utf-8") as f:
                            _memory_cache = json.load(f)
                    except Exception as e:
                        print(f"[WARN] Failed to load disk cache: {e}")
                        _memory_cache = {}
                _cache_loaded = True

def get_cached_result(pdf_url: str) -> dict:
    _ensure_cache_loaded()
    url_hash = hashlib.md5(pdf_url.encode()).hexdigest()
    if url_hash in _memory_cache:
        entry = _memory_cache[url_hash]
        try:
            cached_time = datetime.fromisoformat(entry.get("timestamp", "2000-01-01T00:00:00+00:00"))
            if datetime.now(timezone.utc) - cached_time < timedelta(hours=24):
                return entry.get("result")
        except ValueError:
            pass
    return None

def set_cached_result(pdf_url: str, result: dict):
    _ensure_cache_loaded()
    url_hash = hashlib.md5(pdf_url.encode()).hexdigest()
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "result": result
    }
    with _cache_lock:
        _memory_cache[url_hash] = entry

def save_cache_to_disk():
    global _cache_loaded, _memory_cache
    if not _cache_loaded:
        return
    with _cache_lock:
        try:
            temp_file = CACHE_FILE + ".tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(_memory_cache, f, ensure_ascii=False, indent=2)
            if os.path.exists(temp_file):
                os.replace(temp_file, CACHE_FILE)
                print(f"[INFO] pdf_evaluator: Cache successfully saved to disk. Total entries: {len(_memory_cache)}")
        except Exception as e:
            print(f"[WARN] pdf_evaluator: Failed to save cache: {e}")

atexit.register(save_cache_to_disk)




def evaluate_pdf_for_teaching_job(pdf_url: str, title: str = "") -> dict:
    """
    Evaluates a PDF from a given URL to determine if it is a teaching job notification.

    Uses direct text extraction via PyMuPDF first. Falls back to OCR (via pdf2image +
    pytesseract) if the extracted text is insufficient (< 50 characters).

    The caller can optionally pass `title` (the already-extracted page title) to give
    the scoring extra context — a specific title boosts the effective score.

    Args:
        pdf_url: The URL of the PDF to evaluate.
        title: Optional. The title text extracted from the web page listing.

    Returns:
        A dictionary with keys:
            - "is_teaching_job" (bool): True if score >= 15 AND >= 2 distinct high keywords.
            - "score" (int): The computed relevance score.
            - "method_used" (str): "direct_text", "ocr", or "error".
            - "text" (str): Extracted text from the PDF.
    """
    cached = get_cached_result(pdf_url)
    if cached is not None:
        return cached

    try:
        # --- Download PDF into memory ---
        response = requests.get(pdf_url, timeout=30)
        response.raise_for_status()
        pdf_bytes = response.content

        text = ""
        method_used = "direct_text"

        # -------------------------------------------------------------------------
        # Phase 1: Direct Text Extraction via PyMuPDF
        # -------------------------------------------------------------------------
        pdf_stream = io.BytesIO(pdf_bytes)
        with fitz.open(stream=pdf_stream, filetype="pdf") as doc:
            for page in doc:
                text += page.get_text()

        # -------------------------------------------------------------------------
        # Phase 2: Fallback OCR (if direct extraction yielded < 50 characters)
        # -------------------------------------------------------------------------
        if len(text.strip()) < 50:
            method_used = "ocr"
            images = convert_from_bytes(pdf_bytes)
            for image in images:
                text += pytesseract.image_to_string(image, lang="hin+eng")

        # -------------------------------------------------------------------------
        # Scoring Logic (case-insensitive)
        # -------------------------------------------------------------------------
        # Combine PDF text with the caller-provided title for context-aware scoring.
        # The title is pre-pended and weighted more heavily since it is the
        # authoritative source of what the document is actually about.
        title_lower = (title + " " + title).lower()   # doubled for extra weight
        text_lower = text.lower()
        combined = title_lower + " " + text_lower

        # ── +5 point keywords (core teaching signals) ──
        high_positive_keywords = [
            # Hindi
            "व्याख्याता",
            "शिक्षक",
            "सहायक शिक्षक",
            "बी.एड.",
            "डी.एड.",
            "डी.एल.एड.",
            "टीईटी",
            "t.e.t.",
            "स्वामी आत्मानंद",
            "सेजेस",
            # English
            "teacher",
            "lecturer",
            "pgt",
            "tgt",
            "prt",
            "faculty",
            "professor",
            "b.ed",
            "d.ed",
            "d.el.ed",
            "tet",
            "sages",
            "atmanand",
            # School-lab roles that ARE teaching posts
            "lab attendant",
            "lab sahayak",
            "प्रयोगशाला सहायक",
        ]

        # ── +2 point keywords (supporting signals) ──
        moderate_positive_keywords = [
            "संविदा भर्ती",
            "रिक्त पद",
            "शैक्षणिक योग्यता",
            "प्रवीण्य सूची",
            "teaching post",
            "school recruitment",
            "vidyalaya bharti",
            "विद्यालय भर्ती",
            "physical education teacher",
            "art teacher",
            "music teacher",
            "computer teacher",
        ]

        # ── -5 point keywords (non-teaching signals) ──
        negative_keywords = [
            "निविदा",
            "स्थानांतरण",
            "अवकाश",
            "आजीविका", "livelihood", "bihaan", "nrlm", "srlm", "rural",
            "women empowerment", "medical and health officer", "department of women and child",
            "health mission",
            "list of candidates",
            "pharmacist", "staff nurse", "medical officer", "anm", "ward boy", "dresser",
            "cmho", "c.m.h.o.", "store keeper", "house mother",
            "night watchman", "probation officer", "data entry operator", "social worker",
        ]

        # ── -10 point keywords (strong non-teaching signals — infrastructure, health, admin) ──
        strong_negative_keywords = [
            # Infrastructure / tenders
            "निर्माण कार्य", "construction work", "civil tender",
            "building tender", "building construction",
            "equipment tender", "supply tender",
            "it tender", "it infrastructure",
            # Hospital lab (NOT school lab)
            "lab technician", "laboratory technician", "प्रयोगशाला तकनीशियन",
            "pathologist", "radiographer",
            # Health staff
            "nursing staff", "medical staff", "asha worker",
            "staff nurse", "nursing",
            # Non-teaching rural posts
            "public library", "jan pustakalaya",
            "anganwadi worker", "mitanin",
        ]

        score = 0
        high_keyword_count = 0
        distinct_high_keywords_found = set()

        for keyword in high_positive_keywords:
            count = combined.count(keyword.lower())
            if count > 0:
                distinct_high_keywords_found.add(keyword)
                # Cap per-keyword contribution at 3 occurrences to prevent inflation
                effective_count = min(count, 3)
                high_keyword_count += effective_count
                score += 5 * effective_count

        for keyword in moderate_positive_keywords:
            count = combined.count(keyword.lower())
            if count > 0:
                score += 2 * min(count, 3)

        for keyword in negative_keywords:
            count = text_lower.count(keyword.lower())  # Only penalise in PDF text, not title
            if count > 0:
                score -= 5 * count

        for keyword in strong_negative_keywords:
            count = text_lower.count(keyword.lower())
            if count > 0:
                score -= 100 * count  # Extreme penalty for near-certain non-teaching signals

        # -------------------------------------------------------------------------
        # Decision: RAISED threshold (was ≥10 with ≥1 keyword)
        # Now requires ≥15 score AND ≥2 DISTINCT high keywords.
        # This prevents a document mentioning "teacher" twice in passing from passing.
        # -------------------------------------------------------------------------
        is_teaching_job = (score >= 15) and (len(distinct_high_keywords_found) >= 2)

        result = {
            "is_teaching_job": is_teaching_job,
            "score": score,
            "method_used": method_used,
            "text": text,
            "distinct_high_keywords": list(distinct_high_keywords_found),
        }
        set_cached_result(pdf_url, result)
        return result

    except Exception:
        # Do NOT cache errors — transient failures (timeouts, 403s) should
        # be retried on the next scrape run, not locked out for 24 hours.
        return {
            "is_teaching_job": False,
            "score": 0,
            "method_used": "error",
            "text": "",
            "distinct_high_keywords": [],
        }
