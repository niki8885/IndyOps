-- | Reaction Planner batch engine — a native port of
-- @app.services.reaction_planner@ (the Python oracle). It reuses the chain solver
-- ('Chain.Solver.solveChain') to cost each candidate from scratch, schedules it
-- ('Chain.Schedule') for the income-per-hour metric, and — for a T2 component with a
-- "bought reactions" variant — compares building the reactions from zero vs buying the
-- finished intermediates. Money/ratio fields stay exact 'Rational' (carried as
-- @[numerator, denominator]@) so the engine matches the oracle on strict equality.
module Chain.Planner
  ( SellConfig(..)
  , Candidate(..)
  , PlannerRequest(..)
  , BlueprintLine(..)
  , ScratchDelta(..)
  , CandidateResult(..)
  , runPlanner
  , decodePlannerRequest
  , encodePlannerResponse
  ) where

import Data.List (foldl', sortBy)
import qualified Data.Map.Strict as M
import Data.Maybe (fromMaybe)
import Data.Ord (Down (..), comparing)
import Data.Ratio (denominator, numerator)

import Chain.Schedule
import Chain.Solver (solveChain)
import Chain.Types
import Json

-- request

data SellConfig = SellConfig
  { scUnitPrice :: !Rational
  , scSalesTax  :: !Rational
  , scBroker    :: !Rational
  , scFreight   :: !Rational
  }

data Candidate = Candidate
  { cdTypeId  :: !Int
  , cdName    :: !String
  , cdSell    :: !SellConfig
  , cdScratch :: !ChainRequest
  , cdBought  :: !(Maybe ChainRequest)
  }

data PlannerRequest = PlannerRequest
  { prManSlots   :: !Int
  , prReactSlots :: !Int
  , prCandidates :: ![Candidate]
  }

-- response

data BlueprintLine = BlueprintLine
  { blType     :: !Int
  , blName     :: !String
  , blActivity :: !Int
  , blRuns     :: !Int
  , blJobs     :: !Int
  , blQtyOut   :: !Int
  }

data ScratchDelta = ScratchDelta
  { sdCheaper :: !String
  , sdScratch :: !Rational
  , sdBought  :: !Rational
  , sdDelta   :: !Rational
  }

data CandidateResult = CandidateResult
  { crTypeId        :: !Int
  , crName          :: !String
  , crTargetQty     :: !Int
  , crDecision      :: !String
  , crUnitMakeCost  :: !Rational
  , crTotalMakeCost :: !Rational
  , crUnitSell      :: !Rational
  , crRevenue       :: !Rational
  , crProfit        :: !Rational
  , crRoi           :: !Rational
  , crTotalTimeS    :: !Int
  , crReactTimeS    :: !Int
  , crManTimeS      :: !Int
  , crIskPerHour    :: !Rational
  , crIskPerSlotH   :: !Rational
  , crRunsMan       :: !Int
  , crRunsReact     :: !Int
  , crTotalStages   :: !Int
  , crPeakMan       :: !Int
  , crPeakReact     :: !Int
  , crBlueprints    :: ![BlueprintLine]
  , crScratchBought :: !(Maybe ScratchDelta)
  }

-- core

runPlanner :: PlannerRequest -> [CandidateResult]
runPlanner req =
  sortBy (comparing (Down . crRoi))
    (map (analyzeCandidate (prManSlots req) (prReactSlots req)) (prCandidates req))

analyzeCandidate :: Int -> Int -> Candidate -> CandidateResult
analyzeCandidate manSlots reactSlots cand =
  let plan  = solveChain (cdScratch cand)
      sched = scheduleSummary (plJobs plan) manSlots reactSlots
      sell  = cdSell cand
      qty   = plQty plan

      reactTimeS = sum [pjTime j | j <- plJobs plan, pjSlotKind j == "reaction"]
      manTimeS   = sum [pjTime j | j <- plJobs plan, pjSlotKind j /= "reaction"]
      runsMan    = sum [pjRuns j | j <- plJobs plan, pjActivity j == 1]
      runsReact  = sum [pjRuns j | j <- plJobs plan, pjActivity j == 11]

      totalCost = plTotal plan
      unitCost  = fromMaybe 0 (plUnit plan)
      fee       = (scSalesTax sell + scBroker sell) / 100
      unitSell  = scUnitPrice sell * (1 - fee) - scFreight sell
      revenue   = unitSell * fromIntegral qty
      profit    = revenue - totalCost
      roi       = if totalCost /= 0 then profit / totalCost else 0
      totalTime = schTotalTimeS sched
      iskHour   = if totalTime /= 0 then profit * 3600 / fromIntegral totalTime else 0
      slotSecs  = reactTimeS + manTimeS
      iskSlotH  = if slotSecs /= 0 then profit * 3600 / fromIntegral slotSecs else 0

      decision  = maybe "unobtainable" dDecision (lookup (cdTypeId cand) (plDecisions plan))
      svb = fmap (scratchDelta totalCost . plTotal . solveChain) (cdBought cand)
  in CandidateResult
       { crTypeId = cdTypeId cand, crName = cdName cand, crTargetQty = qty
       , crDecision = decision
       , crUnitMakeCost = unitCost, crTotalMakeCost = totalCost
       , crUnitSell = unitSell, crRevenue = revenue, crProfit = profit, crRoi = roi
       , crTotalTimeS = totalTime, crReactTimeS = reactTimeS, crManTimeS = manTimeS
       , crIskPerHour = iskHour, crIskPerSlotH = iskSlotH
       , crRunsMan = runsMan, crRunsReact = runsReact
       , crTotalStages = schTotalStages sched
       , crPeakMan = schPeakMan sched, crPeakReact = schPeakReact sched
       , crBlueprints = aggregateBlueprints plan
       , crScratchBought = svb
       }

scratchDelta :: Rational -> Rational -> ScratchDelta
scratchDelta scratchCost boughtCost =
  ScratchDelta { sdCheaper = if boughtCost < scratchCost then "bought" else "scratch"
               , sdScratch = scratchCost, sdBought = boughtCost
               , sdDelta = boughtCost - scratchCost }

-- one line per made node, summed over its jobs, ordered by (activity, type_id)
aggregateBlueprints :: ChainPlan -> [BlueprintLine]
aggregateBlueprints plan =
  sortBy (comparing (\b -> (blActivity b, blType b)))
    (M.elems (foldl' step M.empty (plJobs plan)))
  where
    step acc j = M.insertWith merge (pjType j)
      (BlueprintLine (pjType j) (pjName j) (pjActivity j) (pjRuns j) 1 (pjQtyOut j)) acc
    merge new old = old
      { blRuns = blRuns old + blRuns new
      , blJobs = blJobs old + 1
      , blQtyOut = blQtyOut old + blQtyOut new
      }

-- decode

decodePlannerRequest :: JValue -> Either String PlannerRequest
decodePlannerRequest v = do
  manS   <- field "man_slots" v >>= asInt
  reactS <- field "react_slots" v >>= asInt
  candsV <- field "candidates" v >>= asArr
  cands  <- mapM decCandidate candsV
  Right (PlannerRequest manS reactS cands)

decCandidate :: JValue -> Either String Candidate
decCandidate v = do
  tid     <- field "type_id" v >>= asInt
  name    <- field "name" v >>= asString
  sell    <- field "sell" v >>= decSell
  scratch <- field "scratch" v >>= decodeRequest
  boughtV <- fieldMaybe "bought" v
  bought  <- traverse decodeRequest boughtV
  Right (Candidate tid name sell scratch bought)

decSell :: JValue -> Either String SellConfig
decSell v = SellConfig
  <$> num "unit_price" <*> num "sales_tax_pct" <*> num "broker_fee_pct" <*> num "freight_per_unit"
  where num k = field k v >>= asRational

-- encode

encodePlannerResponse :: [CandidateResult] -> JValue
encodePlannerResponse rs = JObj [("candidates", JArr (map encResult rs))]

encResult :: CandidateResult -> JValue
encResult r = JObj
  [ ("type_id", jInt (crTypeId r))
  , ("name", JStr (crName r))
  , ("target_qty", jInt (crTargetQty r))
  , ("decision", JStr (crDecision r))
  , ("unit_make_cost", jRat (crUnitMakeCost r))
  , ("total_make_cost", jRat (crTotalMakeCost r))
  , ("unit_sell", jRat (crUnitSell r))
  , ("revenue", jRat (crRevenue r))
  , ("profit", jRat (crProfit r))
  , ("roi", jRat (crRoi r))
  , ("total_time_s", jInt (crTotalTimeS r))
  , ("react_time_s", jInt (crReactTimeS r))
  , ("man_time_s", jInt (crManTimeS r))
  , ("isk_per_hour", jRat (crIskPerHour r))
  , ("isk_per_slot_hour", jRat (crIskPerSlotH r))
  , ("runs_by_activity", JObj [("1", jInt (crRunsMan r)), ("11", jInt (crRunsReact r))])
  , ("total_stages", jInt (crTotalStages r))
  , ("peak_man", jInt (crPeakMan r))
  , ("peak_react", jInt (crPeakReact r))
  , ("blueprints", JArr (map encBlueprint (crBlueprints r)))
  , ("scratch_vs_bought", maybe JNull encDelta (crScratchBought r))
  ]

encBlueprint :: BlueprintLine -> JValue
encBlueprint b = JObj
  [ ("type_id", jInt (blType b))
  , ("name", JStr (blName b))
  , ("activity", jInt (blActivity b))
  , ("runs", jInt (blRuns b))
  , ("jobs", jInt (blJobs b))
  , ("qty_out", jInt (blQtyOut b))
  ]

encDelta :: ScratchDelta -> JValue
encDelta d = JObj
  [ ("cheaper", JStr (sdCheaper d))
  , ("scratch_cost", jRat (sdScratch d))
  , ("bought_cost", jRat (sdBought d))
  , ("delta", jRat (sdDelta d))
  ]

jInt :: Int -> JValue
jInt = JInt . fromIntegral

-- | Carry an exact rational as [numerator, denominator] (matches Chain.Types.jRat).
jRat :: Rational -> JValue
jRat r = JArr [JInt (numerator r), JInt (denominator r)]
