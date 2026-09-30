# MeDIC workplan — reliability and extraction fidelity

Sequencing for Kevin Schaper's four tracker issues (#59–#62) and the nine drafts in `issues/`.
Ordered by dependency, not by severity: several of these change what a *tier* means, so anything
that reasons about tiers waits until they settle.

All work lands on `fix/59-negation-screen-scoping`, pushed incrementally. One consequence worth
naming up front: that branch stops being a single-issue branch, so its PR grows into a
multi-issue PR. That is the chosen tradeoff, not an oversight.

---

## Phase 0 — land what is already done ✅ code complete, unpushed

The #59 fix: span-scoped ingest negation screen, contraindication screening, shared disease-name
guard, `polarity_unverified` flag. Committed as `da987c7`, 18 files, 853 tests green.

Blocked on one decision: `origin/medic2` is nine commits behind local `medic2`, so the PR diff
would show 180,762 lines instead of 699 until `medic2` is pushed.

---

## Phase 1 — a curator's rejection is being published as HIGH ✅ done

**#62 — KGX export recomputes reliability without the review store** — done, `1a5e75b`.
Changed zero rows today: `mappings/statement_review.tsv` does not exist, so the store
loads empty. The review store has never influenced a published artifact.

First because it is severe, isolated, and small. Four call sites in `export/kgx/` call
`score_reliability` without `review_status`, so a human `REJECTED` verdict is silently discarded
and the record ships as `medic_reliability: HIGH`. Every other caller in the repo passes it.

No dependencies. Does not touch the fold, so it is unaffected by Phases 2–3.

---

## Phase 2 — the tier's foundations

These two rewrite how gate outcomes combine. Everything downstream that reads a tier waits.

**#60 — nothing reaches HIGH by absence of signal, except it does** — done, `4c780f5`.
Moved 9 of 14,474 records (HIGH→LOW), all research placeholders, none in the published
subset. The grounding-confidence half was latent: all 33,653 shipped steps carry a value.
The calibration mismatch (`_assertion_gate` ≥0.5 vs `_grounding_tier` ≥0.9) is **not**
addressed — it is raised as context in #60, not in its Fix, and moving a threshold moves
real records. Decide it with #61.

`_worst([])` returns `HIGH`, the provenance gate returns `HIGH` on 9,000 of 9,000 pairs, and a
missing confidence is read as `1.0`. A record with one evidence field and nothing else scores HIGH
and enters the published soft-launch subset.

Do before #61: #61 restructures the fold, and this fixes the fold's identity element and its
missing-vs-perfect confusion. Fixing them in the other order means doing the fold twice.

**#61 — corroboration lowers the tier**

Every gate folds with `_worst` across a pair's assertions, so a pair attested by four regulators is
scored by whichever read worst — 0% of four-source pairs reach HIGH. `confidence.corroboration()`
moves the opposite way on the same record. Needs #60 settled first.

Dependency: **#47** (reliability gates reading flags no code path emits) overlaps here. Decide
whether to fold it in or keep it separate once #60 is scoped.

---

## Phase 3 — settle the decision #59 deferred

**#68 — decide whether `polarity_unverified` should affect the reliability tier**

Whether a claim whose negation check never ran should be capped below HIGH. Deliberately left open
in #59. Must come after Phase 2, because the answer depends on what the tiers mean once the fold is
fixed — there is no point choosing a cap against a scale that is about to change.

Related: **#22** (lexical entailment demoting 206 correct synonyms) is the same population seen from
the other side. Resolve together.

---

## Phase 4 — ingest span correctness

**#65 — Limitations-of-Use splitting swallows positive indication text**

`split_dailymed_section` splits on the *first* `Limitations of Use` marker. 222 of 259
limitation-bearing DailyMed labels have more than one, and 79 have positive "is indicated for" text
typed as a scope restriction. The #59 work now depends on these boundaries, so this is repairing
the foundation under code already written.

**#66 — a destructive drop fires on zero entailment**

The destructive limitation drop fires on zero entailment, which an abbreviation defeats
(aspirin/omeprazole "MI" vs "myocardial infarction"). Do after the span fix and **re-measure
first** — some of the pressure to loosen this threshold comes from bad span boundaries, and that
pressure may disappear once they are correct.

---

## Phase 5 — the expensive one, batched

Three items that each require a full LLM run across four sources. Run once, not three times.

1. **#57 — DailyMed contraindication cache is never flushed.** 2,484 LLM calls re-run every build,
   returning different answers. Until this is fixed no rebuild is reproducible. Must go first.
2. **#64** — change the extraction contract so the LLM
   returns the verbatim source substring. Closes the 12% of rows where the negation check cannot
   run, and the abbreviation case from Phase 4. Invalidates both caches by design.
3. **#67** — rebuild and re-measure. `screen_contraindications`
   has never executed against real data; its cue list is asserted by unit tests alone, across 3,312
   contraindication rows.

---

## Not in this sequence

Independent tracks with their own gating, listed so they are not lost:

| draft (unfiled, in `issues/`) | nature |
|---|---|
| `issue_faers_meddra_licence.md` | licensing decision — blocks the adverse-event product entirely |
| `issue_pvlens_meddra_licence.md` | same |
| `issue_mhra_licensed_indications.md` | new source; source + licensing decision |
| `issue_branch_history_publishes_background.md` | release hygiene; do before any public merge |

---

## Order of work

```
Phase 0  #59   ✅ landed on fix/59-negation-screen-scoping (PR #63)
Phase 1  #62   ✅ landed — changed 0 rows; the review store was never wired in
Phase 2  #60   ✅ landed — moved 9 rows, all research placeholders
         #61   ← NEXT. First one that moves real records.
Phase 3  #68   ✅ closed by measurement, no code — capping moved 2 pairs of 7,483
Phase 4  #65   ✅ landed — span boundaries follow the SPL's own elements; 203 → 9 labels
         #66   ✅ landed — limitation verdict reported, not dropped; 16 drops → 13
Phase 5  #57 → #64 → #67   ← NEXT. One LLM re-extraction run, not three.
```
