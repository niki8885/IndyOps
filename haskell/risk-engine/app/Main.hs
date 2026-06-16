module Main (main) where

import System.Exit (exitFailure)
import System.IO

import Risk.Score (rankStrategies)
import Risk.Types (decodeRequest, encodeRanked, rrStrategies, rrWeights)
import Json (parse, render)

main :: IO ()
main = do
  hSetEncoding stdin utf8
  hSetEncoding stdout utf8
  hSetEncoding stderr utf8
  input <- getContents
  case parse input >>= decodeRequest of
    Left err -> do
      hPutStrLn stderr ("risk-engine: " ++ err)
      exitFailure
    Right req ->
      putStr (render (encodeRanked (rankStrategies (rrWeights req) (rrStrategies req))))
