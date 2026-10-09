# Where medic2 regressed against v1, and how to compensate

Comparison of the shipped v1.0.1 release (`matrix_indication_list.xlsx`, 10,223 rows) against
the current build (`medic2` + `fix/59-negation-screen-scoping`, `products/indication_list.yaml`,
8,085 pairs).

## Headline

**Only 22.5% of v1's indications survive.**

| | pairs |
|---|---:|
| v1 indications (drug+disease both present) | 10,085 |
| new indications | 8,085 |
| **retained** | **2,267 (22.5% of v1)** |
| lost | 7,818 (77.5%) |
| gained | 5,818 |

This is not "a more conservative subset". It is a near-total replacement of the pair set. The
loss is roughly uniform across regulators — FDA 76.9%, EMA 76.4%, PMDA 79.6% — which rules out
any single source's ingest being at fault.

## The losses decompose into three mechanisms, not one

| mechanism | pairs | nature |
|---|---:|---|
| drug absent from the new build | 4,444 | mostly structural (below) |
| disease absent from the new build | 1,716 | namespace + normalization |
| both endpoints present, pair is not | 1,658 | genuine extraction/coverage loss |

### 1. Namespace exclusion — 3,203 pairs, 0% retention

v1's `final normalized drug id` was whatever its cascade resolved. medic2 grounds drugs to
**CHEBI**. Every non-CHEBI namespace retains **nothing at all**:

| drug namespace | v1 pairs | retained |
|---|---:|---:|
| CHEBI | 7,020 | 2,327 (33.1%) |
| UNII | 1,421 | **0 (0.0%)** |
| PUBCHEM.COMPOUND | 710 | **0** |
| RXCUI | 611 | **0** |
| DRUGBANK | 177 | **0** |
| UMLS | 173 | **0** |
| MESH | 55 | **0** |
| CHEMBL.COMPOUND | 45 | **0** |

31.3% of v1's indications are **structurally unrepresentable** in the new schema, independent
of extraction quality. Nothing in the extraction pipeline can recover them.

**This eliminates the biologics.** Monoclonal antibodies have no CHEBI entries, so they ground
to UNII or not at all: Pembrolizumab (35 pairs), Bevacizumab (24), Rituximab (23) — all gone.
A drug–disease resource for repurposing research that cannot express pembrolizumab's
indications has a hole where modern oncology should be.

The disease side has the same shape, smaller: NCIT (143 pairs), EFO (104), DOID (13) all retain
0%; UMLS retains 12.8%, HP 17.2%, MONDO 25.9%.

### 2. Coverage ceiling — CHEBI-to-CHEBI loss

Even among drugs both builds *can* express, retention is 33.1%: 7,020 v1 CHEBI pairs, 2,327
kept. The binding constraint is the acquired SPL corpus — **1,976 labels** in
`data/raw/dailymed/`. US indications cannot exceed what those labels state, and #16 already
records that DailyMed covers only ~34% of Orange Book drugs.

Concrete casualties with both endpoints still present: ciprofloxacin loses acute cystitis,
acute pyelonephritis, gonorrhea, corneal ulcer, bacterial conjunctivitis, UTI and skin
infection — all uncontroversial FDA indications.

### 3. Legitimate losses

Some loss is v1's precision problem going away. `Croscarmellose` — a tablet disintegrant, not a
drug — carried 42 indication pairs in v1. Removing it is correct. The no-legacy-fallback
decision (SPEC §3.1) was sound; what was never done is quantify its cost.

## What our recent work did and did not do

#59, #60, #61, #62, #64, #65, #66, #68 improved **polarity and reliability correctness on
records that exist**. Measured: unlocatable 12.1% → 2.6%, 2,213 rows rescued, and
`negated_inversion` firing 15 times where the previous build detected 0.

Kevin Schaper's independent comparison agrees on both halves: *"negated indications nearly
gone"*, and *"precision remained unchanged overall"*. Those are consistent. We fixed the
negation machinery; we did not touch the coverage collapse, which is older and lives in
medic2's grounding architecture rather than its extraction.

His finding that ~4.3k DAKP pairs MEDIC lacks "use non-MONDO disease terms" is the same
namespace effect measured from the outside.

## How to compensate, in order of pairs recovered

1. **Admit non-CHEBI drug identifiers as terminal, not as grounding failures.** Biologics need
   UNII (or CHEMBL) to be a legitimate endpoint. Purple Book is already ingested — 406 artifact
   links — so the approvals exist and only the indication attachment is blocked. Addresses the
   3,203-pair structural exclusion; the largest single recovery available.
2. **Admit non-MONDO disease identifiers where MONDO has no term.** #13 covers this via Stage-2
   normalization, but NCIT/EFO/DOID retaining 0% shows it is not reaching them. Independently
   corroborated by Kevin's ~4.3k figure.
3. **Expand the SPL corpus.** 1,976 labels is the hard ceiling on US indications (#16).
4. **Review the 1,658 true pair losses** where both endpoints survive. Ciprofloxacin is the
   test case: if its SPL is present and its indications still vanished, there is an extraction
   bug to find rather than a coverage gap.
5. **Do not restore v1's matrix fallback.** It carried excipients. The architecture decision was
   right.

## What should change about how this gets judged

The regression was invisible because the only v1-vs-v2 diff in the repo
(`exports/diff_report.md`, 25 March) compares **the drug list and per-source exports only** —
never the indication list — and reports PASS against a ">=50% content overlap" target. An
indication-level diff with a retention floor, run in CI, would have caught this months ago.

Every process metric we tracked was green while 77.5% of the indications went missing.
