module Invention.Optimize
  ( optimize
  , evalCand
  ) where

import Data.List (sortBy)

import Invention.Types

-- | Enumerate every (product × decryptor), evaluate its economics, and rank by a
-- z-scored composite of production metrics. Mirrors services.invention_opt.optimize
-- (the Python oracle) exactly — keep both sides identical.
optimize :: [(String, Double)] -> [Product] -> [Decryptor] -> [Cand]
optimize wover prods decs =
  rankCands wover [ evalCand p d | p <- prods, d <- decs ]

-- per-candidate economics (mirror services.invention.evaluate) ----------------

evalCand :: Product -> Decryptor -> Cand
evalCand p d = Cand
  { cLabel          = pName p ++ " / " ++ dName d
  , cProductTypeId  = pTypeId p
  , cProductName    = pName p
  , cDecryptor      = dName d
  , cProbability    = prob
  , cBpcRuns        = bpcRuns
  , cBpcMe          = bpcMe
  , cBpcTe          = bpcTe
  , cCostPerAttempt = costPerAttempt
  , cCostPerBpc     = costPerBpc
  , cCostPerRun     = costPerRun
  , cManufCostPerRun= manufCostPerRun
  , cUnitsPerRun    = units
  , cSellPerUnit    = pSellPerUnit p
  , cCostPerUnit    = costPerUnit
  , cProfitPerUnit  = profitPerUnit
  , cProfitPerRun   = profitPerRun
  , cMarginPct      = marginPct
  , cRank           = 0
  , cScore          = 0
  }
  where
    skillFactor = 1 + (fromIntegral (pSci1 p) + fromIntegral (pSci2 p)) / 30
                    + fromIntegral (pEncryption p) / 40
    prob = clamp01 (pBaseProb p * skillFactor * (1 + dProbMod d / 100))
    bpcRuns = max 1 (pBaseRuns p + dRunsMod d)
    bpcMe   = max 0 (2 + dMeMod d)
    bpcTe   = max 0 (4 + dTeMod d)
    units   = max 1 (pUnitsPerRun p)

    costPerAttempt = pDatacoreCost p + dPrice d + pInventionInstall p
    costPerBpc = if prob > 0 then costPerAttempt / prob else 1 / 0
    costPerRun = costPerBpc / fromIntegral bpcRuns

    matCost = sum [ fromIntegral (adjQty (mQty m) 1 bpcMe (pMatExtraMult p)) * mPrice m
                  | m <- pMaterials p ]
    manufCostPerRun = matCost + pManufInstallPerRun p

    costPerUnit   = (manufCostPerRun + costPerRun) / fromIntegral units
    profitPerUnit = pSellPerUnit p - costPerUnit
    profitPerRun  = profitPerUnit * fromIntegral units
    marginPct     = if costPerUnit > 0 then profitPerUnit / costPerUnit * 100 else 0

clamp01 :: Double -> Double
clamp01 x = min 1.0 (max 0.0 x)

-- material qty after ME, matching services.manufacturing.adj_qty:
-- max(runs, ceil(base * runs * (1 - me/100) * extra)).
adjQty :: Integer -> Int -> Int -> Double -> Integer
adjQty base runs me extra =
  max (fromIntegral runs)
      (ceiling (fromIntegral base * fromIntegral runs * (1 - fromIntegral me / 100) * extra))

-- ranking (mirror services.invention_opt._rank / Risk.Score) -------------------

metrics :: [(String, Cand -> Double, Double, Double)]
metrics =
  [ ("profit_per_run",  cProfitPerRun,  1.0, 1.0)
  , ("margin_pct",      cMarginPct,     1.0, 1.0)
  , ("profit_per_unit", cProfitPerUnit, 1.0, 0.5)
  , ("cost_per_bpc",    cCostPerBpc,   -1.0, 0.5)
  , ("probability",     cProbability,   1.0, 0.5)
  ]

mean :: [Double] -> Double
mean xs = sum xs / fromIntegral (length xs)

pstd :: [Double] -> Double
pstd xs = sqrt (sum [(x - m) ** 2 | x <- xs] / fromIntegral (length xs))
  where m = mean xs

rankCands :: [(String, Double)] -> [Cand] -> [Cand]
rankCands _ [] = []
rankCands wover cands =
  [ c { cRank = r, cScore = sc } | (r, (c, sc)) <- zip [1 ..] sorted ]
  where
    weightOf name dflt = maybe dflt id (lookup name wover)
    contrib (name, acc, sign, dflt) =
      let vals = map acc cands
          m = mean vals
          sd = pstd vals
          w = weightOf name dflt
      in if sd > 0 then [w * sign * (v - m) / sd | v <- vals]
                   else replicate (length cands) 0.0
    scores = foldr (zipWith (+)) (replicate (length cands) 0.0) (map contrib metrics)
    sorted = sortBy cmp (zip cands scores)
    cmp (c1, s1) (c2, s2) =
      compare s2 s1
        <> compare (cProfitPerRun c2) (cProfitPerRun c1)
        <> compare (cLabel c1) (cLabel c2)
