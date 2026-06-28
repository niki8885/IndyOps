-- | Greedy dependency-ordered stage scheduling — a port of
-- @app.services.scheduling.stage_schedule@ used by the Reaction Planner to get a
-- candidate's makespan (and peak slot usage) for the income-per-hour metric.
--
-- A job enters a stage once every job producing its *make* inputs sits in an earlier
-- stage; within a stage at most @manSlots@ manufacturing + @reactSlots@ reaction jobs
-- run in parallel (a slot count @<= 0@ means unlimited). Each stage's wall-clock is its
-- longest job; the makespan sums the stages. Jobs are picked in ascending index order
-- to match the Python oracle exactly (the chain core emits jobs in the same order in
-- both engines, so the schedules — and the peaks — agree on strict equality).
module Chain.Schedule
  ( ScheduleSummary(..)
  , scheduleSummary
  ) where

import Data.List (foldl')
import qualified Data.Map.Strict as M
import qualified Data.Set as S

import Chain.Types

data ScheduleSummary = ScheduleSummary
  { schTotalTimeS  :: !Int
  , schTotalStages :: !Int
  , schPeakMan     :: !Int
  , schPeakReact   :: !Int
  } deriving (Eq, Show)

scheduleSummary :: [PlannedJob] -> Int -> Int -> ScheduleSummary
scheduleSummary jobs manSlots reactSlots =
  let n        = length jobs
      indexed  = zip [0 ..] jobs
      jobsMap  = M.fromList indexed
      capMan   = if manSlots > 0 then Just manSlots else Nothing
      capReact = if reactSlots > 0 then Just reactSlots else Nothing

      producers :: M.Map Int [Int]
      producers = M.fromListWith (++) [(pjType j, [i]) | (i, j) <- indexed]
      depsOf j  = S.fromList
        [ p | inp <- pjInputs j, jiIsMake inp
            , p <- M.findWithDefault [] (jiType inp) producers ]
      depsMap   = M.fromList [(i, depsOf j) | (i, j) <- indexed]

      isReaction i = pjSlotKind (jobsMap M.! i) == "reaction"

      -- one stage: pick ready jobs in ascending index order under the slot caps
      pickStage ready scheduled =
        foldl' step ([], 0, 0, scheduled) ready
        where
          step acc@(picked, manU, reactU, sch) i
            | isReaction i = case capReact of
                Just c | reactU >= c -> acc
                _ -> (picked ++ [i], manU, reactU + 1, S.insert i sch)
            | otherwise = case capMan of
                Just c | manU >= c -> acc
                _ -> (picked ++ [i], manU + 1, reactU, S.insert i sch)

      go scheduled stages
        | S.size scheduled >= n = reverse stages
        | otherwise =
            let ready0 = [ i | (i, _) <- indexed
                             , not (S.member i scheduled)
                             , depsMap M.! i `S.isSubsetOf` scheduled ]
                ready   = if null ready0
                            then [ i | (i, _) <- indexed, not (S.member i scheduled) ]
                            else ready0
                (picked, manU, reactU, scheduled') = pickStage ready scheduled
                stageTime = maximum (0 : [pjTime (jobsMap M.! i) | i <- picked])
            in go scheduled' ((manU, reactU, stageTime) : stages)

      stages = go S.empty []
  in ScheduleSummary
       { schTotalTimeS  = sum [t | (_, _, t) <- stages]
       , schTotalStages = length stages
       , schPeakMan     = maximum (0 : [m | (m, _, _) <- stages])
       , schPeakReact   = maximum (0 : [r | (_, r, _) <- stages])
       }
