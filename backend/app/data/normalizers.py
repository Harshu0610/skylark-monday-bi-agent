"""Pure normalization functions.

Every function here is deterministic, side-effect free, and unit tested. This is
where correctness actually lives -- the agent layer above it can only be as good
as these are.

Governing principle: NEVER DESTROY INFORMATION.
  - Raw values are preserved alongside normalized ones.
  - Unparseable values become None and are FLAGGED, never guessed.
  - A missing amount is None. It is never zero. Zero is a real business fact
    and conflating it with "unknown" is the single most damaging silent error
    available in this dataset (52% of deal values are missing).
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime
from typing import Any

from dateutil import parser as date_parser

# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------

_WHITESPACE = re.compile(r"\s+")

NULL_TOKENS = {
    "", "-", "--", "n/a", "na", "nan", "none", "null", "nil", "tbd", "tba",
    "not available", "not applicable", "#n/a", "?", ".",
}


def clean_text(value: Any) -> str | None:
    """Trim, collapse internal whitespace, and map null-ish tokens to None."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = _WHITESPACE.sub(" ", str(value)).strip()
    if text.lower() in NULL_TOKENS:
        return None
    return text or None


def normalize_key(value: Any) -> str | None:
    """Lowercase comparison key used for joins and alias lookups."""
    text = clean_text(value)
    if text is None:
        return None
    return _WHITESPACE.sub(" ", text.lower()).strip()


def is_header_echo(value: Any, column_name: str) -> bool:
    """True when a cell contains its own column's name.

    These sheets were built by concatenating exports without stripping headers,
    so some rows are the header repeated as data. Left in, they create phantom
    categories such as a sector literally called "Sector/service".
    """
    a = normalize_key(value)
    b = normalize_key(column_name)
    return a is not None and b is not None and a == b


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

_EXPLICIT_FORMATS = (
    "%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y",
    "%d-%b-%Y", "%d-%b-%y", "%d %b %Y", "%d %B %Y",
    "%b %d, %Y", "%B %d, %Y", "%b %d %Y",
    "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S",
)

# dd/mm/yyyy and mm/dd/yyyy are indistinguishable when the day is <= 12.
_AMBIGUOUS_SLASH = re.compile(r"^\s*(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\s*$")


def parse_date(value: Any) -> tuple[date | None, str | None]:
    """Parse a messy date. Returns (date, quality_flag).

    Assumption: day-first. The source is an Indian business, where dd/mm/yyyy
    is the convention. Genuinely ambiguous values are flagged so the ledger can
    surface the assumption rather than hiding it.
    """
    if value is None:
        return None, None
    if isinstance(value, datetime):
        return value.date(), None
    if isinstance(value, date):
        return value, None
    if isinstance(value, float) and math.isnan(value):
        return None, None

    text = clean_text(value)
    if text is None:
        return None, None

    flag: str | None = None
    match = _AMBIGUOUS_SLASH.match(text)
    if match:
        first, second = int(match.group(1)), int(match.group(2))
        if first <= 12 and second <= 12 and first != second:
            flag = "date_ambiguous_dayfirst_assumed"

    for fmt in _EXPLICIT_FORMATS:
        try:
            return datetime.strptime(text, fmt).date(), flag
        except ValueError:
            continue

    try:
        parsed = date_parser.parse(text, dayfirst=True, fuzzy=False)
        return parsed.date(), flag
    except (ValueError, OverflowError, TypeError):
        return None, "date_unparseable"


# ---------------------------------------------------------------------------
# Amounts
# ---------------------------------------------------------------------------

# The trailing \.? must sit AFTER the word boundary: in "Rs. 1,00,000" the
# boundary falls between "s" and ".", so `\brs\.?\b` matches only "Rs" and
# leaves a stray dot that turns the value into 0.1.
_CURRENCY_SYMBOLS = re.compile(r"[\u20b9$\u20ac\u00a3]|(?i:\brs\b\.?|\binr\b|\busd\b)")
# Leading/trailing punctuation left behind after symbol removal.
_EDGE_PUNCTUATION = re.compile(r"^[^\d(+-]+|[^\d)%a-zA-Z]+$")
_SUFFIXES = (
    ("cr", 10_000_000), ("crore", 10_000_000), ("crores", 10_000_000),
    ("l", 100_000), ("lac", 100_000), ("lakh", 100_000), ("lakhs", 100_000),
    ("m", 1_000_000), ("mn", 1_000_000),
    ("k", 1_000),
)


def parse_amount(value: Any) -> tuple[float | None, str | None]:
    """Parse a monetary value. Returns (amount, quality_flag).

    Handles both Western (100,000) and Indian lakh (1,00,000) grouping, plus
    K / L / Cr / M suffixes. Monday's CSV import frequently coerces numeric
    columns to text, so this runs even though the source XLSX stores floats.

    Missing or unparseable ALWAYS yields None, never 0.0.
    """
    if value is None:
        return None, "amount_missing"
    if isinstance(value, bool):
        return None, "amount_invalid"
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None, "amount_missing"
        return float(value), None

    text = clean_text(value)
    if text is None:
        return None, "amount_missing"

    text = _CURRENCY_SYMBOLS.sub("", text).strip()
    text = _EDGE_PUNCTUATION.sub("", text).strip()
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1].strip()

    multiplier = 1
    lowered = text.lower()
    for suffix, factor in _SUFFIXES:
        if lowered.endswith(suffix):
            candidate = lowered[: -len(suffix)].strip()
            # Only treat it as a suffix if what remains is actually numeric.
            if candidate and re.fullmatch(r"[\d,.\s]+", candidate):
                text = candidate
                multiplier = factor
                break

    text = text.replace(",", "").replace(" ", "")
    if not text:
        # There WAS content, it just wasn't a number ("ask finance").
        # That is a different data problem from an empty cell.
        return None, "amount_invalid"

    try:
        amount = float(text) * multiplier
    except ValueError:
        return None, "amount_invalid"

    if math.isnan(amount) or math.isinf(amount):
        return None, "amount_invalid"
    return (-amount if negative else amount), None


# ---------------------------------------------------------------------------
# Categoricals
# ---------------------------------------------------------------------------

DEAL_STATUS_ALIASES: dict[str, str] = {
    "won": "Won", "closed won": "Won", "closed-won": "Won", "close won": "Won",
    "dead": "Lost", "lost": "Lost", "closed lost": "Lost", "closed-lost": "Lost",
    "project lost": "Lost", "dropped": "Lost",
    "open": "Open", "active": "Open", "in progress": "Open",
    "on hold": "OnHold", "hold": "OnHold", "paused": "OnHold",
}


def normalize_deal_status(value: Any) -> tuple[str, str | None]:
    """Map a deal status onto the canonical vocabulary.

    Unrecognised values become 'Unknown' and are FLAGGED -- they are a data
    finding to report, not a row to silently discard.
    """
    key = normalize_key(value)
    if key is None:
        return "Unknown", "status_missing"
    mapped = DEAL_STATUS_ALIASES.get(key)
    if mapped is None:
        return "Unknown", "status_unmapped"
    return mapped, None


EXEC_STATUS_ALIASES: dict[str, str] = {
    "completed": "Completed",
    "complete": "Completed",
    "executed until current month": "Completed",
    "ongoing": "InProgress",
    "in progress": "InProgress",
    "not started": "NotStarted",
    "yet to start": "NotStarted",
    "pause / struck": "Paused",
    "pause/struck": "Paused",
    "paused": "Paused",
    "struck": "Paused",
    "partial completed": "PartiallyComplete",
    "partially completed": "PartiallyComplete",
    "details pending from client": "Blocked",
    "blocked": "Blocked",
}

# Recurring contracts billed monthly are "executed until current month" -- they
# are delivering on schedule, not finished. Treated as complete for completion
# rate but never counted as delayed.
RECURRING_EXEC_STATES = {"Completed"}


def normalize_exec_status(value: Any) -> tuple[str, str | None]:
    key = normalize_key(value)
    if key is None:
        return "Unknown", "exec_status_missing"
    mapped = EXEC_STATUS_ALIASES.get(key)
    if mapped is None:
        return "Unknown", "exec_status_unmapped"
    return mapped, None


SECTOR_ALIASES: dict[str, str] = {
    "mining": "Mining", "mines": "Mining",
    "renewables": "Renewables", "renewable": "Renewables",
    "solar": "Renewables", "wind": "Renewables",
    "powerline": "Powerline", "power line": "Powerline",
    "power": "Powerline", "transmission": "Powerline",
    "railways": "Railways", "railway": "Railways", "rail": "Railways",
    "construction": "Construction", "infra": "Construction",
    "infrastructure": "Construction",
    "dsp": "DSP",
    "tender": "Tender", "tenders": "Tender",
    "manufacturing": "Manufacturing",
    "security and surveillance": "Security and Surveillance",
    "security & surveillance": "Security and Surveillance",
    "security": "Security and Surveillance",
    "aviation": "Aviation",
    "others": "Others", "other": "Others", "misc": "Others",
}


def normalize_sector(value: Any) -> tuple[str | None, str | None]:
    key = normalize_key(value)
    if key is None:
        return None, "sector_missing"
    mapped = SECTOR_ALIASES.get(key)
    if mapped is None:
        # Preserve the original spelling rather than discarding the row.
        return clean_text(value), "sector_unmapped"
    return mapped, None


# ---------------------------------------------------------------------------
# Deal stage (ordered funnel)
# ---------------------------------------------------------------------------

_STAGE_PREFIX = re.compile(r"^\s*([A-Z])\s*[.)]\s*(.+)$", re.IGNORECASE)

# The source uses an A.-O. lettered funnel, which gives us ordering for free.
# "Project Completed" breaks the convention -- it has no letter prefix -- so it
# is mapped explicitly. Without this it sorts to the end and corrupts the funnel.
STAGE_ORDER_OVERRIDES: dict[str, int] = {
    "project completed": 11,
}

STAGE_LABEL_OVERRIDES: dict[str, str] = {
    "project completed": "Project Completed",
}


def normalize_stage(value: Any) -> tuple[str | None, int | None, str | None]:
    """Return (label, funnel_order, quality_flag).

    Order is derived from the letter prefix: A=1 ... O=15.
    """
    text = clean_text(value)
    if text is None:
        return None, None, "stage_missing"

    key = normalize_key(text) or ""
    if key in STAGE_ORDER_OVERRIDES:
        return STAGE_LABEL_OVERRIDES.get(key, text), STAGE_ORDER_OVERRIDES[key], None

    match = _STAGE_PREFIX.match(text)
    if match:
        letter = match.group(1).upper()
        order = ord(letter) - ord("A") + 1
        return text, order, None

    return text, None, "stage_unordered"


# Stages that represent a live commercial opportunity.
OPEN_STAGE_ORDERS = set(range(1, 7))       # A. Lead Generated .. F. Negotiations
WON_STAGE_ORDERS = {7, 8, 9, 10, 11}       # G. Project Won .. K. Amount Accrued
LOST_STAGE_ORDERS = {12}                   # L. Project Lost
DORMANT_STAGE_ORDERS = {13, 14, 15}        # M. On Hold, N./O. Not relevant


# ---------------------------------------------------------------------------
# Probability
# ---------------------------------------------------------------------------

PROBABILITY_WEIGHTS: dict[str, float] = {
    "high": 0.75,
    "medium": 0.45,
    "med": 0.45,
    "low": 0.20,
}

# Fallback when Closure Probability is blank (75% of deals). Derived from the
# funnel position, which is a weaker signal -- flagged so the ledger can say so.
STAGE_FALLBACK_WEIGHTS: dict[int, float] = {
    1: 0.05, 2: 0.10, 3: 0.15, 4: 0.20, 5: 0.35, 6: 0.55,
}


def normalize_probability(
    value: Any, stage_order: int | None
) -> tuple[str | None, float | None, str | None]:
    """Return (label, weight, quality_flag)."""
    key = normalize_key(value)
    if key is not None and key in PROBABILITY_WEIGHTS:
        return clean_text(value), PROBABILITY_WEIGHTS[key], None

    if key is not None:
        return clean_text(value), None, "probability_unmapped"

    if stage_order is not None and stage_order in STAGE_FALLBACK_WEIGHTS:
        return None, STAGE_FALLBACK_WEIGHTS[stage_order], "probability_inferred_from_stage"

    return None, None, "probability_missing"


# ---------------------------------------------------------------------------
# Entity names (cross-board join key)
# ---------------------------------------------------------------------------

_LEGAL_SUFFIXES = re.compile(
    r"\b(pvt\.?|private|ltd\.?|limited|inc\.?|llp|llc|corp\.?|corporation|co\.?)\b",
    re.IGNORECASE,
)
_PUNCTUATION = re.compile(r"[^\w\s]")


def normalize_entity_name(value: Any) -> str | None:
    """Normalize an account / deal name for cross-board joining.

    NOTE: in this dataset the join runs on DEAL NAME, not customer code -- the
    two boards mask customers in different namespaces (COMPANY089 vs
    WOCOMPANY_002) with zero overlap, so a customer join is impossible.
    """
    text = clean_text(value)
    if text is None:
        return None
    lowered = text.lower()
    lowered = _LEGAL_SUFFIXES.sub(" ", lowered)
    lowered = lowered.replace("&", " and ")
    lowered = _PUNCTUATION.sub(" ", lowered)
    lowered = _WHITESPACE.sub(" ", lowered).strip()
    return lowered or None


# ---------------------------------------------------------------------------
# Prompt-injection screening
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions",
        r"disregard\s+(all\s+)?(previous|prior|the)\s+",
        r"system\s*prompt",
        r"reveal\s+(the\s+)?(api\s*key|token|secret|password)",
        r"you\s+are\s+now\s+",
        r"<\s*/?\s*(script|system|instructions?)\s*>",
    )
]


def looks_like_injection(value: Any) -> bool:
    """Flag board text that is shaped like an instruction to the model.

    Board content is untrusted user input. The architecture already prevents
    this from mattering -- the planner never sees board data, and numbers bypass
    the narrator -- but detecting it turns a security control into a visible
    data-quality signal.
    """
    text = clean_text(value)
    if text is None or len(text) < 12:
        return False
    return any(p.search(text) for p in _INJECTION_PATTERNS)
