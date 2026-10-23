import os
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_crm.db")
os.environ["ANTHROPIC_API_KEY"] = ""  # tests use the offline rules

from fastapi.testclient import TestClient  # noqa: E402

from app.cleaning import duplicate_score, validate  # noqa: E402
from app.main import app  # noqa: E402

SAMPLE = Path(__file__).parent.parent / "sample_data" / "contacts.csv"


def test_validation_flags_bad_data():
    issues = validate({"name": "Tom", "email": "tom@gmail", "phone": "555-12"})
    assert any("Invalid email" in i for i in issues)
    assert any("Phone" in i for i in issues)
    assert validate({"name": "A", "email": "a@b.com", "phone": "555-201-3344"}) == []


def test_duplicate_scoring():
    a = {"name": "Sarah Chen", "email": "sarah.chen@brightpath.io", "company": "BrightPath Analytics", "phone": "555-201-3344"}
    b = {"name": "Sara Chen", "email": "schen@brightpath.io", "company": "Brightpath Analytics Inc", "phone": "(555) 201-3344"}
    c = {"name": "David Kim", "email": "dkim@quantaledger.com", "company": "QuantaLedger", "phone": "555-330-7788"}
    assert duplicate_score(a, b)[0] >= 85
    assert duplicate_score(a, c)[0] < 50


def test_full_flow():
    with TestClient(app) as client:
        with SAMPLE.open("rb") as f:
            r = client.post("/contacts/import", files={"file": ("contacts.csv", f, "text/csv")})
        assert r.json() == {"imported": 10}

        stats = client.post("/analyze").json()
        assert stats["contacts"] == 10
        assert stats["duplicate_pairs"] == 3  # Sarah/Sara, Jessica/Jess, two Marcus Webbs
        assert stats["contacts_with_issues"] >= 2

        dups = client.get("/duplicates").json()
        merged = client.post(f"/duplicates/{dups[0]['id']}/merge").json()
        assert merged["removed_id"]
        assert client.get("/report").json()["contacts"] == 9

        hot = client.get("/contacts", params={"category": "Hot"}).json()
        assert {c["name"] for c in hot} >= {"Jessica Alvarez"}

        assert client.get("/").status_code == 200

    Path("test_crm.db").unlink(missing_ok=True)
