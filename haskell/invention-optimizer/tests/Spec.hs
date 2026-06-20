module Main (main) where

import System.Exit (exitFailure)

import Invention.Optimize (optimize, evalCand)
import Invention.Types

main :: IO ()
main = do
  rs <- sequence [testCount, testRankOrder, testEconomics, testNoDecryptorProb]
  let n = length rs; passed = length (filter id rs)
  putStrLn ("--- " ++ show passed ++ "/" ++ show n ++ " passed ---")
  if passed == n then pure () else exitFailure

check :: String -> Bool -> IO Bool
check name ok = putStrLn ((if ok then "PASS  " else "FAIL  ") ++ name) >> pure ok

decs :: [Decryptor]
decs =
  [ Decryptor "No Decryptor" 0  0  0 0 0
  , Decryptor "Accelerant"  20  2 10 1 800000
  , Decryptor "Augmentation" (-40) (-2) 2 9 300000
  ]

prod :: Product
prod = Product
  { pTypeId = 100, pName = "Widget II"
  , pBaseProb = 0.34, pBaseRuns = 10, pUnitsPerRun = 1
  , pDatacoreCost = 500000, pInventionInstall = 10000
  , pManufInstallPerRun = 5000, pSellPerUnit = 4000000
  , pMaterials = [Mat 100 50.0, Mat 1 1000000.0]
  , pMatExtraMult = 1.0, pEncryption = 5, pSci1 = 5, pSci2 = 5
  }

-- products × decryptors fan-out count
testCount :: IO Bool
testCount = check "count = products*decryptors"
  (length (optimize [] [prod, prod { pTypeId = 101 }] decs) == 6)

-- ranks are 1..n contiguous and sorted by score desc
testRankOrder :: IO Bool
testRankOrder =
  let rs = optimize [] [prod] decs
      ranks = map cRank rs
      scores = map cScore rs
  in check "ranks 1..n, score desc"
       (ranks == [1, 2, 3] && and (zipWith (>=) scores (drop 1 scores)))

-- probability with all-V skills: 0.34 × (1 + 10/30 + 5/40) × 1.2 (Accelerant)
testEconomics :: IO Bool
testEconomics =
  let c = evalCand prod (decs !! 1)
      expected = 0.34 * (1 + 10/30 + 5/40) * 1.2
  in check "probability formula" (abs (cProbability c - expected) < 1e-9
                                  && cBpcRuns c == 11 && cBpcMe c == 4 && cBpcTe c == 14)

-- no decryptor: base ME2/TE4, runs unchanged, prob = base × skill factor
testNoDecryptorProb :: IO Bool
testNoDecryptorProb =
  let c = evalCand prod (head decs)
  in check "no-decryptor base" (cBpcMe c == 2 && cBpcTe c == 4 && cBpcRuns c == 10)
