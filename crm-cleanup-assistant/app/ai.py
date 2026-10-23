"""Lead categorization and interaction summaries.

Uses Claude when ANTHROPIC_API_KEY is set; otherwise falls back to simple
keyword rules so the app still runs (and tests pass) without an API key.
"""
import json
import re

from .config import ANTHROPIC_API_KEY, CLAUDE_MODEL, LEAD_CATEGORIES

PROMPT = """You help a B2B sales team keep their CRM clean.

Contact:
Name: {name}
Company: {company}
Interaction notes: {notes}

Pick exactly one category from: {categories}
Then write a one-sentence summary of where this contact stands and the next step.

Reply with JSON only, in this shape:
{{"category": "...", "reason": "short reason for the category", "summary": "..."}}"""


def _rules_based(contact: dict) -> dict:
    notes = (contact.get("notes") or "").lower()
    if re.search(r"customer since|current customer|billing contact|support ticket", notes):
        category, reason = "Existing customer", "Notes show an existing account."
    elif re.search(r"we don't|don't offer|not a fit|wrong", notes):
        category, reason = "Not a fit", "Asked for something the product doesn't do."
    elif re.search(r"pricing|trial|urgent|decision maker|second meeting|start next month", notes):
        category, reason = "Hot", "Buying signals: pricing, trial, or a deadline."
    elif re.search(r"no reply|no response|unsubscribed", notes):
        category, reason = "Cold", "Not responding to outreach."
    else:
        category, reason = "Warm", "Showed interest but no buying signal yet."
    first_sentence = (contact.get("notes") or "No interaction notes.").split(". ")[0].rstrip(".")
    return {"category": category, "reason": reason, "summary": f"{first_sentence}.", "source": "rules"}


def _claude(contact: dict) -> dict:
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=300,
        messages=[{
            "role": "user",
            "content": PROMPT.format(
                name=contact.get("name", ""),
                company=contact.get("company", ""),
                notes=contact.get("notes") or "None",
                categories=", ".join(LEAD_CATEGORIES),
            ),
        }],
    )
    text = message.content[0].text
    data = json.loads(text[text.find("{"): text.rfind("}") + 1])
    if data.get("category") not in LEAD_CATEGORIES:
        data["category"] = "Warm"
    data["source"] = "claude"
    return data


def analyze_contact(contact: dict) -> dict:
    """Return {category, reason, summary, source} for one contact."""
    if ANTHROPIC_API_KEY:
        try:
            return _claude(contact)
        except Exception as exc:  # network error, bad JSON, etc.
            result = _rules_based(contact)
            result["reason"] += f" (Claude unavailable: {type(exc).__name__})"
            return result
    return _rules_based(contact)
