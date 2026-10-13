"""Shared fixtures: a throwaway Postgres database and a one-study corpus on disk."""
import json
import os
import uuid

import psycopg
import pytest

from rrsrch.corpus import snapshot
from rrsrch.ledger import db

ADMIN_URL = os.environ.get("RRSRCH_DATABASE_URL", db.DEFAULT_URL)


@pytest.fixture
def conn():
    name = f"rrsrch_test_{uuid.uuid4().hex[:8]}"
    try:
        admin = psycopg.connect(ADMIN_URL, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("Postgres not running (docker compose up -d)")
    admin.execute(f"CREATE DATABASE {name}")
    c = psycopg.connect(ADMIN_URL.rsplit("/", 1)[0] + f"/{name}")
    try:
        yield c
    finally:
        c.close()
        admin.execute(f"DROP DATABASE {name}")
        admin.close()


@pytest.fixture
def corpus_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rec = {"id": "1", "source": "MED", "pmid": "1", "title": "BM-MSC for knee OA",
           "pubYear": "2019", "abstractText": "<h4>Methods</h4>RCT, NCT01234567. n=40.",
           "pubTypeList": {"pubType": ["Randomized Controlled Trial"]}}
    d = snapshot.record_dir("MED:1")
    d.mkdir(parents=True)
    (d / "record.json").write_bytes(snapshot.stable_record_bytes(rec))
    t = snapshot.trial_path("NCT01234567")
    t.parent.mkdir(parents=True)
    t.write_text(json.dumps({"hasResults": False, "protocolSection": {
        "identificationModule": {"briefTitle": "MSC knee trial"},
        "statusModule": {"overallStatus": "COMPLETED", "completionDateStruct": {"date": "2018-06"}},
        "outcomesModule": {"primaryOutcomes": [{"measure": "WOMAC", "timeFrame": "12 months"}]}}}))
    return {"topic": "t",
            "answer_key": [{"pmid": "99", "pmcid": "PMC99", "title": "A meta-analysis", "year": 2025}],
            "studies": [{"id": "MED:1", "title": "BM-MSC for knee OA", "included_by": ["99"]}],
            "unresolved": []}
