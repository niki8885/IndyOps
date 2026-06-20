module Main (main) where

import System.Exit (exitFailure)
import System.IO

import Invention.Optimize (optimize)
import Invention.Types (decodeRequest, encodeRanked, reqProducts, reqDecryptors, reqWeights)
import Json (parse, render)

main :: IO ()
main = do
  hSetEncoding stdin utf8
  hSetEncoding stdout utf8
  hSetEncoding stderr utf8
  input <- getContents
  case parse input >>= decodeRequest of
    Left err -> do
      hPutStrLn stderr ("invention-optimizer: " ++ err)
      exitFailure
    Right req ->
      putStr (render (encodeRanked
        (optimize (reqWeights req) (reqProducts req) (reqDecryptors req))))
