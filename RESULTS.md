# Measured results

All numbers below were produced by the scripts in `tools/` on the data described; nothing is estimated.
All data is synthetic or public: accuracy is an upper bound for real factory data.

## v2: demo factory, end to end (`results/demo_factory_eval.json`)

`python tools/factory/evaluate.py --workers 2` reads the six demo sources through the real connectors from the local
API simulators (SOLIDWORKS PDM Web API, Vault, Windchill, Teamcenter, a legacy folder, Priority), runs the audit and
compares the result with what the factory builder planted (`demo/factory/factory.json`, `truth`). The factory has
472 parts, 29 assemblies and 434 ERP items; business data is synthetic, standard-part
geometry follows ISO/DIN dimensions, and 5 NIST test models are included. Time: 4.5 s reading,
40.7 s audit (2 workers, cold cache).

**Duplicate pairs** (pairs of records that are the same part): 318 true, 297 predicted,
**297 correct, 0 wrong, 21 missed: precision 100.0%, recall 93.4%**.
With a STEP file on both sides: 253 of 256 (98.8%). With a STEP file missing (names, part numbers and
specs only): 44 of 62 (71.0%).

| How the copy was made | STEP files | Found | Total | Recall |
|---|---|---:|---:|---:|
| base+copy | both STEP | 7 | 7 | 100.0% |
| base+moved | STEP missing | 0 | 3 | 0.0% |
| base+moved | both STEP | 17 | 17 | 100.0% |
| base+reexport | STEP missing | 1 | 6 | 16.7% |
| base+reexport | both STEP | 10 | 10 | 100.0% |
| base+saveas | STEP missing | 0 | 1 | 0.0% |
| base+saveas | both STEP | 11 | 11 | 100.0% |
| base+split | STEP missing | 0 | 1 | 0.0% |
| base+split | both STEP | 6 | 6 | 100.0% |
| base+unit_error | both STEP | 5 | 5 | 100.0% |
| copy+saveas | both STEP | 1 | 1 | 100.0% |
| copy+split | both STEP | 2 | 2 | 100.0% |
| library | STEP missing | 43 | 50 | 86.0% |
| library | both STEP | 186 | 186 | 100.0% |
| moved | both STEP | 1 | 1 | 100.0% |
| moved+reexport | STEP missing | 0 | 1 | 0.0% |
| moved+split | both STEP | 1 | 1 | 100.0% |
| moved+unit_error | both STEP | 1 | 1 | 100.0% |
| near | both STEP | 1 | 1 | 100.0% |
| nist | both STEP | 2 | 5 | 40.0% |
| reexport | both STEP | 1 | 1 | 100.0% |
| saveas+unit_error | both STEP | 1 | 1 | 100.0% |

Missed pairs (the first 15 of 21, as listed by the evaluation script):

- `nist_ctc_04_asme1_ap203` / `TEST PART CTC-04` (nist, both STEP): got near_identical
- `תושבת זוויתית 45x70x35 final` / `תושבת זוויתית 45x70x35` (base+reexport, STEP missing): got name_similar
- `200-9778 צינור Ø30x2 L=250` / `Tube d30x2 l=250` (moved+reexport, STEP missing): got name_similar
- `N-PUL-0437_revA` / `PULLEY D80x30` (base+reexport, STEP missing): got name_similar
- `N-SHF-0626 IDLER SHAFT D15x120` / `IDLER SHAFT D15x120` (base+reexport, STEP missing): got name_similar
- `ידית U 180 מ"מ` / `ידית U 180 מ"מ` (library, STEP missing): got name_similar
- `פרופיל אלומיניום 40x40 L=400` / `AL PROFILE 40x40 L=400` (library, STEP missing): got name_similar
- `פרופיל אלומיניום 40x40 L=1000` / `פרופיל אלומיניום 40x40 L=1000` (library, STEP missing): got not flagged
- `פלטת חיבור 100x60x8` / `פלטת חיבור` (base+saveas, STEP missing): got name_similar
- `צינור Ø30x2 L=250` / `Tube d30x2 l=250` (base+moved, STEP missing): got name_similar
- `תושבת זוויתית 60x60x40 ימני` / `BRACKET,ANGLE,60X60X40,RH` (base+moved, STEP missing): got name_similar
- `בלוק הידוק 100x40x30` / `Clamp block 100x40x30` (base+reexport, STEP missing): got name_similar
- `PROFILE,AL,40X40,L1000` / `פרופיל אלומיניום 40x40 L=1000` (library, STEP missing): got not flagged
- `PROFILE,AL,40X40,L2000` / `Al profile 40x40 l=2000` (library, STEP missing): got name_similar
- `BUSHING,PLAIN,8X12X10` / `Plain bushing 8/12x10 nylon` (base+split, STEP missing): got name_similar

**Same design, not a duplicate** (planted variants that must not be merged; outcome -> count):

| Variant -> outcome | Pairs |
|---|---:|
| legacy_only -> (not flagged) (not merged) | 4 |
| mirror -> (not flagged) (not merged) | 1 |
| mirror -> mirror (not merged) | 5 |
| near (volume change <= 10%) -> conflict (not merged) | 3 |
| near (volume change <= 10%) -> mirror (not merged) | 1 |
| near (volume change <= 10%) -> name_similar (not merged) | 11 |
| near (volume change <= 10%) -> near_identical (not merged) | 23 |
| near (volume change > 10%) -> name_similar (not merged) | 4 |
| oldrev -> (not flagged) (not merged) | 1 |
| oldrev -> conflict (not merged) | 4 |
| oldrev -> name_similar (not merged) | 4 |

**Hard negatives** (same geometry, different specification: 8.8 / 12.9 / A2, 2RS / ZZ):

| Outcome | Pairs |
|---|---:|
| not merged / (not flagged) | 3 |
| not merged / identical_attr_conflict | 15 |

**NIST models** (the same test case exported by different CAD systems vs different test cases):

| Outcome | Pairs |
|---|---:|
| different case -> (not flagged) | 40 |
| same case -> identical | 2 |
| same case -> near_identical | 3 |

**Planted data-quality and ERP issues** (`on unplanted records`: issues of the same check on records where nothing
was planted; these were not verified one by one and can be real consequences of the factory data):

| Planted | Check | Planted | Found | On unplanted records |
|---|---|---:|---:|---:|
| missing_material | `missing_material` | 7 | 7 | 0 |
| stale_mass_high | `mass_mismatch` | 2 | 2 | 1 |
| stale_mass_low | `mass_mismatch` | 9 | 8 | 1 |
| filename_pn_mismatch | `filename_pn_mismatch` | 6 | 6 | 0 |
| pn_format | `pn_format` | 4 | 4 | 0 |
| bom_state_in_work | `bom_state` | 2 | 2 | 3 |
| bom_state_obsolete | `obsolete_in_use` | 2 | 2 | 6 |
| missing_in_erp | `released_not_in_erp` | 8 | 8 | 0 |
| erp_description_differs | `erp_description_mismatch` | 8 | 8 | 0 |
| erp_material_differs | `erp_material_mismatch` | 5 | 5 | 1 |
| erp_bom_qty_differs | `erp_bom_mismatch` | 2 | 2 | 0 |
| obsolete_but_active_in_erp | `erp_status_mismatch` | 8 | 8 | 0 |
| unit_error (archive) | `unit_error` | 5 | 5 | – |

## v1 held-out test set re-run with the v2 engine

The v1 test set (below) was scored again on 2026-10-04 with the v2 engine (`results/test_metrics_v2_engine.json`).
Every metric is identical to the v1 numbers after the documented post-freeze L3b fix
(`results/test_metrics.json`): A-D 100% precision and recall, E precision 98.1% / recall 100%, F F1 0.781,
2 false positives in 235 flagged pairs.

# v1 results

## Test sets

| | Dev (tuning) | Test (held out) |
|---|---:|---:|
| base files | 250 | 500 |
| A files | 15 | 30 |
| B files | 15 | 30 |
| C files | 15 | 30 |
| D files | 15 | 30 |
| E files | 30 | 40 |
| F files | 50 | 50 |
| HN_material files | 8 | 15 |
| HN_thickness files | 8 | 15 |
| HN_mirror files | 2 | 8 |
| HN_name pairs | 12 | 25 |
| total STEP files | 408 | 748 |
| ERP rows | 318 | 621 |
| planted A-F share of files | 34.3% | 28.1% |
| ABC files screened | 750 | 1500 |
| single-body valid | 468 | 1033 |
| natural near-duplicates removed | 22 | 189 |

## Held-out test set

Thresholds were tuned on the dev set and frozen; the test set was built afterwards and scored once with the frozen code and thresholds:

| Type | GT pairs | Found | Missed | Predicted | Wrong | Precision | Recall | F1 | Target | Met |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| A | 30 | 30 | 0 | 42 | 0 | 100.0% | 100.0% | 1.000 | P>=95% and R>=95% | yes |
| B | 30 | 30 | 0 | 40 | 0 | 100.0% | 100.0% | 1.000 | P>=95% and R>=95% | yes |
| C | 30 | 29 | 1 | 40 | 0 | 100.0% | 96.7% | 0.983 | P>=95% and R>=95% | yes |
| D | 30 | 30 | 0 | 36 | 0 | 100.0% | 100.0% | 1.000 | P>=95% and R>=95% | yes |
| E | 40 | 40 | 0 | 52 | 1 | 98.1% | 100.0% | 0.990 | R>=80% at P>=90% | yes |
| F | 50 | 35 | 15 | 51 | 6 | 88.2% | 70.0% | 0.781 | F1>=0.85 | no |
| F (full pipeline) | 50 | 50 | 0 | - | - | - | 100.0% | - | info | n/a |
| False positives / flagged pairs | - | - | - | 234 | 2 | - | - | - | FP <= 2% | yes |

*GT pairs / Found / Missed*: (base, variant) pairs, used for recall. *Predicted / Wrong*: every predicted pair that involves a file of that type, used for precision = (Predicted - Wrong) / Predicted. For F, 'predicted' means a name-layer link (score >= threshold). For the false-positive row, 'Predicted' is all flagged pairs (merge candidates + near-identical alerts).

False positives on truly different parts: 2 of 234 flagged pairs = **0.85%** (target <= 2%).

| Hard negative | Pairs | Handled correctly | Outcome counts |
|---|---:|---:|---|
| HN_material | 15 | 15 (100%) | category=identical_attr_conflict: 15 |
| HN_mirror | 8 | 7 (88%) | category=identical: 1, category=mirror: 7 |
| HN_name | 25 | 25 (100%) | category=name_similar: 15, category=none: 10 |
| HN_thickness | 15 | 15 (100%) | category=name_similar: 5, category=none: 10 |

All name-layer links (any type): 277 links, 75.8% within the same ground-truth group.

Remaining errors in this run:

- Name layer (F): 15 of the F variants were not linked by name alone; 7 of them because the description matched but is shared by many part numbers (generic, discounted on purpose) and 8 because the variant's description itself scored below the threshold (unrecognised transliteration or typo, or a generic name that also scored low). 6 name links pointed to a different part with the same or nearly the same description. With geometry (full pipeline) every F variant was linked.
- positive (C): `PA-17473_STIFFENER-FLAT.stp` vs `PA-17473_STIFFENER-FLAT_old.step` - expected identical, got conflict (geometry: mirror).
- false positive (E): `PA-14079 KNOB FRONT CYLINDER D16 MODIFIED.stp` vs `PA-14080_KNOB-FRONT-CYLINDER-D16-LH.step` - expected different, got near_identical.
- false positive (flagged): `PA-14079 KNOB FRONT CYLINDER D16 MODIFIED.stp` vs `PA-14080_KNOB-FRONT-CYLINDER-D16-LH.step` - expected different, got near_identical.
- false positive (flagged): `PA-14080_KNOB-FRONT-CYLINDER-D16-LH.step` vs `PA-14078_KNOB-FRONT-CYLINDER-D16.STP` - expected different, got identical.
- hard negative (HN_mirror): `PA-14078_KNOB-FRONT-CYLINDER-D16.STP` vs `PA-14080_KNOB-FRONT-CYLINDER-D16-LH.step` - expected mirror image, not merged, got identical.
- Missed mirror images are parts whose handedness is weak: the exact-distance check used to label them finds a difference, but the skewness test has no clear sign and 4,096 surface samples cannot separate the reflection from a rotation. Copies of such a part are then merged with its mirror twin, which also explains the related false positives above.

### After one post-hoc fix

Error analysis on the test run found one algorithmic bug (not a threshold): for nearly axisymmetric parts the L3b rotation search used a 10-degree grid, so a rotated copy could fit worse than a reflection and was reported as a mirror image. The search now uses a 5-degree grid with 0.5-degree refinement. Thresholds were not changed. Re-running dev and test with the fixed code changed only these rows (precision / recall, or false positives):

| Row | Frozen run | After fix |
|---|---|---|
| C | 100.0% / 96.7% | 100.0% / 100.0% |
| False positives / flagged pairs | 2 FP of 234 | 2 FP of 235 |

### Name layer: sensitivity on the test set (post-hoc, not used for any number above)

| name_similar | name_k0 | partial factor | F precision | F recall | F1 |
|---:|---:|---:|---:|---:|---:|
| 0.85 | 3 | 0.85 | 79.0% | 70.0% | 0.742 |
| 0.85 | 6 | 0.85 | 67.7% | 72.0% | 0.698 |
| 0.85 | 10 | 0.85 | 65.3% | 74.0% | 0.694 |
| 0.9 | 3 | 0.85 | 88.2% | 70.0% | 0.781 |
| 0.9 | 6 | 0.85 | 86.8% | 72.0% | 0.787 |
| 0.9 | 10 | 0.85 | 86.8% | 72.0% | 0.787 |

## Dev set (used for tuning)

| Type | GT pairs | Found | Missed | Predicted | Wrong | Precision | Recall | F1 | Target | Met |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| A | 15 | 15 | 0 | 22 | 0 | 100.0% | 100.0% | 1.000 | P>=95% and R>=95% | yes |
| B | 15 | 14 | 1 | 18 | 0 | 100.0% | 93.3% | 0.966 | P>=95% and R>=95% | no |
| C | 15 | 15 | 0 | 20 | 0 | 100.0% | 100.0% | 1.000 | P>=95% and R>=95% | yes |
| D | 15 | 15 | 0 | 19 | 0 | 100.0% | 100.0% | 1.000 | P>=95% and R>=95% | yes |
| E | 30 | 30 | 0 | 47 | 0 | 100.0% | 100.0% | 1.000 | R>=80% at P>=90% | yes |
| F | 50 | 39 | 11 | 55 | 0 | 100.0% | 78.0% | 0.876 | F1>=0.85 | yes |
| F (full pipeline) | 50 | 50 | 0 | - | - | - | 100.0% | - | info | n/a |
| False positives / flagged pairs | - | - | - | 166 | 0 | - | - | - | FP <= 2% | yes |

*GT pairs / Found / Missed*: (base, variant) pairs, used for recall. *Predicted / Wrong*: every predicted pair that involves a file of that type, used for precision = (Predicted - Wrong) / Predicted. For F, 'predicted' means a name-layer link (score >= threshold). For the false-positive row, 'Predicted' is all flagged pairs (merge candidates + near-identical alerts).

False positives on truly different parts: 0 of 166 flagged pairs = **0.00%** (target <= 2%).

| Hard negative | Pairs | Handled correctly | Outcome counts |
|---|---:|---:|---|
| HN_material | 8 | 8 (100%) | category=identical_attr_conflict: 8 |
| HN_mirror | 2 | 2 (100%) | category=mirror: 2 |
| HN_name | 12 | 12 (100%) | category=name_similar: 4, category=none: 8 |
| HN_thickness | 8 | 8 (100%) | category=name_similar: 2, category=none: 6 |

All name-layer links (any type): 162 links, 88.9% within the same ground-truth group.

Remaining errors on dev:

- Name layer (F): 11 of the F variants were not linked by name alone; 9 of them because the description matched but is shared by many part numbers (generic, discounted on purpose) and 2 because the variant's description itself scored below the threshold (unrecognised transliteration or typo, or a generic name that also scored low). 0 name links pointed to a different part with the same or nearly the same description. With geometry (full pipeline) every F variant was linked.
- positive (B): `PA-18634 stop.stp` vs `PA-10011_STOP_AP242.step` - expected identical, got identical_attr_conflict.

## Real STEP files: NIST MBE PMI models

44 real STEP files (NIST CTC/FTC/STC test cases exported by different CAD systems; some files appear in two NIST archives). Read errors: 0.

| Relation (from NIST file names) | Pairs | Tool result |
|---|---:|---|
| same test case | 51 | (not flagged): 2, identical: 26, near_identical: 23 |
| stc-vs-ftc | 16 | identical: 11, near_identical: 5 |
| different test cases | 0 | - |

Of the 51 same-test-case pairs, 11 are the same file name in the two NIST archives (results: identical: 11). The other 40 pairs are different exports of the same test case (AP203 geometry-only, AP203 with PMI, AP242; NIST removed the names of the CAD systems): (not flagged): 2, identical: 15, near_identical: 23. No pair of different test cases was flagged.

Pairs of the same test case (tool category, largest property difference):

| File A (archive) | File B (archive) | Category | Max relative property difference |
|---|---|---|---:|
| nist_ctc_01_asme1_rd.stp (CAD-models) | nist_ctc_01_asme1_rd.stp (PMI-STEP) | identical | - |
| nist_ctc_01_asme1_rd.stp (CAD-models) | nist_ctc_01_asme1_ap203.stp (PMI-STEP) | identical | 0.0e+00 |
| nist_ctc_01_asme1_rd.stp (CAD-models) | nist_ctc_01_asme1_ap242-e1.stp (PMI-STEP) | near_identical | 1.1e-03 |
| nist_ctc_02_asme1_rc.stp (CAD-models) | nist_ctc_02_asme1_rc.stp (PMI-STEP) | identical | - |
| nist_ctc_02_asme1_rc.stp (CAD-models) | nist_ctc_02_asme1_ap203.stp (PMI-STEP) | near_identical | 4.8e-05 |
| nist_ctc_02_asme1_rc.stp (CAD-models) | nist_ctc_02_asme1_ap242-e2.stp (PMI-STEP) | near_identical | 4.9e-04 |
| nist_ctc_03_asme1_rc.stp (CAD-models) | nist_ctc_03_asme1_rc.stp (PMI-STEP) | identical | - |
| nist_ctc_03_asme1_rc.stp (CAD-models) | nist_ctc_03_asme1_ap203.stp (PMI-STEP) | identical | 0.0e+00 |
| nist_ctc_03_asme1_rc.stp (CAD-models) | nist_ctc_03_asme1_ap242-e2.stp (PMI-STEP) | near_identical | 1.5e-03 |
| nist_ctc_04_asme1_rd.stp (CAD-models) | nist_ctc_04_asme1_rd.stp (PMI-STEP) | identical | - |
| nist_ctc_04_asme1_rd.stp (CAD-models) | nist_ctc_04_asme1_ap203.stp (PMI-STEP) | identical | 3.8e-05 |
| nist_ctc_04_asme1_rd.stp (CAD-models) | nist_ctc_04_asme1_ap242-e1.stp (PMI-STEP) | near_identical | 5.4e-04 |
| nist_ctc_05_asme1_rd.stp (CAD-models) | nist_ctc_05_asme1_rd.stp (PMI-STEP) | identical | - |
| nist_ctc_05_asme1_rd.stp (CAD-models) | nist_ctc_05_asme1_ap203.stp (PMI-STEP) | near_identical | 9.3e-07 |
| nist_ctc_05_asme1_rd.stp (CAD-models) | nist_ctc_05_asme1_ap242-e1.stp (PMI-STEP) | near_identical | 4.7e-07 |
| nist_ftc_06_asme1_rd.stp (CAD-models) | nist_ftc_06_asme1_rd.stp (PMI-STEP) | identical | - |
| nist_ftc_06_asme1_rd.stp (CAD-models) | nist_ftc_06_asme1_ap242-e2.stp (PMI-STEP) | identical | 8.6e-06 |
| nist_ftc_07_asme1_rd.stp (CAD-models) | nist_ftc_07_asme1_rd.stp (PMI-STEP) | identical | - |
| nist_ftc_07_asme1_rd.stp (CAD-models) | nist_ftc_07_asme1_ap242-e2.stp (PMI-STEP) | identical | 1.0e-05 |
| nist_ftc_08_asme1_rc.stp (CAD-models) | nist_ftc_08_asme1_rc.stp (PMI-STEP) | identical | - |
| nist_ftc_08_asme1_rc.stp (CAD-models) | nist_ftc_08_asme1_ap242-e1-tg.stp (PMI-STEP) | near_identical | 1.3e-03 |
| nist_ftc_08_asme1_rc.stp (CAD-models) | nist_ftc_08_asme1_ap242-e2.stp (PMI-STEP) | near_identical | 1.9e-04 |
| nist_ftc_09_asme1_rd.stp (CAD-models) | nist_ftc_09_asme1_rd.stp (PMI-STEP) | identical | - |
| nist_ftc_09_asme1_rd.stp (CAD-models) | nist_ftc_09_asme1_ap242-e1.stp (PMI-STEP) | identical | 1.3e-05 |
| nist_ftc_10_asme1_rb.stp (CAD-models) | nist_ftc_10_asme1_rb.stp (PMI-STEP) | identical | - |
| nist_ftc_10_asme1_rb.stp (CAD-models) | nist_ftc_10_asme1_ap242-e2.stp (PMI-STEP) | identical | 9.8e-08 |
| nist_ftc_11_asme1_rb.stp (CAD-models) | nist_ftc_11_asme1_rb.stp (PMI-STEP) | identical | - |
| nist_ftc_11_asme1_rb.stp (CAD-models) | nist_ftc_11_asme1_ap242-e2.stp (PMI-STEP) | (not flagged) | - |
| nist_ctc_01_asme1_rd.stp (PMI-STEP) | nist_ctc_01_asme1_ap203.stp (PMI-STEP) | identical | 0.0e+00 |
| nist_ctc_01_asme1_rd.stp (PMI-STEP) | nist_ctc_01_asme1_ap242-e1.stp (PMI-STEP) | near_identical | 1.1e-03 |
| nist_ctc_02_asme1_rc.stp (PMI-STEP) | nist_ctc_02_asme1_ap203.stp (PMI-STEP) | near_identical | 4.8e-05 |
| nist_ctc_02_asme1_rc.stp (PMI-STEP) | nist_ctc_02_asme1_ap242-e2.stp (PMI-STEP) | near_identical | 4.9e-04 |
| nist_ctc_03_asme1_rc.stp (PMI-STEP) | nist_ctc_03_asme1_ap203.stp (PMI-STEP) | identical | 0.0e+00 |
| nist_ctc_03_asme1_rc.stp (PMI-STEP) | nist_ctc_03_asme1_ap242-e2.stp (PMI-STEP) | near_identical | 1.5e-03 |
| nist_ctc_04_asme1_rd.stp (PMI-STEP) | nist_ctc_04_asme1_ap203.stp (PMI-STEP) | identical | 3.8e-05 |
| nist_ctc_04_asme1_rd.stp (PMI-STEP) | nist_ctc_04_asme1_ap242-e1.stp (PMI-STEP) | near_identical | 5.4e-04 |
| nist_ctc_05_asme1_rd.stp (PMI-STEP) | nist_ctc_05_asme1_ap203.stp (PMI-STEP) | near_identical | 9.3e-07 |
| nist_ctc_05_asme1_rd.stp (PMI-STEP) | nist_ctc_05_asme1_ap242-e1.stp (PMI-STEP) | near_identical | 4.7e-07 |
| nist_ftc_06_asme1_rd.stp (PMI-STEP) | nist_ftc_06_asme1_ap242-e2.stp (PMI-STEP) | identical | 8.6e-06 |
| nist_ftc_07_asme1_rd.stp (PMI-STEP) | nist_ftc_07_asme1_ap242-e2.stp (PMI-STEP) | identical | 1.0e-05 |
| nist_ftc_08_asme1_rc.stp (PMI-STEP) | nist_ftc_08_asme1_ap242-e1-tg.stp (PMI-STEP) | near_identical | 1.3e-03 |
| nist_ftc_08_asme1_rc.stp (PMI-STEP) | nist_ftc_08_asme1_ap242-e2.stp (PMI-STEP) | near_identical | 1.9e-04 |
| nist_ftc_09_asme1_rd.stp (PMI-STEP) | nist_ftc_09_asme1_ap242-e1.stp (PMI-STEP) | identical | 1.3e-05 |
| nist_ftc_10_asme1_rb.stp (PMI-STEP) | nist_ftc_10_asme1_ap242-e2.stp (PMI-STEP) | identical | 9.8e-08 |
| nist_ftc_11_asme1_rb.stp (PMI-STEP) | nist_ftc_11_asme1_ap242-e2.stp (PMI-STEP) | (not flagged) | - |
| nist_ctc_01_asme1_ap203.stp (PMI-STEP) | nist_ctc_01_asme1_ap242-e1.stp (PMI-STEP) | near_identical | 1.1e-03 |
| nist_ctc_02_asme1_ap203.stp (PMI-STEP) | nist_ctc_02_asme1_ap242-e2.stp (PMI-STEP) | near_identical | 4.9e-04 |
| nist_ctc_03_asme1_ap203.stp (PMI-STEP) | nist_ctc_03_asme1_ap242-e2.stp (PMI-STEP) | near_identical | 1.5e-03 |
| nist_ctc_04_asme1_ap203.stp (PMI-STEP) | nist_ctc_04_asme1_ap242-e1.stp (PMI-STEP) | near_identical | 5.8e-04 |
| nist_ctc_05_asme1_ap203.stp (PMI-STEP) | nist_ctc_05_asme1_ap242-e1.stp (PMI-STEP) | identical | 8.0e-07 |
| nist_ftc_08_asme1_ap242-e1-tg.stp (PMI-STEP) | nist_ftc_08_asme1_ap242-e2.stp (PMI-STEP) | near_identical | 1.4e-03 |

## Speed

Feasibility (work order step 2): 83 STEP files (83 read OK, 0 errors), 1 worker, cold: mean 0.483 s, median 0.26 s, p90 1.275 s, max 2.659 s per file (time split: read 53%, properties 24%, mesh 20%).

Benchmark: 5000 random ABC STEP files (1536.7 MB, median 89.5 KB, max 2889.8 KB), 2 workers on a 2-vCPU cloud VM, cold cache: **20.29 min total** (0.243 s per file wall-clock). Geometry per file in a worker: mean 0.362 s, median 0.083 s, p90 1.028 s, max 25.04 s. Stages: scan + hashes 110.4 s, geometry (L3) 905.8 s, scoring incl. L3b 195.9 s, of which L3b 173.3 s (2677 L3b checks). Errors/skips: no usable geometry: 2. Peak RSS of the largest process: 591.7 MB.

Before the last speed-up (same 5,000 files, same machine) the run took 30.0 min (scoring stage 760.9 s, of which L3b shape checks 718.5 s). L3b now runs only where it can change the result and in parallel processes; dev and test metrics were identical before and after.

## Threshold sweeps on the dev set

Provenance: `geo_near` = 0.10 was chosen on an earlier build of the dev set (same 250 ABC base parts, 18 E variants, code before the stray-sheet and unique-surface changes). In that sweep, `geo_near` 0.05 and 0.08 found 17 of 18 E variants (the miss was a fillet that changed the surface area by 9%) and 0.10 and 0.15 found 18 of 18, all with 0 false positives. That console output was not saved to a file before the dev set was rebuilt with more E and F variants. The geometry sweep below was re-run on the final dev set after the test run, for the record only: on this set every setting gives the same metrics, so it does not discriminate. The name thresholds were chosen from the name sweep below (final dev set, before the test set was built).

Geometry:

| geo_near | shape_near_excess50 | E P/R | F P/R/F1 | FP rate |
|---:|---:|---:|---:|---:|
| 0.05 | 2.0 | 100.0%/100.0% | 100.0%/78.0%/0.876 | 0.0% |
| 0.05 | 3.0 | 100.0%/100.0% | 100.0%/78.0%/0.876 | 0.0% |
| 0.05 | 4.0 | 100.0%/100.0% | 100.0%/78.0%/0.876 | 0.0% |
| 0.08 | 2.0 | 100.0%/100.0% | 100.0%/78.0%/0.876 | 0.0% |
| 0.08 | 3.0 | 100.0%/100.0% | 100.0%/78.0%/0.876 | 0.0% |
| 0.08 | 4.0 | 100.0%/100.0% | 100.0%/78.0%/0.876 | 0.0% |
| 0.1 | 2.0 | 100.0%/100.0% | 100.0%/78.0%/0.876 | 0.0% |
| 0.1 | 3.0 | 100.0%/100.0% | 100.0%/78.0%/0.876 | 0.0% |
| 0.1 | 4.0 | 100.0%/100.0% | 100.0%/78.0%/0.876 | 0.0% |
| 0.15 | 2.0 | 100.0%/100.0% | 100.0%/78.0%/0.876 | 0.0% |
| 0.15 | 3.0 | 100.0%/100.0% | 100.0%/78.0%/0.876 | 0.0% |
| 0.15 | 4.0 | 100.0%/100.0% | 100.0%/78.0%/0.876 | 0.0% |

Names:

| name_similar | name_k0 | name_partial_factor | E P/R | F P/R/F1 | FP rate |
|---:|---:|---:|---:|---:|---:|
| 0.85 | 2 | 0.8 | 100.0%/100.0% | 100.0%/72.0%/0.837 | 0.0% |
| 0.85 | 2 | 0.85 | 100.0%/100.0% | 100.0%/72.0%/0.837 | 0.0% |
| 0.85 | 2 | 0.9 | 100.0%/100.0% | 100.0%/72.0%/0.837 | 0.0% |
| 0.85 | 3 | 0.8 | 100.0%/100.0% | 100.0%/78.0%/0.876 | 0.0% |
| 0.85 | 3 | 0.85 | 100.0%/100.0% | 96.5%/78.0%/0.863 | 0.0% |
| 0.85 | 3 | 0.9 | 100.0%/100.0% | 96.5%/78.0%/0.863 | 0.0% |
| 0.85 | 4 | 0.8 | 100.0%/100.0% | 88.2%/84.0%/0.861 | 0.0% |
| 0.85 | 4 | 0.85 | 100.0%/100.0% | 85.7%/84.0%/0.849 | 0.0% |
| 0.85 | 4 | 0.9 | 100.0%/100.0% | 85.7%/84.0%/0.849 | 0.0% |
| 0.9 | 2 | 0.8 | 100.0%/100.0% | 100.0%/72.0%/0.837 | 0.0% |
| 0.9 | 2 | 0.85 | 100.0%/100.0% | 100.0%/72.0%/0.837 | 0.0% |
| 0.9 | 2 | 0.9 | 100.0%/100.0% | 100.0%/72.0%/0.837 | 0.0% |
| 0.9 | 3 | 0.8 | 100.0%/100.0% | 100.0%/78.0%/0.876 | 0.0% |
| 0.9 | 3 | 0.85 | 100.0%/100.0% | 100.0%/78.0%/0.876 | 0.0% |
| 0.9 | 3 | 0.9 | 100.0%/100.0% | 96.5%/78.0%/0.863 | 0.0% |
| 0.9 | 4 | 0.8 | 100.0%/100.0% | 100.0%/78.0%/0.876 | 0.0% |
| 0.9 | 4 | 0.85 | 100.0%/100.0% | 100.0%/78.0%/0.876 | 0.0% |
| 0.9 | 4 | 0.9 | 100.0%/100.0% | 96.5%/78.0%/0.863 | 0.0% |

## Thresholds used

```json
{
 "geo_exact": 1e-06,
 "geo_identical": 0.0001,
 "geo_near": 0.1,
 "geo_split_type_tol": 0.0002,
 "near_max_face_ratio": 3.0,
 "near_max_type_dist": 0.25,
 "unit_tol": 0.0001,
 "name_similar": 0.9,
 "name_k0": 3,
 "name_partial_factor": 0.85,
 "name_candidate": 0.7,
 "shape_same_excess50": 2.0,
 "shape_near_excess50": 3.0,
 "shape_near_p95": 0.1,
 "mirror_ratio": 0.6,
 "skew_min": 0.004
}
```
