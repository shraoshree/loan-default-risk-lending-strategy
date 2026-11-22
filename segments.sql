WITH segments AS (
    SELECT 'loan_purpose' AS dimension, purpose AS segment, pd, defaulted
    FROM scored
    UNION ALL
    SELECT 'home_ownership', home_ownership, pd, defaulted
    FROM scored
)
SELECT dimension, COALESCE(segment, '(missing)') AS segment,
       COUNT(*) AS loans, SUM(pd > :threshold) AS excluded,
       AVG(pd > :threshold) AS exclusion_rate,
       AVG(pd) AS mean_pd, AVG(defaulted) AS observed_chargeoff_rate,
       AVG(CASE WHEN pd > :threshold THEN defaulted END) AS excluded_chargeoff_rate
FROM segments
GROUP BY dimension, COALESCE(segment, '(missing)')
ORDER BY dimension, loans DESC, segment;
