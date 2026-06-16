module Risk.Score
  ( rankStrategies
  , defaultWeights
  ) where

import Data.List (sortBy)

import Risk.Types

-- (metric name, accessor, sign [+1 higher-is-better / −1 lower], default weight).
-- Mirrors services.profit_sim._RANK_METRICS exactly so the Python fallback and
-- this engine produce the same ranking.
metrics :: [(String, Strategy -> Double, Double, Double)]
metrics =
  [ ("expected_profit", sExpectedProfit,  1.0, 1.0)
  , ("sharpe_like",     sSharpeLike,      1.0, 1.0)
  , ("var5",            sVar5,            1.0, 1.0)
  , ("return_per_slot", sReturnPerSlot,   1.0, 0.5)
  , ("return_per_time", sReturnPerTime,   1.0, 0.5)
  , ("prob_loss",       sProbLoss,       -1.0, 1.0)
  ]

defaultWeights :: [(String, Double)]
defaultWeights = [(name, w) | (name, _, _, w) <- metrics]

mean :: [Double] -> Double
mean xs = sum xs / fromIntegral (length xs)

-- population standard deviation (ddof=0), matching numpy's default
pstd :: [Double] -> Double
pstd xs = sqrt (sum [(x - m) ** 2 | x <- xs] / fromIntegral (length xs))
  where m = mean xs

-- | Composite risk-adjusted ranking. Each metric is z-scored across the candidate
-- set (population std; a constant metric contributes 0), signed so higher is
-- better, then weighted-summed. Sorted by score desc; ties broken by
-- expected_profit desc, then label asc. Deterministic — see
-- services.profit_sim.rank_strategies.
rankStrategies :: [(String, Double)] -> [Strategy] -> [Ranked]
rankStrategies _ [] = []
rankStrategies wover strs =
  [Ranked r (sLabel s) sc | (r, (s, sc)) <- zip [1 ..] sorted]
  where
    weightOf name dflt = maybe dflt id (lookup name wover)
    contrib (name, acc, sign, dflt) =
      let vals = map acc strs
          m = mean vals
          sd = pstd vals
          w = weightOf name dflt
      in if sd > 0 then [w * sign * (v - m) / sd | v <- vals]
                   else replicate (length strs) 0.0
    scores = foldr (zipWith (+)) (replicate (length strs) 0.0) (map contrib metrics)
    sorted = sortBy cmp (zip strs scores)
    cmp (s1, sc1) (s2, sc2) =
      compare sc2 sc1
        <> compare (sExpectedProfit s2) (sExpectedProfit s1)
        <> compare (sLabel s1) (sLabel s2)
