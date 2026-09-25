# Products

MeDIC produces the following data products from its merged knowledge base.

## Drug List (`products/drug_list.yaml`)

Unified drug list with approval status across jurisdictions, chemical identifiers, ATC codes, and drug classification flags.

## Disease List (`products/disease_list.yaml`)

Curated list of diseases with Mondo identifiers, filter flags, and cross-references.

## Indication List (`products/indication_list.yaml`)

Drug-disease indication associations (approved, investigational, and off-label) with multi-source evidence and hyperrelations.

## Contraindication List (`products/contraindication_list.yaml`)

Drug-disease contraindication associations.

## Research List

Drug-disease associations from research and repurposing sources (EveryCure, CURE-ID, clinical trials).

## Adverse Event List — deferred, not built in v2.0.0

**Not built or shipped in v2.0.0.** Both sources carry MedDRA term text, whose redistribution is restricted under the ICH/MSSO subscription licence, and it has never been established whether they can be ingested at all — see the open issues. The schema and ingesters remain in the tree, dormant.

### Design as it stands

Drug-adverse event associations from label mining and post-market reports.

Disease-centric aggregation report providing a rapid overview of drugs associated with each Mondo disease term.

## Exports

- `exports/medic_drug_mappings.sssom.tsv` - SSSOM drug identifier mappings
- `exports/drug_list_flexible.csv` - Legacy format drug list
- `exports/drug_list_stringent.csv` - Legacy format stringent drug list
- KGX biolink-compliant nodes and edges
