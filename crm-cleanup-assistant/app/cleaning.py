"""Data validation and duplicate detection. Pure Python, no AI needed."""
import re
from itertools import combinations

from rapidfuzz import fuzz

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.IGNORECASE)
COMPANY_SUFFIXES = re.compile(r"\b(inc|llc|ltd|corp|co|company|incorporated)\b\.?", re.IGNORECASE)


def digits(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


def normalize_company(company: str) -> str:
    cleaned = COMPANY_SUFFIXES.sub("", company or "")
    return re.sub(r"[^a-z0-9 ]", "", cleaned.lower()).strip()


def email_domain(email: str) -> str:
    return email.split("@")[-1].lower() if email and "@" in email else ""


def validate(contact: dict) -> list[str]:
    """Return a list of data-quality issues for one contact."""
    issues = []
    if not (contact.get("name") or "").strip():
        issues.append("Missing name")
    email = (contact.get("email") or "").strip()
    if not email:
        issues.append("Missing email")
    elif not EMAIL_RE.match(email):
        issues.append(f"Invalid email: {email}")
    phone = digits(contact.get("phone", ""))
    if phone and not 10 <= len(phone) <= 15:
        issues.append(f"Phone looks incomplete: {contact.get('phone')}")
    return issues


def duplicate_score(a: dict, b: dict) -> tuple[float, list[str]]:
    """Score how likely two contacts are the same person (0-100), with reasons."""
    reasons = []
    name_sim = fuzz.token_sort_ratio((a.get("name") or "").lower(), (b.get("name") or "").lower())
    company_a, company_b = normalize_company(a.get("company", "")), normalize_company(b.get("company", ""))
    company_sim = fuzz.ratio(company_a, company_b) if company_a and company_b else 0

    email_a, email_b = (a.get("email") or "").lower(), (b.get("email") or "").lower()
    same_email = bool(email_a) and email_a == email_b
    same_domain = bool(email_domain(email_a)) and email_domain(email_a) == email_domain(email_b)
    phone_a, phone_b = digits(a.get("phone", "")), digits(b.get("phone", ""))
    same_phone = len(phone_a) >= 10 and phone_a == phone_b

    if same_email:
        return 100.0, ["Identical email"]

    score = 0.5 * name_sim + 0.2 * company_sim
    if name_sim >= 80:
        reasons.append(f"Similar names ({name_sim:.0f}%)")
    if company_sim >= 85:
        reasons.append("Same company")
    if same_domain:
        score += 15
        reasons.append("Same email domain")
    if same_phone:
        score += 20
        reasons.append("Same phone number")
    return min(round(score, 1), 100.0), reasons


def find_duplicates(contacts: list[dict], threshold: int) -> list[dict]:
    """Compare every pair of contacts and return the likely duplicates.

    Fine for thousands of records. For very large CRMs, add a blocking step
    (only compare contacts sharing a domain or phone) before pairing.
    """
    pairs = []
    for a, b in combinations(contacts, 2):
        score, reasons = duplicate_score(a, b)
        if score >= threshold:
            pairs.append({"a": a["id"], "b": b["id"], "score": score, "reason": "; ".join(reasons)})
    return sorted(pairs, key=lambda p: p["score"], reverse=True)
