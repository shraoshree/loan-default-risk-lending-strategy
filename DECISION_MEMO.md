# Lending Strategy Decision Memo

**Decision.** Advance the 20% modeled default-risk cutoff to a backtest on newer cohorts. The 2015 holdout supports further evaluation because the rule reduced losses relative to keeping all historical originations. At the stated costs, the cutoff improved historical holdout margin by $13.1M. The cost sensitivity shows when that advantage holds.

## What the holdout showed

| Metric | Approve all | 20% risk cutoff |
| --- | ---: | ---: |
| Loans retained | 283,026 | 250,339 |
| Share retained | 100.0% | 88.5% |
| Charge-off rate among retained loans | 14.89% | 13.46% |
| Historical cash-flow margin per evaluated loan | −$106.27 | −$60.01 |
| Modeled profit per evaluated loan under stress | −$559.29 | −$427.84 |

The baseline retained roughly $3.62 billion in loan principal and the 20% rule retained roughly $3.28 billion. The 32,687 loans the rule would exclude had an observed charge-off rate of 25.77%. Both policies had positive gross cash margin before funding and operating costs. At $150 operating cost per funded loan, both break even below approximately 3.45% annual funding, and the cutoff leads in total margin above approximately 1.48%. At the assumed 4% rate it improves the margin by $46.25 per evaluated loan. The model-based profit was positive in the base case, while the historical cash-flow proxy was negative under both policies. That gap limits confidence in the modeled dollar estimates.

## Challenger and calibration

Adding five application-time features raised holdout ROC AUC from 0.641 to 0.651. Its separately selected 20% cutoff improved historical holdout margin by $15.7M versus approve-all. Verify this follow-up result on a fresh vintage because it reuses the original holdout. The observed charge-off rate rose from 12.33% in the 2013 training vintage to 14.89% in 2015, consistent with the original model underestimating later-cohort risk.

## Before considering a rollout

1. Recalibrate default probabilities on a newer mature cohort and verify the improvement against a realistic existing policy using actual funding and servicing costs.
2. Review retention and calibration across segments. The holdout exclusion rate was 19.9% for renters and 3.7% for mortgage holders. Medical-purpose loans had a 35.0% exclusion rate (1,102 of 3,146). Review these disparities and potential proxy effects with fair-lending specialists before any policy use.
3. Treat pricing as a separate decision. Estimate how offer take-up and repayment change with price before using a rate increase in a profitability forecast.

[Holdout policy results](empirical/test_policies.csv) · [Risk bands](empirical/test_risk_bands.csv) · [Segment results](empirical/test_segments.csv)
