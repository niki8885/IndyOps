module Main (main) where
import Data.Ratio ((%))
import System.Exit (exitFailure)
import Chain.Solver (solveChain)
import Chain.Types
import Json

main :: IO ()
main = do
  rs <- sequence
    [ check "decRational 0.958 = 479/500" (parseNum "0.958" == Just (479 % 500))
    , check "decRational 1.5e9"           (parseNum "1.5e9" == Just (1500000000 % 1))
    , check "decRational -0.042"          (parseNum "-0.042" == Just ((-42) % 1000))
    , check "decRational 100000.0"        (parseNum "100000.0" == Just (100000 % 1))
    , check "decRational 1e+21"           (parseNum "1e+21" == Just (10 ^ (21 :: Int) % 1))
    , testWidget
    , testNonTerminating
    ]
  let n = length rs
      passed = length (filter id rs)
  putStrLn ("--- " ++ show passed ++ "/" ++ show n ++ " passed ---")
  if passed == n then pure () else exitFailure

check :: String -> Bool -> IO Bool
check name ok = do
  putStrLn ((if ok then "PASS  " else "FAIL  ") ++ name)
  pure ok

parseNum :: String -> Maybe Rational
parseNum s = case parse s of
  Right (JNum r) -> Just r
  _              -> Nothing

solveJson :: String -> Either String ChainPlan
solveJson s = solveChain <$> (parse s >>= decodeRequest)

loc :: String
loc = "{\"place_id\":10,\"place_name\":\"P\",\"slot_kind\":\"manufacturing\","
   ++ "\"me_mult\":1.0,\"te_mult\":1.0,\"sci\":0.0,\"tax\":0.0,\"scc\":0.0,"
   ++ "\"struct_discount\":0.0,\"eiv_unit\":0.0,\"bpc_unit\":0.0}"

testWidget :: IO Bool
testWidget =
  let json =
        "{\"target_type_id\":1,\"target_qty\":3,\"nodes\":{"
        ++ "\"1\":{\"type_id\":1,\"name\":\"WIDGET\",\"buy_price\":100000.0,\"recipes\":[{"
        ++ "\"activity\":1,\"blueprint_type_id\":101,\"qty_per_run\":1,\"base_time\":600,"
        ++ "\"max_runs\":10,\"inputs\":[[2,10],[3,5]],\"locations\":[" ++ loc ++ "]}]},"
        ++ "\"2\":{\"type_id\":2,\"name\":\"A\",\"buy_price\":1000.0,\"recipes\":[{"
        ++ "\"activity\":1,\"blueprint_type_id\":102,\"qty_per_run\":1,\"base_time\":300,"
        ++ "\"max_runs\":10,\"inputs\":[[3,20]],\"locations\":[" ++ loc ++ "]}]},"
        ++ "\"3\":{\"type_id\":3,\"name\":\"RAW\",\"buy_price\":10.0,\"recipes\":[]}}}"
  in case solveJson json of
       Left e -> check ("widget parse: " ++ e) False
       Right p ->
         let dec t = lookup t (plDecisions p)
             aJobs = [j | j <- plJobs p, pjType j == 2]
             rawShop = [s | s <- plShopping p, slType s == 3]
         in check "widget: unit_cost = 2050" (plUnit p == Just (2050 % 1))
              `andM` check "widget: total = 6150" (plTotal p == 6150 % 1)
              `andM` check "widget: WIDGET make" (fmap dDecision (dec 1) == Just "make")
              `andM` check "widget: A make 200" ((dec 2 >>= dUnitCost) == Just (200 % 1))
              `andM` check "widget: RAW buy" (fmap dDecision (dec 3) == Just "buy")
              `andM` check "widget: A one job (30d limit, not maxRuns)" (map pjRuns aJobs == [30])
              `andM` check "widget: RAW qty 615" (map slQty rawShop == [615])


testNonTerminating :: IO Bool
testNonTerminating =
  let json =
        "{\"target_type_id\":1,\"target_qty\":1,\"nodes\":{"
        ++ "\"1\":{\"type_id\":1,\"name\":\"P\",\"buy_price\":100.0,\"recipes\":[{"
        ++ "\"activity\":1,\"blueprint_type_id\":9,\"qty_per_run\":3,\"base_time\":1,"
        ++ "\"max_runs\":100,\"inputs\":[[2,1]],\"locations\":[" ++ loc ++ "]}]},"
        ++ "\"2\":{\"type_id\":2,\"name\":\"RAW\",\"buy_price\":10.0,\"recipes\":[]}}}"
  in case solveJson json of
       Left e  -> check ("nonterm parse: " ++ e) False
       Right p -> check "nonterm: unit_cost = 10/3" (plUnit p == Just (10 % 3))

andM :: IO Bool -> IO Bool -> IO Bool
andM a b = do
  x <- a
  y <- b
  pure (x && y)
