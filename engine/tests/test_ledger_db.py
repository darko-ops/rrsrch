"""Ledger load against a real Postgres (the docker-compose one), in a throwaway database."""
import json

import pytest

from rrsrch.corpus import snapshot
from rrsrch.ledger import db

pytestmark = pytest.mark.db


def test_load_is_repeatable_and_links_trials(conn, corpus_dir):
    assert db.migrate(conn) == ["0001_ledger.sql", "0002_reader.sql", "0003_writer.sql",
                                "0004_trials.sql", "0005_skeptic.sql", "0006_knowledge.sql",
                                "0007_identity.sql", "0008_trust.sql", "0009_knowledge_api.sql",
                                "0010_collaboration.sql",
                                "0011_answer_jobs.sql",
                                "0012_claim_reviews.sql",
                                "0013_answer_limits.sql",
                                "0014_feedback.sql", "0015_research_network.sql",
                                    "0016_agent_network.sql", "0017_post_moderation.sql",
                                    "0018_site_people.sql", "0019_needs_work.sql", "0020_inbox.sql", "0021_self_serve_orgs.sql",
                                    "0022_discovery.sql", "0023_git_ref_evidence.sql",
                                    "0024_embargo_disclosure_questions.sql", "0025_bounties.sql", "0026_one_review_record.sql", "0027_questions_not_tasks.sql", "0028_findings_and_threads.sql", "0029_drop_retired.sql", "0030_agent_sources.sql", "0031_source_uploads.sql", "0032_humanity_confidence.sql", "0033_knowledge_health.sql", "0034_agent_public_repos.sql", "0035_sliding_keys.sql", "0036_polls.sql", "0037_feedback_marks.sql", "0038_checkin_cursor.sql", "0039_agent_protocol.sql", "0040_topic_tree.sql", "0041_retire_collections.sql", "0042_gauges.sql", "0043_prescience.sql", "0044_proposed_gauges.sql", "0045_perspective_moderation.sql", "0046_sparks_for_activity.sql", "0047_follow_agents.sql", "0048_x_posts.sql", "0049_commons_claims.sql", "0050_economy.sql", "0051_spark_priority.sql", "0052_spark_transfers.sql", "0053_post_drafts.sql", "0054_post_headlines.sql", "0055_benchmark_snapshots.sql", "0056_handle_changes.sql", "0057_grokbot_model.sql", "0058_grokbot_label.sql", "0059_signup_network.sql", "0060_post_loops.sql"]
    assert db.migrate(conn) == []
    rep = db.load_corpus(conn, corpus_dir)
    assert (rep.sources, rep.trials, rep.links) == (1, 1, 1)
    db.load_corpus(conn, corpus_dir)
    assert conn.execute("SELECT count(*) FROM documents").fetchone()[0] == 2   # title + abstract
    assert conn.execute("SELECT method FROM trial_links").fetchone()[0] == "nct_in_abstract"
    assert conn.execute("SELECT has_full_text FROM sources").fetchone()[0] is False


def test_text_changed_under_a_claim_is_refused(conn, corpus_dir):
    db.migrate(conn)
    db.load_corpus(conn, corpus_dir)
    doc_id, sha = conn.execute("SELECT id, sha256 FROM documents WHERE part = 'abstract'").fetchone()
    conn.execute("INSERT INTO claims (document_id, doc_sha256, span_start, span_end, text, extractor, "
                 "repository_id, type, state, agent_id) VALUES (%s, %s, 0, 7, 'Methods', 'test', "
                 "(SELECT id FROM repositories WHERE slug = 'rrsrch/msc-knee-oa'), 'empirical', 'structurally_valid', (SELECT id FROM agents))",
                 (doc_id, sha))
    conn.commit()
    rec_path = snapshot.record_dir("MED:1") / "record.json"
    rec = json.loads(rec_path.read_text())
    rec["abstractText"] = "<h4>Methods</h4>Corrected: n=38."
    rec_path.write_bytes(snapshot.stable_record_bytes(rec))
    with pytest.raises(db.ChangedUnderClaims):
        db.load_corpus(conn, corpus_dir)
