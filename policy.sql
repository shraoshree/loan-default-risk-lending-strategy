WITH totals AS (
    SELECT COUNT(*) AS evaluated FROM scored
), approved AS (
    SELECT p.name, COUNT(s.pd) AS approvals,
           AVG(s.defaulted) AS observed_default_rate,
           AVG(s.pd) AS mean_pd,
           COALESCE(SUM(s.amount), 0) AS principal,
           COALESCE(SUM(
               (1 - s.pd) * s.interest * p.interest_multiplier
               - s.pd * s.amount * p.lgd
               - s.funding * p.funding_multiplier
               - p.operating_cost
           ), 0) AS expected_profit,
           COUNT(s.observed_cash_margin) AS loans_with_cash_data,
           CASE WHEN p.interest_multiplier = 1
                     AND p.funding_multiplier = 1
                     AND p.lgd = 0.65
                     AND COUNT(s.observed_cash_margin) = COUNT(s.pd)
                     AND COUNT(s.pd) > 0
                THEN SUM(s.observed_cash_margin - s.funding - p.operating_cost)
           END AS outcome_based_profit
    FROM policies AS p
    LEFT JOIN scored AS s ON s.pd <= p.threshold
    GROUP BY p.name
)
SELECT approved.*, 1.0 * approvals / evaluated AS approval_rate,
       expected_profit / evaluated AS profit_per_evaluated_loan,
       outcome_based_profit / evaluated AS outcome_profit_per_evaluated_loan
FROM approved CROSS JOIN totals
ORDER BY expected_profit DESC, name;
