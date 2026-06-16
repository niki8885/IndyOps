module Main (main) where

import System.Exit (exitFailure)

import Risk.Score (rankStrategies)
import Risk.Types
import Json (parse)

main :: IO ()
main = do
  rs <- sequence
    [ testOrdering
    , testRanks
    , testSingleScoreZero
    , testWeightOverride
    , testDecode
    , testEmpty
    ]
  let n = length rs
      passed = length (filter id rs)
  putStrLn ("--- " ++ show passed ++ "/" ++ show n ++ " passed ---")
  if passed == n then pure () else exitFailure

check :: String -> Bool -> IO Bool
check name ok = do
  putStrLn ((if ok then "PASS  " else "FAIL  ") ++ name)
  pure ok

andM :: IO Bool -> IO Bool -> IO Bool
andM a b = do { x <- a; y <- b; pure (x && y) }

-- A dominates on profit/sharpe/low-loss; B is worst; C is middling.
sample :: [Strategy]
sample =
  [ Strategy "A" 1000 2.0 (-50)  1000 10 0.1
  , Strategy "B"  500 0.5 (-300)  500  5 0.4
  , Strategy "C" 1200 1.0 (-200)  600  8 0.2
  ]

testOrdering :: IO Bool
testOrdering =
  check "ranking order A,C,B" (map rkLabel (rankStrategies [] sample) == ["A", "C", "B"])

testRanks :: IO Bool
testRanks =
  check "ranks 1,2,3" (map rkRank (rankStrategies [] sample) == [1, 2, 3])

testSingleScoreZero :: IO Bool
testSingleScoreZero =
  let [r] = rankStrategies [] [Strategy "solo" 1 1 1 1 1 0.1]
  in check "single strategy: rank 1, score 0" (rkRank r == 1 && rkScore r == 0.0)

-- Killing every weight but prob_loss (lower is better) ranks the low-loss A first
-- and the high-loss B last, regardless of profit.
testWeightOverride :: IO Bool
testWeightOverride =
  let w = [("expected_profit", 0), ("sharpe_like", 0), ("var5", 0),
           ("return_per_slot", 0), ("return_per_time", 0), ("prob_loss", 1)]
  in check "weight override (prob_loss only) → A,C,B"
       (map rkLabel (rankStrategies w sample) == ["A", "C", "B"])

testDecode :: IO Bool
testDecode =
  let json = "{\"strategies\":["
          ++ "{\"label\":\"X\",\"expected_profit\":900,\"sharpe_like\":1.5,\"var5\":-40,"
          ++ "\"return_per_slot\":900,\"return_per_time\":9,\"prob_loss\":0.15},"
          ++ "{\"label\":\"Y\",\"expected_profit\":100,\"sharpe_like\":0.2,\"var5\":-400,"
          ++ "\"return_per_slot\":100,\"return_per_time\":1,\"prob_loss\":0.6}]}"
  in case parse json >>= decodeRequest of
       Left e  -> check ("decode: " ++ e) False
       Right req ->
         check "decode: 2 strategies" (length (rrStrategies req) == 2)
           `andM` check "decode→rank: X beats Y"
                    (map rkLabel (rankStrategies (rrWeights req) (rrStrategies req)) == ["X", "Y"])

testEmpty :: IO Bool
testEmpty = check "empty strategies → []" (null (rankStrategies [] []))
