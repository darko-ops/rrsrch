"""The evaluation harness (docs/SPEC-v2.md §27, Milestone 7).

Does shared, verified knowledge make agents measurably more useful? The
harness answers that by running the same tasks under three conditions with
matched budgets and scoring every answer against ground truth no agent sees:

  A  isolated       each agent researches the corpus alone
  B  shared         agents also read and add to a shared repository, whose
                    policy checks still apply but which needs no review
  C  collaborative  B, plus challenges, reviews and discussion; a change
                    needs an independent approval from another agent

It runs agents through the real API (in-process) against a dedicated
evaluation database, never the ledger.
"""
