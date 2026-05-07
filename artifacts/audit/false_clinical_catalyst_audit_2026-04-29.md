# False Clinical Catalyst Audit — 2026-04-29

Snapshot: `data/snapshots/2026-04-29/rankings.csv`  
Trial cache: `production_data/trial_records.json`  
Read-only. No model changes.

## Summary

- In-window catalysts (all sources): **104**
- CT.gov candidates audited: **85**
  - High-confidence FALSE: **15**
  - Ambiguous (manual review): **1**
  - Likely valid: **69**

## KALV seed check

### KALV (rank 46) — CT_PRIMARY_COMPLETION 2026-06-30 (build_window)

- tier_any/dev: `A/A`  | phase: `3.0`  | stage: `phase_3`  | days: `62`  | source: `CTGOV_CALENDAR`
  - `NCT05505916` [PHASE3/ACTIVE_NOT_RECRUITING/INTERVENTIONAL] pri_comp=2026-06-30 → **false** (title:ole_or_long_term_extension)  
    _An Open-label Extension Trial to Evaluate the Long-term Safety of KVD900 (Sebetralstat) for On-Demand Treatment of Angio_
  - `NCT05511922` [PHASE3/ACTIVE_NOT_RECRUITING/INTERVENTIONAL] pri_comp=2026-06-30 → **false** (title:pk_subtrial)  
    _PK Subtrial in Adolescent Patients With HAE Type I or II Participating in the KVD900-302 Trial_
- **why_flagged**: title:ole_or_long_term_extension, title:pk_subtrial

  ⇒ aggregate verdict: **false**

## High-confidence false catalysts

### JAZZ (rank 33) — CT_PRIMARY_COMPLETION 2026-05-31 (build_window)

- tier_any/dev: `C/C`  | phase: `3.0`  | stage: `approved`  | days: `32`  | source: `CTGOV_CALENDAR`
  - `NCT05850676` [N/A/RECRUITING/OBSERVATIONAL] pri_comp=2026-05-30 → **false** (study_type=OBSERVATIONAL)  
    _Disentangling the Role of Depression in Hypersomnia_
  - `NCT06217536` [PHASE1/WITHDRAWN/INTERVENTIONAL] pri_comp=2026-05-31 → **false** (status=WITHDRAWN)  
    _Neoadjuvant Lurbinectedin and Preoperative Radiation for Treating Soft Tissue Sarcomas_
- **why_flagged**: status=WITHDRAWN, study_type=OBSERVATIONAL

### FATE (rank 42) — CT_PRIMARY_COMPLETION 2026-05-01 (binary_now)

- tier_any/dev: `B/B`  | phase: `2.0`  | stage: `phase_2`  | days: `2`  | source: `CTGOV_CALENDAR`
  - `NCT05934097` [PHASE1/WITHDRAWN/INTERVENTIONAL] pri_comp=2026-05-01 → **false** (status=WITHDRAWN)  
    _FT596 in Combination With R-CHOP in Subjects With B-Cell Lymphoma_
- **why_flagged**: status=WITHDRAWN

### KALV (rank 46) — CT_PRIMARY_COMPLETION 2026-06-30 (build_window)

- tier_any/dev: `A/A`  | phase: `3.0`  | stage: `phase_3`  | days: `62`  | source: `CTGOV_CALENDAR`
  - `NCT05505916` [PHASE3/ACTIVE_NOT_RECRUITING/INTERVENTIONAL] pri_comp=2026-06-30 → **false** (title:ole_or_long_term_extension)  
    _An Open-label Extension Trial to Evaluate the Long-term Safety of KVD900 (Sebetralstat) for On-Demand Treatment of Angio_
  - `NCT05511922` [PHASE3/ACTIVE_NOT_RECRUITING/INTERVENTIONAL] pri_comp=2026-06-30 → **false** (title:pk_subtrial)  
    _PK Subtrial in Adolescent Patients With HAE Type I or II Participating in the KVD900-302 Trial_
- **why_flagged**: title:ole_or_long_term_extension, title:pk_subtrial

### PTCT (rank 55) — CT_PRIMARY_COMPLETION 2026-06-30 (build_window)

- tier_any/dev: `A/A`  | phase: `3.0`  | stage: `phase_3`  | days: `62`  | source: `CTGOV_CALENDAR`
  - `NCT05166161` [PHASE3/ACTIVE_NOT_RECRUITING/INTERVENTIONAL] pri_comp=2026-06-30 → **false** (title:ole_or_long_term_extension)  
    _A Long-Term Safety Study of PTC923 in Participants With Phenylketonuria_
- **why_flagged**: title:ole_or_long_term_extension

### BEAM (rank 62) — CT_STUDY_COMPLETION 2026-05-29 (binary_now)

- tier_any/dev: `C/C`  | phase: `1.0`  | stage: `phase_1`  | days: `30`  | source: `CTGOV_CALENDAR`
  - `NCT07304791` [PHASE1/RECRUITING/INTERVENTIONAL] pri_comp=2026-01-29 → **false** (title:healthy_volunteers_or_food_effect, phase1_pk_healthy)  
    _This is a Phase 1, Randomized, Single-blind, Placebo-controlled Study to Assess the Safety, Pharmacokinetics (PK), and P_
- **why_flagged**: phase1_pk_healthy, title:healthy_volunteers_or_food_effect

### APLS (rank 83) — CT_STUDY_COMPLETION 2026-07-01 (build_window)

- tier_any/dev: `B/B`  | phase: `3.0`  | stage: `phase_3`  | days: `63`  | source: `CTGOV_CALENDAR`
  - `NCT03531255` [PHASE3/ACTIVE_NOT_RECRUITING/INTERVENTIONAL] pri_comp=2025-11-29 → **false** (title:ole_or_long_term_extension)  
    _Pegcetacoplan Long Term Safety and Efficacy Extension Study_
- **why_flagged**: title:ole_or_long_term_extension

### SION (rank 93) — CT_PRIMARY_COMPLETION 2026-06-01 (build_window)

- tier_any/dev: `A/A`  | phase: `2.0`  | stage: `phase_2`  | days: `33`  | source: `CTGOV_CALENDAR`
  - `NCT07035990` [PHASE1/RECRUITING/INTERVENTIONAL] pri_comp=2026-06-01 → **false** (phase1_pk_healthy)  
    _Safety, Tolerability, and Pharmacokinetics of Multiple Dose Combinations of SION-451 and Complementary Modulators SION-2_
- **why_flagged**: phase1_pk_healthy

### PTGX (rank 109) — DATA_READOUT 2026-06-15 (build_window)

- tier_any/dev: `A/A`  | phase: `3.0`  | stage: `phase_3`  | days: `47`  | source: `CTGOV_CALENDAR`
  - `NCT07153146` [PHASE1/RECRUITING/INTERVENTIONAL] pri_comp=2026-06-15 → **false** (title:healthy_volunteers_or_food_effect, phase1_pk_healthy)  
    _Safety, Tolerability, Pharmacokinetics, and Pharmacodynamics of PN-881 in Healthy Subjects._
- **why_flagged**: phase1_pk_healthy, title:healthy_volunteers_or_food_effect

### CLYM (rank 117) — DATA_READOUT 2026-06-01 (build_window)

- tier_any/dev: `A/A`  | phase: `2.0`  | stage: `phase_2`  | days: `33`  | source: `CTGOV_CALENDAR`
  - `NCT07090655` [EARLY_PHASE1/ACTIVE_NOT_RECRUITING/INTERVENTIONAL] pri_comp=2026-04-01 → **false** (title:healthy_volunteers_or_food_effect)  
    _A Phase 1 Study of Budoprutug (TNT119) Subcutaneous and Intravenous Injections in Normal Healthy Volunteers_
- **why_flagged**: title:healthy_volunteers_or_food_effect

### GHRS (rank 121) — CT_PRIMARY_COMPLETION 2026-05-01 (binary_now)

- tier_any/dev: `C/C`  | phase: `2.0`  | stage: `phase_2`  | days: `2`  | source: `CTGOV_CALENDAR`
  - `NCT07540494` [PHASE1/NOT_YET_RECRUITING/INTERVENTIONAL] pri_comp=2026-05-01 → **false** (title:healthy_volunteers_or_food_effect, phase1_pk_healthy)  
    _Pharmacokinetics and Safety of GH001 Delivered Via a GH001 Aerosol Delivery System in Healthy Subjects_
- **why_flagged**: phase1_pk_healthy, title:healthy_volunteers_or_food_effect

### ELDN (rank 166) — CT_PRIMARY_COMPLETION 2026-06-01 (build_window)

- tier_any/dev: `A/A`  | phase: `2.0`  | stage: `phase_2`  | days: `33`  | source: `CTGOV_CALENDAR`
  - `NCT04711226` [PHASE2/WITHDRAWN/INTERVENTIONAL] pri_comp=2024-06-01 → **false** (status=WITHDRAWN)  
    _Safety, Tolerability and Efficacy of Immunomodulation With AT-1501 in Islet Cell Transplantation_
- **why_flagged**: status=WITHDRAWN

### NVAX (rank 172) — DATA_READOUT 2026-05-17 (binary_now)

- tier_any/dev: `C/C`  | phase: `3.0`  | stage: `approved`  | days: `18`  | source: `CTGOV_CALENDAR`
  - `NCT06482359` [PHASE2/WITHDRAWN/INTERVENTIONAL] pri_comp=2025-11-16 → **false** (status=WITHDRAWN)  
    _Lot Consistency Study of COVID-19 and Influenza Combination Vaccine_
- **why_flagged**: status=WITHDRAWN

### IBRX (rank 186) — DATA_READOUT 2026-04-30 (binary_now)

- tier_any/dev: `A/A`  | phase: `3.0`  | stage: `phase_3`  | days: `1`  | source: `CTGOV_CALENDAR`
  - `NCT05007769` [PHASE2/WITHDRAWN/INTERVENTIONAL] pri_comp=2024-04-30 → **false** (status=WITHDRAWN)  
    _Ramucirumab, Atezolizumab and N-803 After Progression on Any Immune Checkpoint Blocker in NSCLC_
- **why_flagged**: status=WITHDRAWN

### NUVB (rank -) — CT_PRIMARY_COMPLETION 2026-07-01 (build_window)

- tier_any/dev: `D/D`  | phase: `3.0`  | stage: `phase_3`  | days: `63`  | source: `CTGOV_CALENDAR`
  - `NCT05191017` [PHASE1/WITHDRAWN/INTERVENTIONAL] pri_comp=2025-01-01 → **false** (status=WITHDRAWN)  
    _Study of NUV-422 in Combination With Enzalutamide in Patients With mCRPC_
- **why_flagged**: status=WITHDRAWN

### BMEA (rank -) — DATA_READOUT 2026-05-01 (binary_now)

- tier_any/dev: `D/D`  | phase: `2.0`  | stage: `phase_2`  | days: `2`  | source: `CTGOV_CALENDAR`
  - `NCT07223216` [PHASE1/ACTIVE_NOT_RECRUITING/INTERVENTIONAL] pri_comp=2026-05-01 → **false** (phase1_pk_healthy)  
    _Study of BMF-650 in Otherwise Healthy Overweight or Obese Adult Participants_
- **why_flagged**: phase1_pk_healthy


## Ambiguous catalysts (manual review)

### DNA (rank -) — DATA_READOUT 2026-04-30 (binary_now)

- tier_any/dev: `D/D`  | phase: `3.0`  | stage: `approved`  | days: `1`  | source: `CTGOV_CALENDAR`
  - `NCT03729518` [NA/ACTIVE_NOT_RECRUITING/INTERVENTIONAL] pri_comp=2026-05-01 → **ambiguous** (phase=N/A interventional)  
    _TORS De-Intensification Protocol Version 2.0: Dose and Volume Reduction in the Neck_
  - `NCT06670807` [NA/NOT_YET_RECRUITING/INTERVENTIONAL] pri_comp=2026-05-01 → **ambiguous** (phase=N/A interventional)  
    _Effect of a Probiotic Formula in Mild Cognitive Impairement_
  - `NCT06899061` [PHASE1/ACTIVE_NOT_RECRUITING/INTERVENTIONAL] pri_comp=2026-02-03 → **false** (title:healthy_volunteers_or_food_effect)  
    _Modular Clinical Pharmacology Study to Evaluate the Drug-drug Interaction Potential and Relative Bioavailability of Saru_
  - `NCT04904835` [N/A/RECRUITING/OBSERVATIONAL] pri_comp=2025-12-01 → **false** (study_type=OBSERVATIONAL)  
    _Access HBV Assays - European Union (EU) Clinical Trial Protocol -_
  - `NCT01084785` [N/A/RECRUITING/OBSERVATIONAL] pri_comp=2026-05-01 → **false** (study_type=OBSERVATIONAL)  
    _Biobank Carcinoma: Storing Blood and Protein of Patients With Cancer_
  - `NCT06624618` [N/A/RECRUITING/OBSERVATIONAL] pri_comp=2026-05-01 → **false** (study_type=OBSERVATIONAL)  
    _Rapid Molecular Diagnosis of Sepsis in the Intensive Care Unit_
- **why_flagged**: phase=N/A interventional, study_type=OBSERVATIONAL, title:healthy_volunteers_or_food_effect


## Likely valid catalysts (sanity)

_69 entries — see JSON for full list. Top 20 by rank shown:_

- `COGT` rank 1 — CT_PRIMARY_COMPLETION 2026-06-01 (NCT06208748)
- `NRIX` rank 6 — DATA_READOUT 2026-05-01 (NCT04830137)
- `ORIC` rank 8 — CT_PRIMARY_COMPLETION 2026-05-01 (NCT06816992)
- `RCUS` rank 14 — CT_PRIMARY_COMPLETION 2026-04-30 (NCT03821246,NCT04791839)
- `TNGX` rank 18 — CT_PRIMARY_COMPLETION 2026-05-01 (NCT05732831)
- `RVMD` rank 20 — CT_PRIMARY_COMPLETION 2026-04-30 (NCT06040541)
- `EWTX` rank 24 — CT_PRIMARY_COMPLETION 2026-05-01 (NCT07324616,NCT07177066,NCT05257473)
- `NBIX` rank 25 — DATA_READOUT 2026-06-01 (NCT05206513)
- `ALKS` rank 27 — CT_PRIMARY_COMPLETION 2026-06-01 (NCT06843590,NCT05495984)
- `BCRX` rank 28 — CT_PRIMARY_COMPLETION 2026-05-01 (NCT07228559)
- `UTHR` rank 35 — CT_STUDY_COMPLETION 2026-05-31 (NCT04905693,NCT06335407)
- `CGON` rank 37 — CT_PRIMARY_COMPLETION 2026-06-01 (NCT06111235)
- `MBX` rank 39 — CT_PRIMARY_COMPLETION 2026-05-30 (NCT07142707)
- `GH` rank 41 — CT_PRIMARY_COMPLETION 2026-04-30 (NCT07005648,NCT06102291,NCT03274492,NCT06309966,NCT05309551,NCT06685978,NCT00863460,NCT07540494)
- `MLTX` rank 45 — CT_STUDY_COMPLETION 2026-06-17 (NCT06411899,NCT06411379)
- `IDYA` rank 48 — CT_PRIMARY_COMPLETION 2026-06-22 (NCT06710847)
- `CGEM` rank 58 — CT_STUDY_COMPLETION 2026-06-01 (NCT05117476)
- `ANIP` rank 71 — CT_PRIMARY_COMPLETION 2026-07-01 (NCT05486468)
- `ELVN` rank 75 — CT_PRIMARY_COMPLETION 2026-07-01 (NCT05650879)
- `CATX` rank 81 — CT_PRIMARY_COMPLETION 2026-04-30 (NCT05111509)

## Recommended next implementation spec

If high-confidence-false count is materially non-zero (>5), draft a `spec_NNN_catalyst_classifier.md` proposing a CT.gov catalyst-quality gate that (1) filters trials by study_type + title regex before assigning catalyst credit, (2) downgrades `catalyst_bucket` from `binary_now` / `build_window` to `registry_only` for OLE/PK/expanded-access matches, and (3) preserves the original CT.gov date as a context field rather than a tier driver. Alpha-affecting → Checklist v2 required before promotion.
