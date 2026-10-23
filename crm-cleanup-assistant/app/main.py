"""CRM Cleanup Assistant: FastAPI app.

Run locally:  uvicorn app.main:app --reload
API docs:     http://localhost:8000/docs
Dashboard:    http://localhost:8000/
"""
import csv
import html
import io
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .ai import analyze_contact
from .cleaning import find_duplicates, validate
from .config import DUPLICATE_THRESHOLD
from .db import Contact, DuplicatePair, get_session, init_db

FIELDS = ["name", "email", "company", "phone", "notes"]


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="CRM Cleanup Assistant",
    description="Finds duplicate contacts, validates data, and categorizes and summarizes leads.",
    version="1.0.0",
    lifespan=lifespan,
)


def as_dict(c: Contact) -> dict:
    return {
        "id": c.id, "name": c.name, "email": c.email, "company": c.company,
        "phone": c.phone, "notes": c.notes, "category": c.category,
        "category_reason": c.category_reason, "summary": c.summary,
        "validation_issues": [i for i in c.validation_issues.split(" | ") if i],
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/contacts/import")
async def import_contacts(file: UploadFile, replace: bool = True, db: Session = Depends(get_session)):
    """Upload a CSV with columns: name, email, company, phone, notes."""
    raw = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames or "name" not in [f.strip().lower() for f in reader.fieldnames]:
        raise HTTPException(400, "CSV needs at least a 'name' column.")
    if replace:
        db.execute(delete(DuplicatePair))
        db.execute(delete(Contact))
    count = 0
    for row in reader:
        row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
        db.add(Contact(**{f: row.get(f, "") for f in FIELDS}))
        count += 1
    db.commit()
    return {"imported": count}


@app.get("/contacts")
def list_contacts(category: str | None = None, db: Session = Depends(get_session)):
    query = select(Contact).order_by(Contact.id)
    if category:
        query = query.where(Contact.category == category)
    return [as_dict(c) for c in db.scalars(query)]


@app.post("/analyze")
def analyze(db: Session = Depends(get_session)):
    """Validate every contact, categorize and summarize it, and flag duplicates."""
    contacts = list(db.scalars(select(Contact)))
    for c in contacts:
        data = as_dict(c)
        c.validation_issues = " | ".join(validate(data))
        result = analyze_contact(data)
        c.category, c.category_reason, c.summary = result["category"], result["reason"], result["summary"]

    db.execute(delete(DuplicatePair).where(DuplicatePair.status == "pending"))
    pairs = find_duplicates([as_dict(c) for c in contacts], DUPLICATE_THRESHOLD)
    for p in pairs:
        db.add(DuplicatePair(contact_a_id=p["a"], contact_b_id=p["b"], score=p["score"], reason=p["reason"]))
    db.commit()
    return report(db)


@app.get("/duplicates")
def list_duplicates(db: Session = Depends(get_session)):
    rows = db.scalars(select(DuplicatePair).where(DuplicatePair.status == "pending").order_by(DuplicatePair.score.desc()))
    out = []
    for p in rows:
        a, b = db.get(Contact, p.contact_a_id), db.get(Contact, p.contact_b_id)
        out.append({"id": p.id, "score": p.score, "reason": p.reason, "contact_a": as_dict(a), "contact_b": as_dict(b)})
    return out


@app.post("/duplicates/{pair_id}/merge")
def merge_duplicate(pair_id: int, keep: str = "a", db: Session = Depends(get_session)):
    """Merge a duplicate pair. keep='a' or 'b' chooses the record to keep; the
    other one's missing fields and notes are folded in, then it is deleted."""
    pair = db.get(DuplicatePair, pair_id)
    if not pair or pair.status != "pending":
        raise HTTPException(404, "No pending duplicate with that id.")
    keep_id, drop_id = (pair.contact_a_id, pair.contact_b_id) if keep == "a" else (pair.contact_b_id, pair.contact_a_id)
    keeper, other = db.get(Contact, keep_id), db.get(Contact, drop_id)
    for f in ["email", "company", "phone"]:
        if not getattr(keeper, f) and getattr(other, f):
            setattr(keeper, f, getattr(other, f))
    if other.notes:
        keeper.notes = f"{keeper.notes} {other.notes}".strip()
    db.execute(delete(DuplicatePair).where(
        (DuplicatePair.contact_a_id == drop_id) | (DuplicatePair.contact_b_id == drop_id)))
    db.delete(other)
    db.commit()
    return {"kept": as_dict(keeper), "removed_id": drop_id}


@app.post("/duplicates/{pair_id}/dismiss")
def dismiss_duplicate(pair_id: int, db: Session = Depends(get_session)):
    pair = db.get(DuplicatePair, pair_id)
    if not pair:
        raise HTTPException(404, "No duplicate with that id.")
    pair.status = "dismissed"
    db.commit()
    return {"dismissed": pair_id}


@app.get("/report")
def report(db: Session = Depends(get_session)):
    contacts = list(db.scalars(select(Contact)))
    by_category: dict[str, int] = {}
    for c in contacts:
        by_category[c.category or "Not analyzed"] = by_category.get(c.category or "Not analyzed", 0) + 1
    pending = db.scalars(select(DuplicatePair).where(DuplicatePair.status == "pending")).all()
    return {
        "contacts": len(contacts),
        "by_category": by_category,
        "contacts_with_issues": sum(1 for c in contacts if c.validation_issues),
        "duplicate_pairs": len(pending),
    }


@app.get("/", response_class=HTMLResponse)
def dashboard(db: Session = Depends(get_session)):
    """A simple read-only page for demos and screenshots."""
    e = html.escape
    stats = report(db)
    rows = "".join(
        f"<tr><td>{e(c['name'])}</td><td>{e(c['company'])}</td>"
        f"<td><span class='tag'>{e(c['category'] or '-')}</span></td>"
        f"<td>{e(c['summary'] or '')}</td><td class='warn'>{e(', '.join(c['validation_issues']))}</td></tr>"
        for c in list_contacts(None, db)
    )
    dups = "".join(
        f"<tr><td>{e(d['contact_a']['name'])} &harr; {e(d['contact_b']['name'])}</td>"
        f"<td>{d['score']:.0f}</td><td>{e(d['reason'])}</td></tr>"
        for d in list_duplicates(db)
    ) or "<tr><td colspan=3>None pending</td></tr>"
    cats = " &middot; ".join(f"{e(k)}: {v}" for k, v in stats["by_category"].items())
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>CRM Cleanup Assistant</title>
<style>
body{{font-family:system-ui,sans-serif;margin:24px;color:#1b1f24;background:#f6f7f9}}
h1{{margin:0 0 4px}} .sub{{color:#5b6470;margin-bottom:20px}}
.cards{{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:20px}}
.card{{background:#fff;border-radius:10px;padding:14px 18px;box-shadow:0 1px 3px #0001;min-width:140px}}
.card b{{display:block;font-size:26px}} table{{width:100%;border-collapse:collapse;background:#fff;
border-radius:10px;overflow:hidden;box-shadow:0 1px 3px #0001;margin-bottom:24px}}
th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid #eceef1;font-size:14px;vertical-align:top}}
th{{background:#1f4e79;color:#fff}} .tag{{background:#e8f0f8;color:#1f4e79;padding:2px 8px;border-radius:10px}}
.warn{{color:#b3261e}}
</style></head><body>
<h1>CRM Cleanup Assistant</h1><div class="sub">{cats}</div>
<div class="cards"><div class="card"><b>{stats['contacts']}</b>contacts</div>
<div class="card"><b>{stats['duplicate_pairs']}</b>likely duplicates</div>
<div class="card"><b>{stats['contacts_with_issues']}</b>with data issues</div></div>
<h2>Likely duplicates</h2><table><tr><th>Contacts</th><th>Score</th><th>Why</th></tr>{dups}</table>
<h2>Contacts</h2><table><tr><th>Name</th><th>Company</th><th>Category</th><th>Summary</th><th>Issues</th></tr>{rows}</table>
<p class="sub">API docs at <a href="/docs">/docs</a></p></body></html>"""
