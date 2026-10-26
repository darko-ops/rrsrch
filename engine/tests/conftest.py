"""Shared fixtures: a throwaway Postgres database and a one-study corpus on disk."""
import json
import os
import uuid

import psycopg
import pytest

from rrsrch.corpus import snapshot
from rrsrch.ledger import db

ADMIN_URL = os.environ.get("RRSRCH_DATABASE_URL", db.DEFAULT_URL)


@pytest.fixture(autouse=True)
def _fresh_limits():
    """Limits the engine keeps in its process start empty for each test, as after a restart."""
    from rrsrch.knowledge import ingest, query
    ingest.ATTEMPTS.reset()
    query.NORMALIZED.clear()
    yield


@pytest.fixture
def db_url():
    """A fresh, empty database; yields its URL and drops it afterwards."""
    name = f"rrsrch_test_{uuid.uuid4().hex[:8]}"
    try:
        admin = psycopg.connect(ADMIN_URL, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("Postgres not running (docker compose up -d)")
    admin.execute(f"CREATE DATABASE {name}")
    try:
        yield ADMIN_URL.rsplit("/", 1)[0] + f"/{name}"
    finally:
        admin.execute(f"DROP DATABASE {name} WITH (FORCE)")
        admin.close()


@pytest.fixture
def conn(db_url):
    c = psycopg.connect(db_url)
    try:
        yield c
    finally:
        c.close()


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
