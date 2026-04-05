# Universe Stability Diagnostics

Snapshots: 71
Mean Jaccard overlap: 0.7912
Min Jaccard overlap: 0.5
Universe size range: [53, 145]

## Signal Distribution Drift (first half vs second half)

| Signal | Mean₁ | Mean₂ | Shift | Std₁ | Std₂ | Material? |
|--------|-------|-------|-------|------|------|-----------|
| coinvest_score_z | 0.1758 | 0.2341 | +0.0583 | 1.003 | 0.9911 | no |
| inst_delta_z | 0.0199 | 0.0211 | +0.0012 | 0.9704 | 0.7201 | no |
| clinical_score_v2_z | 0.0615 | 0.0068 | -0.0547 | 0.9985 | 0.995 | no |
| catalyst_decay_w | 0.1646 | 0.3111 | +0.1465 | 0.2742 | 0.356 | no |
| financial_score | 48.8852 | 45.4009 | -3.4844 | 21.233 | 22.0896 | YES |
| composite_score | 0.0265 | 0.0408 | +0.0143 | 0.0412 | 0.0418 | no |