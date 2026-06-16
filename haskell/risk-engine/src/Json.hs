module Json
  ( JValue(..)
  , parse, render
  -- accessors
  , field, fieldMaybe
  , asObj, asArr, asString, asDouble, asInt, asBool, asRational, asIntMaybe
  ) where

import Data.Char (chr, isDigit, isHexDigit, isSpace, ord)
import Data.List (foldl', intercalate)
import Data.Ratio ((%))
import Numeric (showHex)

data JValue
  = JNull
  | JBool Bool
  | JInt Integer
  | JNum Rational
  | JStr String
  | JArr [JValue]
  | JObj [(String, JValue)]
  deriving (Eq, Show)

-- parse

parse :: String -> Either String JValue
parse s = do
  (v, rest) <- pValue (skipWs s)
  if all isSpace rest then Right v else Left ("trailing input: " ++ take 20 rest)

type P a = String -> Either String (a, String)

skipWs :: String -> String
skipWs = dropWhile isSpace

pValue :: P JValue
pValue s = case s of
  ('{' : r) -> pObject (skipWs r)
  ('[' : r) -> pArray (skipWs r)
  ('"' : r) -> do (str, r') <- pString r; Right (JStr str, r')
  ('t' : r) -> lit r "rue" (JBool True)
  ('f' : r) -> lit r "alse" (JBool False)
  ('n' : r) -> lit r "ull" JNull
  _         -> pNumber s
  where
    lit r pat v
      | take (length pat) r == pat = Right (v, drop (length pat) r)
      | otherwise = Left ("bad literal near " ++ take 10 s)

pObject :: P JValue
pObject ('}' : r) = Right (JObj [], r)
pObject s = go [] s
  where
    go acc s1 = do
      (k, s2) <- case skipWs s1 of
        ('"' : r) -> pString r
        _         -> Left "expected string key"
      s3 <- case skipWs s2 of
        (':' : r) -> Right (skipWs r)
        _         -> Left "expected ':'"
      (v, s4) <- pValue s3
      case skipWs s4 of
        (',' : r) -> go ((k, v) : acc) (skipWs r)
        ('}' : r) -> Right (JObj (reverse ((k, v) : acc)), r)
        _         -> Left "expected ',' or '}'"

pArray :: P JValue
pArray (']' : r) = Right (JArr [], r)
pArray s = go [] s
  where
    go acc s1 = do
      (v, s2) <- pValue s1
      case skipWs s2 of
        (',' : r) -> go (v : acc) (skipWs r)
        (']' : r) -> Right (JArr (reverse (v : acc)), r)
        _         -> Left "expected ',' or ']'"

pString :: P String
pString = go []
  where
    go acc ('"' : r) = Right (reverse acc, r)
    go acc ('\\' : c : r) = case c of
      '"'  -> go ('"' : acc) r
      '\\' -> go ('\\' : acc) r
      '/'  -> go ('/' : acc) r
      'n'  -> go ('\n' : acc) r
      't'  -> go ('\t' : acc) r
      'r'  -> go ('\r' : acc) r
      'b'  -> go ('\b' : acc) r
      'f'  -> go ('\f' : acc) r
      'u'  -> case splitAt 4 r of
        (h, r') | length h == 4 && all isHexDigit h -> go (chr (hexv h) : acc) r'
        _ -> Left "bad \\u escape"
      _    -> Left ("bad escape \\" ++ [c])
    go acc (c : r) = go (c : acc) r
    go _ [] = Left "unterminated string"
    hexv = foldl' (\a d -> a * 16 + digit d) 0
    digit d
      | d >= '0' && d <= '9' = ord d - ord '0'
      | d >= 'a' && d <= 'f' = ord d - ord 'a' + 10
      | otherwise            = ord d - ord 'A' + 10

pNumber :: P JValue
pNumber s =
  let (tok, rest) = span (`elem` "+-.eE0123456789") s
  in if null tok
       then Left ("unexpected " ++ take 10 s)
       else if any (`elem` ".eE") tok
              then case decRational tok of
                     Just r  -> Right (JNum r, rest)
                     Nothing -> Left ("bad number " ++ tok)
              else case reads tok :: [(Integer, String)] of
                     [(i, "")] -> Right (JInt i, rest)
                     _         -> Left ("bad integer " ++ tok)

-- | Parse a decimal/scientific token to an *exact* rational (e.g. "0.958" -> 479/500).
decRational :: String -> Maybe Rational
decRational s0 =
  let (sgn, s1) = case s0 of
        ('-' : r) -> (-1, r)
        ('+' : r) -> (1, r)
        _         -> (1, s0)
      (mant, ePart) = break (`elem` "eE") s1
      (ip, fp0) = break (== '.') mant
      fp = drop 1 fp0
      digits = ip ++ fp
      me = case ePart of
        []      -> Just 0
        (_ : d) -> readExp d
  in case me of
       Just e | not (null digits) && all isDigit digits ->
         let n = read digits :: Integer
             scale = length fp
             base = n % (10 ^ scale)
             scaled = if e >= 0 then base * (10 ^ e) else base / (10 ^ negate e)
         in Just (fromInteger sgn * scaled)
       _ -> Nothing
  where
    readExp d = case d of
      ('+' : ds) -> readI ds
      _          -> readI d
    readI ds = case reads ds :: [(Integer, String)] of
      [(v, "")] -> Just v
      _         -> Nothing

-- render

render :: JValue -> String
render JNull       = "null"
render (JBool b)   = if b then "true" else "false"
render (JInt i)    = show i
render (JNum r)    = let d = fromRational r :: Double
                     in if isNaN d || isInfinite d then "0" else show d
render (JStr s)    = renderStr s
render (JArr xs)   = "[" ++ intercalate "," (map render xs) ++ "]"
render (JObj kvs)  = "{" ++ intercalate "," (map kv kvs) ++ "}"
  where kv (k, v) = renderStr k ++ ":" ++ render v

renderStr :: String -> String
renderStr s = '"' : concatMap esc s ++ "\""
  where
    esc c = case c of
      '"'  -> "\\\""
      '\\' -> "\\\\"
      '\n' -> "\\n"
      '\t' -> "\\t"
      '\r' -> "\\r"
      _ | ord c < 0x20 -> "\\u" ++ pad4 (showHex (ord c) "")
        | otherwise    -> [c]
    pad4 x = replicate (4 - length x) '0' ++ x

-- accessor

asObj :: JValue -> Either String [(String, JValue)]
asObj (JObj o) = Right o
asObj v        = Left ("expected object, got " ++ tag v)

asArr :: JValue -> Either String [JValue]
asArr (JArr a) = Right a
asArr v        = Left ("expected array, got " ++ tag v)

asString :: JValue -> Either String String
asString (JStr s) = Right s
asString v        = Left ("expected string, got " ++ tag v)

asRational :: JValue -> Either String Rational
asRational (JNum r) = Right r
asRational (JInt i) = Right (fromInteger i)
asRational v        = Left ("expected number, got " ++ tag v)

asDouble :: JValue -> Either String Double
asDouble v = fromRational <$> asRational v

asInt :: JValue -> Either String Int
asInt (JInt i) = Right (fromInteger i)
asInt (JNum r) = Right (round r)
asInt v        = Left ("expected int, got " ++ tag v)

asBool :: JValue -> Either String Bool
asBool (JBool b) = Right b
asBool v         = Left ("expected bool, got " ++ tag v)

-- | Look a key up in an object value (errors if missing).
field :: String -> JValue -> Either String JValue
field k v = do
  o <- asObj v
  case lookup k o of
    Just x  -> Right x
    Nothing -> Left ("missing key '" ++ k ++ "'")

-- | Look a key up; absent or JSON null -> Nothing.
fieldMaybe :: String -> JValue -> Either String (Maybe JValue)
fieldMaybe k v = do
  o <- asObj v
  Right $ case lookup k o of
    Just JNull -> Nothing
    other      -> other

asIntMaybe :: Maybe JValue -> Either String (Maybe Int)
asIntMaybe Nothing  = Right Nothing
asIntMaybe (Just x) = Just <$> asInt x

tag :: JValue -> String
tag JNull     = "null"
tag (JBool _) = "bool"
tag (JInt _)  = "int"
tag (JNum _)  = "number"
tag (JStr _)  = "string"
tag (JArr _)  = "array"
tag (JObj _)  = "object"
