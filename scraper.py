import sys
import io
import requests
import json
import re
import hashlib

# Fix Windows cp1252 crash when printing Devanagari/Hindi characters.
# Without this, any district with Hindi text in job titles silently crashes
# and drops ALL PDFs for that district (confirmed: Durg lost 64 PDFs, Kanker crashed).
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf-8-sig'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
import pypdf
from bs4 import BeautifulSoup
from pdf_evaluator import evaluate_pdf_for_teaching_job
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))

DISTRICTS = {
    "Balod": "balod",
    "Balodabazar-Bhatapara": "balodabazar",
    "Balrampur": "balrampur",
    "Bastar": "bastar",
    "Bemetara": "bemetara",
    "Bijapur": "bijapur",
    "Bilaspur": "bilaspur",
    "Dantewada": "dantewada",
    "Dhamtari": "dhamtari",
    "Durg": "durg",
    "Gariyaband": "gariaband",
    "Gaurela-Pendra-Marwahi": "gpm",
    "Janjgir-Champa": "janjgir-champa",
    "Jashpur": "jashpur",
    "Kabirdham": "kabeerdham",
    "Kanker": "kanker",
    "Khairagarh": "khairagarh",
    "Kondagaon": "kondagaon",
    "Korba": "korba",
    "Korea": "koriya",
    "Mahasamund": "mahasamund",
    "MCB": "mcb",
    "Mohla-Manpur-Ambagarh": "mohla-manpur-ambagarh",
    "Mungeli": "mungeli",
    "Narayanpur": "narayanpur",
    "Raigarh": "raigarh",
    "Raipur": "raipur",
    "Rajnandgaon": "rajnandgaon",
    "Sakti": "sakti",
    "Sarangarh-Bilaigarh": "sarangarh-bilaigarh",
    "Sukma": "sukma",
    "Surajpur": "surajpur",
    "Surguja": "surguja"
}

# ─── LAYER 1: Core Teaching Role Keywords ────────────────────────────────────
# These ALONE satisfy the teaching requirement. They are very specific to
# classroom/educational instruction roles. Over-broad terms that also appear
# in hospital/admin/infrastructure contexts have been moved to SUPPORT list.
CORE_TEACHING_KEYWORDS = [
    "shikshak", "शिक्षक",
    "teacher",
    "lecturer",
    "pgt", "tgt", "prt",
    "faculty",
    "professor",
    "assistant professor",
    "adhyapak", "अध्यापक",
    "व्याख्याता",           # Hindi: lecturer/reader post
    "teaching",
    "physical education teacher", "pe teacher",
    "art teacher", "music teacher",
    "computer teacher", "science teacher", "math teacher", "hindi teacher",
    "english teacher", "social science teacher", "vocational teacher",
    # CG-specific school programme names — always teaching recruitment
    "swami atmanand", "स्वामी आत्मानंद",
    "sages", "सेजेस",
    "eklavya", "एकलव्य",
    # Head teaching roles
    "headmaster", "head master",
    "प्रधानाध्यापक",
    "प्राचार्य",    # principal of a school (not principal secretary)
]

# ─── LAYER 2: Teaching-Support Keywords ──────────────────────────────────────
# These contribute to relevance but do NOT alone satisfy the teaching check.
# A match here only counts when combined with at least one CORE keyword.
TEACHING_SUPPORT_KEYWORDS = [
    "lab attendant", "lab sahayak", "प्रयोगशाला सहायक",  # school lab attendant
    "computer lab",      # school computer lab (must appear with core keyword)
    "science lab",       # school science lab
    "educational",
    "instructor",
    "tutor",
    "physical education",  # department name, not always a teacher post alone
    "principal",           # school principal — only valid with core/school context
]

# ─── Librarian: context-dependent ─────────────────────────────────────────────
# "librarian" is only a teaching-sector post when it appears with school/vidyalaya context.
# Public/district library vacancies are NOT teaching posts.
LIBRARIAN_CONTEXT_REQUIRED = ["school", "vidyalaya", "विद्यालय", "college", "महाविद्यालय",
                               "university", "विश्वविद्यालय", "kendriya", "navodaya", "atmanand", "sages"]

# Employment type keywords (must match at least one — defines HOW the post is filled)
EMPLOYMENT_TYPE_KEYWORDS = [
    # Guest / Atithi
    "atithi", "अतिथि", "guest",
    # Samvida / Contractual
    "samvida", "संविदा", "contractual",
    # Contract basis
    "contract basis", "on contract", "contract",
    # Part-Time
    "part-time", "part time", "parttime", "अंशकालिक",
    # Permanent / Regular
    "permanent", "स्थाई", "niyamit", "नियमित", "regular post", "नियमित पद", "स्थायी",
    # Temporary / Ad-hoc
    "temporary", "अस्थाई", "अस्थायी", "ad-hoc", "ad hoc", "adhoc",
    # Walk-in (implies direct employment offer)
    "walk-in", "walk in",
    # Deputation
    "deputation", "प्रतिनियुक्ति",
]

# ─── Merit & Result Keywords ──────────────────────────────────────────────────
MERIT_KEYWORDS = [
    "merit list", "merit suchi", "मेरिट सूची", "मेरिट",
    "claim", "objection", "दावा", "आपत्ति", "dawa", "aapatti",
    "document verification", "dastavej", "दस्तावेज", "verification", "re-verification", "सत्यापन",
    "corrigendum", "amendment", "संशोधन", "cancellation", "निरस्त", "postponed",
    "selection list", "waiting list", "provisional list", "provisonal", "shortlist", "short-list", "shortlisted",
    "list of candidates", "candidate list", "admit card", "call letter", "exam schedule",
    "syllabus", "roster", "exam center", "examination pattern", "answer key", "result", "परिणाम"
]

# ─── Hard Exclusion Keywords ──────────────────────────────────────────────────
# Confirmed false-positive categories based on user feedback:
# 1. Health/NHM/nurse posts (not school-lab related)
# 2. Administrative posts (peon, driver, clerk, sweeper)
# 3. Infrastructure tenders (building, civil work, construction)
HARD_EXCLUSION_KEYWORDS = [
    # ── Admin events (not vacancies) ──
    "admission", "entrance", "fee", "transfer", "holiday", "calendar",
    "training", "sports meet", "festival",

    # ── Admin posts (peon, driver, clerk — confirmed false positives) ──
    "peon", "चपरासी",
    "driver", "चालक",
    "sweeper", "सफाई कर्मी",
    "chowkidar", "चौकीदार",
    "watchman",
    "night watchman", "night wachman",
    "clerk", "लिपिक",
    "accounting", "लेखा",
    "admin",
    "data entry operator", "डेटा एंट्री",
    "store keeper",
    "house mother",
    "probation officer",
    "social worker", "समाज कार्यकर्ता",

    # ── Health/NHM posts (confirmed false positives; school lab attendant is NOT excluded) ──
    "health mission", "national health mission", "राष्ट्रीय स्वास्थ्य मिशन",
    "women empowerment", "child development",
    "स्वास्थ्य मिशन", "चिकित्सा एवं स्वास्थ्य", "महिला एवं बाल विकास",
    "pharmacist", "फार्मासिस्ट",
    "staff nurse", "स्टाफ नर्स",
    "nursing", "नर्सिंग",
    "medical officer", "चिकित्सा अधिकारी",
    "anm ", "asha worker", "आशा कार्यकर्ता",
    "mitanin", "मितानिन",
    "anganwadi", "आंगनवाड़ी",
    "sahayika", "सहायिका",
    "cmho", "chmo", "c.m.h.o.",
    "ward boy", "ward aaya",
    "dresser",
    "lab technician", "laboratory technician", "प्रयोगशाला तकनीशियन",
    "pathologist",
    "radiographer",

    # ── Infrastructure tenders (confirmed false positives) ──
    "निर्माण कार्य", "निर्माण",
    "construction work", "civil work", "civil tender",
    "building construction", "building tender",
    "it infrastructure", "it tender", "computer equipment",
    "equipment supply", "supply of",
    "bank", "deposit", "tender", "panel", "fdr", "f d r", "audit", "security", "cleaning",
    "बैंक", "जमा", "निविदा", "पैनल", "अल्पावधि", "एफडीआर", "ऑडिट", "सुरक्षा",

    # ── Non-teaching rural/livelihood programmes ──
    "livelihood", "bihaan", "nrlm", "srlm", "आजीविका",
    "ration", "राशन",

    # ── Miscellaneous (non-job events) ──
    "warden",
    "cook ", "रसोइया",
    "eductor",
    "principal secretary", "chief secretary",  # IAS officer – not school principal
]

INDIAN_STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa",
    "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala",
    "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland",
    "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura",
    "Uttar Pradesh", "Uttarakhand", "West Bengal", "Andaman and Nicobar Islands",
    "Chandigarh", "Dadra and Nagar Haveli", "Daman and Diu", "Delhi", "Lakshadweep",
    "Puducherry", "Ladakh", "Jammu and Kashmir"
]

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}


# ─── Keyword Check Functions ──────────────────────────────────────────────────

def _has_librarian_in_context(text: str) -> bool:
    """Returns True if 'librarian' appears AND a school/education context keyword is nearby."""
    t = text.lower()
    if "librarian" not in t:
        return False
    return any(ctx in t for ctx in LIBRARIAN_CONTEXT_REQUIRED)


def is_teaching_job(text: str) -> bool:
    """
    Returns True if the text signals a teaching role.
    Core keywords satisfy this alone. Support keywords require at least one core keyword too.
    Context-dependent librarian is checked separately.
    """
    t = text.lower()
    if any(k in t for k in CORE_TEACHING_KEYWORDS):
        return True
    if _has_librarian_in_context(text):
        return True
    # Support keywords only count when combined with a core keyword in the same text.
    # (This prevents "computer lab tender" or "educational grant" from passing alone.)
    return False


def is_employment_type_job(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in EMPLOYMENT_TYPE_KEYWORDS)


# Backward compat alias
def is_contract_job(text: str) -> bool:
    return is_employment_type_job(text)


def is_excluded(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in HARD_EXCLUSION_KEYWORDS)


def get_doc_type(text: str) -> str:
    """Returns 'merit' if text indicates a merit list or process document, else 'job'."""
    t = text.lower()
    
    # 1. Absolute process/merit keywords
    if any(k in t for k in MERIT_KEYWORDS):
        return "merit"
        
    # 2. Check for interview (except walk-in)
    if "interview" in t or "साक्षात्कार" in t:
        if "walk-in" in t or "walk in" in t or "walkin" in t:
            return "job"
        return "merit"
        
    # 3. Check for any list/suchi combined with candidates/selection/eligible/etc.
    list_words = ["list", "suchi", "सूची"]
    if any(lw in t for lw in list_words):
        merit_list_qualifiers = [
            "candidate", "applicant", "eligible", "ineligible", "select", "chayan", "चयन", 
            "final", "posting", "preference", "provisonal", "provisional", "waiting", "pratiksha", "प्रतीक्षा",
            "appointment", "order", "नियुक्ति", "पात्र", "अपात्र", "selected"
        ]
        if any(q in t for q in merit_list_qualifiers):
            return "merit"
            
    return "job"


def keyword_match(text: str) -> bool:
    return not is_excluded(text) and is_teaching_job(text) and is_employment_type_job(text)


# ─── NEW: Title Confidence Scorer ─────────────────────────────────────────────

# Vague single-word or very short titles that are almost never actual vacancy notices.
VAGUE_TITLE_PATTERNS = [
    r"^recruitment$", r"^vacancy$", r"^notification$", r"^notice$",
    r"^advertisement$", r"^advt\.?$", r"^भर्ती$", r"^रिक्ति$",
    r"^सूचना$", r"^विज्ञापन$", r"^post$", r"^posts?$",
]
_VAGUE_RE = re.compile("|".join(VAGUE_TITLE_PATTERNS), re.IGNORECASE)


def title_confidence_score(title: str) -> float:
    """
    Returns a confidence score 0.0–1.0 for how likely this title represents
    a real teaching vacancy (vs. a generic/process document).

    0.0–0.29  → Very low confidence (vague/generic title) — should be rejected
    0.30–0.59 → Moderate — accept only if PDF also confirms
    0.60–0.79 → High — accept even if PDF fails to download
    0.80–1.0  → Very high — specific, named teaching post
    """
    t = title.lower().strip()

    # Absolute rejection: generic single-word or very short titles
    if _VAGUE_RE.match(t) or len(t) < 20:
        return 0.1

    score = 0.0

    # Core teaching role explicitly named
    if any(k in t for k in CORE_TEACHING_KEYWORDS):
        score += 0.45

    # Librarian in school context
    if _has_librarian_in_context(title):
        score += 0.35

    # Employment type explicitly in title
    if is_employment_type_job(t):
        score += 0.25

    # Subject specificity (PGT/TGT/PRT + known title pattern)
    if any(k in t for k in ["pgt", "tgt", "prt", "व्याख्याता", "शिक्षक पद", "lecturer post"]):
        score += 0.15

    # Named CG school programme — strong indicator of teaching vacancy
    if any(k in t for k in ["swami atmanand", "sages", "eklavya", "navodaya", "kendriya vidyalaya"]):
        score += 0.25

    # Penalize if any hard-exclusion signal is present
    if is_excluded(t):
        score -= 0.4

    return max(0.0, min(score, 1.0))


# ─── Employment Type / Category Helpers ───────────────────────────────────────

def get_employment_type(text: str) -> str:
    """Detect employment type label from text."""
    t = text.lower()
    if any(k in t for k in ["atithi", "अतिथि", "guest"]):
        return "Guest"
    if any(k in t for k in ["samvida", "संविदा"]):
        return "Samvida"
    if any(k in t for k in ["part-time", "part time", "अंशकालिक"]):
        return "Part-Time"
    if any(k in t for k in ["temporary", "अस्थाई", "अस्थायी", "ad-hoc", "ad hoc", "adhoc"]):
        return "Temporary"
    if any(k in t for k in ["deputation", "प्रतिनियुक्ति"]):
        return "Deputation"
    if any(k in t for k in ["permanent", "स्थाई", "नियमित", "niyamit", "स्थायी"]):
        return "Permanent"
    # Generic contract fallback
    return "Contract"


def evaluate_pdf(pdf_url: str, title: str = "") -> tuple:
    """
    Returns (is_valid, extracted_text, pdf_score).
    Passes the title into the evaluator for context-aware scoring.
    """
    try:
        res = evaluate_pdf_for_teaching_job(pdf_url, title=title)

        if res["method_used"] == "error":
            return False, "", 0

        text = res["text"]

        # Respect the evaluator's verdict (raised threshold already inside evaluator)
        if not res["is_teaching_job"]:
            return False, text, res.get("score", 0)

        return True, text, res.get("score", 0)
    except Exception as e:
        print(f"[WARN] PDF Parse Error: {e}")
        return False, "", 0


def normalize_date(date_str: str) -> str:
    """Convert DD/MM/YYYY or similar to YYYY-MM-DD for frontend filtering."""
    if not date_str:
        return ""
    m = re.match(r'(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})', date_str)
    if m:
        d, mo, y = m.group(1), m.group(2), m.group(3)
        if len(y) == 2:
            y = "20" + y
        return f"{y}-{mo.zfill(2)}-{d.zfill(2)}"
    return date_str


def extract_dates(texts: list) -> tuple:
    date_pattern = re.compile(r'\b(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})\b')
    dates = []
    for t in texts:
        dates.extend(date_pattern.findall(t))

    today = datetime.now(IST).strftime("%d/%m/%Y")
    start = dates[0] if len(dates) > 0 else today
    end = dates[1] if len(dates) > 1 else None
    return start, end


def extract_state(text: str) -> str:
    t = text.lower()
    for state in INDIAN_STATES:
        if state.lower() in t:
            return state

    # City to State mapping for common teaching hubs
    city_map = {
        "Delhi": "Delhi", "New Delhi": "Delhi", "Mumbai": "Maharashtra", "Pune": "Maharashtra",
        "Bangalore": "Karnataka", "Bengaluru": "Karnataka", "Chennai": "Tamil Nadu",
        "Hyderabad": "Telangana", "Kolkata": "West Bengal", "Ahmedabad": "Gujarat",
        "Jaipur": "Rajasthan", "Lucknow": "Uttar Pradesh", "Patna": "Bihar",
        "Bhopal": "Madhya Pradesh", "Indore": "Madhya Pradesh", "Chandigarh": "Chandigarh",
        "Kochi": "Kerala", "Guwahati": "Assam", "Bhubaneswar": "Odisha", "Raipur": "Chhattisgarh"
    }
    for city, state in city_map.items():
        if city.lower() in t:
            return state

    return "All India"


def extract_school(title: str) -> str:
    t = title.lower()
    if "swami atmanand" in t or "sages" in t:
        return "Swami Atmanand English Medium School"
    if "kvs" in t or "kendriya vidyalaya" in t:
        return "Kendriya Vidyalaya"
    if "emrs" in t or "eklavya" in t:
        return "Eklavya Model Residential School"
    if "navodaya" in t or "nvs" in t:
        return "Navodaya Vidyalaya"
    return "District Collectorate"


def categorize(title: str) -> str:
    t = title.lower()
    if any(k in t for k in ["swami atmanand", "स्वामी", "sages"]):
        return "Swami Atmanand"
    if any(k in t for k in ["emrs", "eklavya", "एकलव्य"]):
        return "EMRS"
    if any(k in t for k in ["kvs", "kendriya vidyalaya"]):
        return "KVS"
    if any(k in t for k in ["navodaya", "nvs"]):
        return "NVS"
    if any(k in t for k in ["atithi", "अतिथि"]):
        return "Atithi"
    if any(k in t for k in ["samvida", "संविदा", "contract"]):
        return "Contract"
    return "Other"


def make_id(title: str, district: str) -> str:
    return hashlib.sha1(f"{title}{district}".encode()).hexdigest()[:12]


# ─── Core Scraping Logic ──────────────────────────────────────────────────────

def _process_pdf_entry(title: str, full_text_check: str, pdf_link: str) -> tuple:
    """
    Multi-layer confidence gate:
    1. Hard exclusion check
    2. Teaching keyword check (core keywords)
    3. Employment type check
    4. Title confidence score
    5. PDF evaluator score
    Returns (should_include, pdf_text).
    """
    # Layer 1: Hard exclusion (always reject immediately)
    if is_excluded(full_text_check):
        return False, ""

    has_teaching = is_teaching_job(full_text_check)
    has_emp_type = is_employment_type_job(full_text_check)

    # Layer 4: Title confidence score
    title_conf = title_confidence_score(title)

    # If title is extremely vague, skip immediately — PDF can't save a bad title
    if title_conf < 0.15:
        return False, ""

    # Layer 5: PDF evaluation
    is_valid, pdf_text, pdf_score = evaluate_pdf(pdf_link, title=title)

    # If PDF was downloaded, augment text check with PDF content
    if pdf_text:
        full_text_check_augmented = full_text_check + " " + pdf_text
        has_teaching = is_teaching_job(full_text_check_augmented)
        has_emp_type = is_employment_type_job(full_text_check_augmented)

    # ── Decision matrix ──
    # Case A: PDF confirmed valid → accept if teaching + employment type confirmed
    if is_valid:
        return (has_teaching and has_emp_type), pdf_text

    # Case B: PDF failed to download (timeout/403/SSL) or returned error
    #   → Trust title ONLY if it is highly confident (≥ 0.70) AND
    #     both teaching and employment type are satisfied from title alone
    if not is_valid:
        if title_conf >= 0.70 and has_teaching and has_emp_type:
            return True, pdf_text
        # PDF downloaded but scored too low → both must fail gracefully
        return False, pdf_text

    return False, ""



def scrape_district(name: str, slug: str) -> list:
    base_urls = [
        f"https://{slug}.gov.in/en/notice_category/recruitment/",
        f"https://{slug}.gov.in/en/past-notices/recruitment/",
        f"https://{slug}.nic.in/en/notice_category/recruitment/",
        f"https://{slug}.nic.in/en/past-notices/recruitment/",
    ]

    jobs_dict = {}
    MAX_PAGES = 10

    for base_url in base_urls:
        for page in range(1, MAX_PAGES + 1):
            url = base_url if page == 1 else f"{base_url}page/{page}/"
            try:
                r = requests.get(url, timeout=15, headers=UA, verify=False)
                r.raise_for_status()
            except Exception:
                break

            soup = BeautifulSoup(r.text, "lxml")
            pdfs_found = False

            for a in soup.find_all("a", href=re.compile(r"\.pdf", re.I)):
                pdfs_found = True
                tr = a.find_parent("tr")
                title = ""
                texts = []

                if tr:
                    tds = tr.find_all(["td", "th"])
                    texts = [td.get_text(separator=' ', strip=True) for td in tds]
                    # Pick the most specific candidate: longest text that has a CORE keyword
                    candidates = sorted(
                        [t for t in texts if len(t) > 15 and is_teaching_job(t)],
                        key=lambda t: title_confidence_score(t),
                        reverse=True
                    )
                    if candidates:
                        title = candidates[0]
                else:
                    # Fallback if not inside a traditional tr (div structure)
                    for sib in a.find_all_previous(string=True, limit=10):
                        candidate = sib.strip()
                        if len(candidate) > 15 and is_teaching_job(candidate):
                            title = candidate
                            break
                    texts = [title] if title else []

                if not title:
                    link_text = a.get_text(separator=' ', strip=True)
                    if len(link_text) > 15 and is_teaching_job(link_text):
                        if not re.match(r'^view\b', link_text, re.IGNORECASE) and not re.search(r'\d+\s*(mb|kb)', link_text, re.IGNORECASE):
                            title = link_text
                            texts = [title]
                    if not title:
                        continue

                # Pre-flight: reject vague titles immediately (saves a PDF download)
                if title_confidence_score(title) < 0.15:
                    continue

                job_id = make_id(title, name)
                pdf_link = a["href"] if a["href"].startswith("http") else f"https://{slug}.gov.in{a['href']}"
                link_label = a.get_text(separator=' ', strip=True) or "View Document"

                # If we already validated this identical job title, just append new PDF
                if job_id in jobs_dict:
                    if not any(u["url"] == pdf_link for u in jobs_dict[job_id]["job_urls"]):
                        jobs_dict[job_id]["job_urls"].append({"label": link_label, "url": pdf_link})
                    continue

                full_text_check = " ".join(texts) + " " + title

                # Run the multi-layer confidence gate
                valid, pdf_text = _process_pdf_entry(title, full_text_check, pdf_link)
                if not valid:
                    continue

                if pdf_text:
                    full_text_check += " " + pdf_text

                start_date, end_date = extract_dates(texts)
                emp_type = get_employment_type(full_text_check)

                jobs_dict[job_id] = {
                    "id": job_id,
                    "title": title,
                    "category": categorize(title),
                    "employment_type": emp_type,
                    "district": name,
                    "school": extract_school(title),
                    "start_date": start_date,
                    "posted_date": normalize_date(start_date),
                    "end_date": end_date,
                    "job_url": pdf_link,
                    "job_urls": [{"label": link_label, "url": pdf_link}],
                    "doc_type": get_doc_type(full_text_check)
                }

            # If we successfully loaded a page but it had no PDFs, stop paginating this base_url
            if not pdfs_found and page > 1:
                break

    jobs = list(jobs_dict.values())
    print(f"[INFO] {name}: Found {len(jobs)} jobs")
    return jobs


def scrape_central_source(source_name: str, base_url: str, domain_url: str) -> list:
    """Generic scraper for central school portals."""
    jobs_dict = {}
    MAX_PAGES = 10

    for page in range(1, MAX_PAGES + 1):
        url = base_url if page == 1 else f"{base_url}?page={page-1}"
        if "/page/" in base_url or base_url.endswith("/"):
            url = base_url if page == 1 else f"{base_url.rstrip('/')}/page/{page}/"

        try:
            r = requests.get(url, timeout=15, headers=UA, verify=False)
            r.raise_for_status()
        except Exception as e:
            if page == 1:
                print(f"[WARN] {source_name} ({url}): {e}")
            break

        soup = BeautifulSoup(r.text, "lxml")
        pdfs_found = False

        for a in soup.find_all("a", href=re.compile(r"\.pdf", re.I)):
            pdfs_found = True
            tr = a.find_parent("tr")
            title = ""
            texts = []

            if tr:
                tds = tr.find_all(["td", "th"])
                texts = [td.get_text(separator=' ', strip=True) for td in tds]
                candidates = sorted(
                    [t for t in texts if len(t) > 10 and is_teaching_job(t)],
                    key=lambda t: title_confidence_score(t),
                    reverse=True
                )
                if candidates:
                    title = candidates[0]

            if not title:
                parent = a.find_parent(["li", "div", "p"])
                if parent:
                    candidate = parent.get_text(separator=' ', strip=True)
                    if len(candidate) > 10 and is_teaching_job(candidate):
                        title = candidate[:200]

            if not title:
                link_text = a.get_text(separator=' ', strip=True)
                if len(link_text) > 10 and is_teaching_job(link_text):
                    if not re.match(r'^view\b', link_text, re.IGNORECASE) and not re.search(r'\d+\s*(mb|kb)', link_text, re.IGNORECASE):
                        title = link_text

            if not title:
                continue

            # Pre-flight vague title check
            if title_confidence_score(title) < 0.15:
                continue

            href = a.get("href", "")
            pdf_link = href if href.startswith("http") else domain_url.rstrip("/") + "/" + href.lstrip("/")
            link_label = a.get_text(separator=' ', strip=True) or "View Notice"
            if len(link_label) < 3:
                link_label = "View Notice"

            full_text_check = " ".join(texts) + " " + title

            valid, pdf_text = _process_pdf_entry(title, full_text_check, pdf_link)
            if not valid:
                continue

            if pdf_text:
                full_text_check += " " + pdf_text

            job_id = make_id(title, source_name)

            if job_id in jobs_dict:
                if not any(u["url"] == pdf_link for u in jobs_dict[job_id]["job_urls"]):
                    jobs_dict[job_id]["job_urls"].append({"label": link_label, "url": pdf_link})
                continue

            start_date, end_date = extract_dates(texts)
            emp_type = get_employment_type(full_text_check)
            if emp_type == "Permanent":
                state_found = "All India"
            else:
                state_found = extract_state(full_text_check)

            jobs_dict[job_id] = {
                "id": job_id,
                "title": title,
                "category": source_name,
                "employment_type": emp_type,
                "district": state_found,
                "school": source_name,
                "start_date": start_date,
                "posted_date": normalize_date(start_date),
                "end_date": end_date,
                "job_url": pdf_link,
                "job_urls": [{"label": link_label, "url": pdf_link}],
                "doc_type": get_doc_type(full_text_check)
            }

        if not pdfs_found and page > 1:
            break

    jobs = list(jobs_dict.values())
    print(f"[INFO] {source_name}: Found {len(jobs)} jobs")
    return jobs


def scrape_kvs() -> list:
    print("[INFO] Scraping KVS...")
    urls_to_try = [
        "https://kvsangathan.nic.in/sakshatkara-soochana/",
        "https://kvsangathan.nic.in/en/employment/",
        "https://kvsangathan.nic.in/en/notifications-recruitment/",
    ]
    for url in urls_to_try:
        jobs = scrape_central_source("KVS", url, "https://kvsangathan.nic.in")
        if jobs:
            return jobs
    return scrape_central_source("KVS", "https://kvsangathan.nic.in/", "https://kvsangathan.nic.in")


def scrape_nvs() -> list:
    print("[INFO] Scraping NVS...")
    urls_to_try = [
        "https://navodaya.gov.in/nvs/en/Recruitment/Notification-Vacancies/",
        "https://navodaya.gov.in/nvs/en/Notifications-Recruitment/",
    ]
    for url in urls_to_try:
        try:
            jobs = scrape_central_source("NVS", url, "https://navodaya.gov.in")
            if jobs:
                return jobs
        except Exception:
            continue
    return []


def scrape_emrs() -> list:
    print("[INFO] Scraping EMRS...")
    urls_to_try = [
        "https://nests.tribal.gov.in/show_content.php?lang=1&level=1&ls_id=949&lid=550",
        "https://emrs.tribal.gov.in/",
        "https://nests.gov.in/recruitment",
    ]
    for url in urls_to_try:
        try:
            jobs = scrape_central_source("EMRS", url, url.rsplit("/", 2)[0])
            if jobs:
                return jobs
        except Exception:
            continue
    return []


def load_existing(path="data.json") -> list:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f).get("jobs", [])
    except Exception:
        return []


def merge(existing: list, fresh: list) -> list:
    """
    Merge freshly scraped jobs with existing cached jobs.
    Old cached jobs now undergo the FULL validation (teaching + employment type +
    title confidence) to purge past false positives from the cache.
    """
    seen = {j["id"] for j in fresh}
    kept = []
    for j in existing:
        if j["id"] not in seen:
            title = j.get("title", "")
            # Full re-validation for old cached entries
            if (not is_excluded(title)
                    and is_teaching_job(title)
                    and is_employment_type_job(title)          # NEW: was missing before
                    and title_confidence_score(title) >= 0.30  # NEW: reject vague titles
            ):
                j["doc_type"] = get_doc_type(title)
                kept.append(j)
    return fresh + kept


def save_jobs(jobs: list, path: str):
    existing = load_existing(path)
    merged = merge(existing, jobs)
    payload = {
        "last_updated": datetime.now(IST).isoformat(timespec="seconds"),
        "jobs": merged,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(merged)} jobs to {path}")

    # Also save as .js for local file:// access
    js_path = path.replace('.json', '.js')
    var_name = "STATE_DATA" if "central" not in path else "CENTRAL_DATA"
    with open(js_path, "w", encoding="utf-8") as f:
        f.write(f"window.{var_name} = ")
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write(";")


if __name__ == "__main__":
    import urllib3
    import concurrent.futures
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # --- STATE vacancies (CG districts — teaching posts with employment type) ---
    state_jobs = []
    print("[INFO] Starting parallel state scrape...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        future_to_district = {executor.submit(scrape_district, name, slug): name for name, slug in DISTRICTS.items()}
        for future in concurrent.futures.as_completed(future_to_district):
            district_name = future_to_district[future]
            try:
                state_jobs += future.result()
            except Exception as e:
                print(f"[ERROR] Failed to scrape {district_name}: {e}")

    save_jobs(state_jobs, "data.json")
    print(f"State: {len(state_jobs)} fresh jobs scraped.")

    # --- CENTRAL vacancies (KVS, NVS, EMRS — all employment types for teaching posts) ---
    central_jobs = []
    print("[INFO] Starting parallel central scrape...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        future_to_central = {
            executor.submit(scrape_kvs): "KVS",
            executor.submit(scrape_nvs): "NVS",
            executor.submit(scrape_emrs): "EMRS"
        }
        for future in concurrent.futures.as_completed(future_to_central):
            name = future_to_central[future]
            try:
                central_jobs += future.result()
            except Exception as e:
                print(f"[ERROR] Failed to scrape {name}: {e}")

    save_jobs(central_jobs, "data_central.json")
    print(f"Central: {len(central_jobs)} fresh jobs scraped.")

    # --- AUTO-CHAIN: Run post-scrape clean pass on both data files ---
    print("[INFO] Saving PDF evaluator cache...")
    try:
        from pdf_evaluator import save_cache_to_disk
        save_cache_to_disk()
    except Exception as e:
        print(f"[WARN] Failed to save cache: {e}")

    print("[INFO] Running post-scrape validation pass via clean_data.py...")
    try:
        import clean_data
        clean_data.clean_file("data.json")
        clean_data.clean_file("data_central.json")
        print("[INFO] Post-scrape clean complete.")
    except Exception as e:
        print(f"[WARN] Post-scrape clean failed: {e}")