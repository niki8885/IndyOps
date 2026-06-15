module Main (main) where

import System.Exit (exitFailure)
import System.IO

import Chain.Solver (solveChain)
import Chain.Types (decodeRequest, encodePlan)
import Json (parse, render)

main :: IO ()
main = do
  hSetEncoding stdin utf8
  hSetEncoding stdout utf8
  hSetEncoding stderr utf8
  input <- getContents
  case parse input >>= decodeRequest of
    Left err -> do
      hPutStrLn stderr ("chain-engine: " ++ err)
      exitFailure
    Right req ->
      putStr (render (encodePlan (solveChain req)))
