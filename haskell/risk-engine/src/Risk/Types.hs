module Risk.Types
  ( Strategy(..)
  , RankRequest(..)
  , Ranked(..)
  , decodeRequest
  , encodeRanked
  ) where

import Json

-- request: a candidate strategy's ranking-relevant metrics (a subset of
-- services.profit_sim.SimMetrics — see services.profit_sim.RankInput).

data Strategy = Strategy
  { sLabel          :: !String
  , sExpectedProfit :: !Double
  , sSharpeLike     :: !Double
  , sVar5           :: !Double
  , sReturnPerSlot  :: !Double
  , sReturnPerTime  :: !Double
  , sProbLoss       :: !Double
  }

data RankRequest = RankRequest
  { rrWeights    :: ![(String, Double)]   -- per-metric weight overrides (optional)
  , rrStrategies :: ![Strategy]
  }

-- response

data Ranked = Ranked
  { rkRank  :: !Int
  , rkLabel :: !String
  , rkScore :: !Double
  }

-- decode

decodeRequest :: JValue -> Either String RankRequest
decodeRequest v = do
  stratsV <- field "strategies" v >>= asArr
  strats  <- mapM decStrategy stratsV
  wts     <- decWeights v
  Right (RankRequest wts strats)

decWeights :: JValue -> Either String [(String, Double)]
decWeights v = do
  mw <- fieldMaybe "weights" v
  case mw of
    Nothing -> Right []
    Just wv -> asObj wv >>= mapM (\(k, x) -> (,) k <$> asDouble x)

decStrategy :: JValue -> Either String Strategy
decStrategy v = Strategy
  <$> (field "label" v >>= asString)
  <*> num "expected_profit"
  <*> num "sharpe_like"
  <*> num "var5"
  <*> num "return_per_slot"
  <*> num "return_per_time"
  <*> num "prob_loss"
  where num k = field k v >>= asDouble

-- encode

encodeRanked :: [Ranked] -> JValue
encodeRanked rs = JObj [("ranked", JArr (map enc rs))]
  where
    enc r = JObj
      [ ("rank", JInt (fromIntegral (rkRank r)))
      , ("label", JStr (rkLabel r))
      , ("score", JNum (toRational (rkScore r)))
      ]
