module Main (main) where

import System.Exit (exitFailure)
import System.IO

import Chain.Planner (decodePlannerRequest, encodePlannerResponse, runPlanner)
import Json (parse, render)

-- Reaction Planner native engine: a pure stdin→stdout JSON filter. Reads a batch of
-- candidate products (each with its from-scratch ChainRequest and an optional
-- bought-reactions variant) + the slot counts, ranks them by ROI, and emits per-candidate
-- cost / income-per-hour / scratch-vs-bought metrics. Oracle: app.services.reaction_planner.
main :: IO ()
main = do
  hSetEncoding stdin utf8
  hSetEncoding stdout utf8
  hSetEncoding stderr utf8
  input <- getContents
  case parse input >>= decodePlannerRequest of
    Left err -> do
      hPutStrLn stderr ("reaction-planner: " ++ err)
      exitFailure
    Right req ->
      putStr (render (encodePlannerResponse (runPlanner req)))
