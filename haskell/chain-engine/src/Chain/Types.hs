module Chain.Types
  ( RecipeLocation(..)
  , Recipe(..)
  , Node(..)
  , ChainRequest(..)
  , NodeDecision(..)
  , JobInput(..)
  , PlannedJob(..)
  , ShoppingLine(..)
  , ChainPlan(..)
  , decodeRequest
  , encodePlan
  ) where

import qualified Data.Map.Strict as M
import Data.Ratio (denominator, numerator)
import Json

-- request

data RecipeLocation = RecipeLocation
  { locPlaceId        :: !Int
  , locPlaceName      :: !String
  , locSlotKind       :: !String
  , locMeMult         :: !Rational
  , locTeMult         :: !Rational
  , locSci            :: !Rational
  , locTax            :: !Rational
  , locScc            :: !Rational
  , locStructDiscount :: !Rational
  , locEivUnit        :: !Rational
  , locBpcUnit        :: !Rational
  }

data Recipe = Recipe
  { rcActivity  :: !Int
  , rcBlueprint :: !Int
  , rcQtyPerRun :: !Int
  , rcBaseTime  :: !Int
  , rcMaxRuns   :: !(Maybe Int)
  , rcInputs    :: ![(Int, Int)]
  , rcLocations :: ![RecipeLocation]
  }

data Node = Node
  { ndTypeId   :: !Int
  , ndName     :: !String
  , ndBuyPrice :: !(Maybe Rational)
  , ndRecipes  :: ![Recipe]
  }

data ChainRequest = ChainRequest
  { reqTarget :: !Int
  , reqQty    :: !Int
  , reqNodes  :: !(M.Map Int Node)
  }

-- response

data NodeDecision = NodeDecision
  { dTypeId      :: !Int
  , dName        :: !String
  , dDecision    :: !String
  , dUnitCost    :: !(Maybe Rational)
  , dUnitBuy     :: !(Maybe Rational)
  , dUnitMake    :: !(Maybe Rational)
  , dRecipeIndex :: !(Maybe Int)
  , dPlaceId     :: !(Maybe Int)
  , dSaved       :: !Rational
  , dActivity    :: !(Maybe Int)
  }

data JobInput = JobInput
  { jiType   :: !Int
  , jiQty    :: !Int
  , jiUnit   :: !Rational
  , jiIsMake :: !Bool
  }

data PlannedJob = PlannedJob
  { pjType        :: !Int
  , pjName        :: !String
  , pjActivity    :: !Int
  , pjPlaceId     :: !Int
  , pjPlaceName   :: !String
  , pjSlotKind    :: !String
  , pjRuns        :: !Int
  , pjQtyOut      :: !Int
  , pjTime        :: !Int
  , pjInstall     :: !Rational
  , pjBpc         :: !Rational
  , pjLeafMat     :: !Rational
  , pjInputs      :: ![JobInput]
  , pjBuyFallback :: !(Maybe Rational)
  , pjBounceable  :: !Bool
  }

data ShoppingLine = ShoppingLine
  { slType  :: !Int
  , slName  :: !String
  , slQty   :: !Int
  , slUnit  :: !Rational
  , slTotal :: !Rational
  }

data ChainPlan = ChainPlan
  { plTarget    :: !Int
  , plQty       :: !Int
  , plUnit      :: !(Maybe Rational)
  , plTotal     :: !Rational
  , plDecisions :: ![(Int, NodeDecision)]
  , plJobs      :: ![PlannedJob]
  , plShopping  :: ![ShoppingLine]
  }

-- decode request

decodeRequest :: JValue -> Either String ChainRequest
decodeRequest v = do
  target <- field "target_type_id" v >>= asInt
  qty    <- field "target_qty" v >>= asInt
  nodesO <- field "nodes" v >>= asObj
  nodes  <- mapM (\(_, nv) -> decNode nv) nodesO
  Right (ChainRequest target qty (M.fromList [(ndTypeId n, n) | n <- nodes]))

decNode :: JValue -> Either String Node
decNode v = do
  tid   <- field "type_id" v >>= asInt
  name  <- field "name" v >>= asString
  buy   <- optRat "buy_price" v
  recsV <- field "recipes" v >>= asArr
  recs  <- mapM decRecipe recsV
  Right (Node tid name buy recs)

decRecipe :: JValue -> Either String Recipe
decRecipe v = do
  act   <- field "activity" v >>= asInt
  bp    <- field "blueprint_type_id" v >>= asInt
  qpr   <- field "qty_per_run" v >>= asInt
  bt    <- field "base_time" v >>= asInt
  mr    <- fieldMaybe "max_runs" v >>= asIntMaybe
  insV  <- field "inputs" v >>= asArr
  ins   <- mapM decPair insV
  locsV <- field "locations" v >>= asArr
  locs  <- mapM decLoc locsV
  Right (Recipe act bp qpr bt mr ins locs)

decPair :: JValue -> Either String (Int, Int)
decPair v = do
  xs <- asArr v
  case xs of
    [a, b] -> (,) <$> asInt a <*> asInt b
    _      -> Left "input must be [type_id, qty]"

decLoc :: JValue -> Either String RecipeLocation
decLoc v = RecipeLocation
  <$> (field "place_id" v >>= asInt)
  <*> (field "place_name" v >>= asString)
  <*> (field "slot_kind" v >>= asString)
  <*> num "me_mult" <*> num "te_mult" <*> num "sci" <*> num "tax"
  <*> num "scc" <*> num "struct_discount" <*> num "eiv_unit" <*> num "bpc_unit"
  where num k = field k v >>= asRational

optRat :: String -> JValue -> Either String (Maybe Rational)
optRat k v = fieldMaybe k v >>= traverse asRational

-- encode plan

encodePlan :: ChainPlan -> JValue
encodePlan p = JObj
  [ ("target_type_id", jInt (plTarget p))
  , ("target_qty", jInt (plQty p))
  , ("unit_cost", jMaybeRat (plUnit p))
  , ("total_cost", jRat (plTotal p))
  , ("decisions", JObj [(show t, encDecision d) | (t, d) <- plDecisions p])
  , ("jobs", JArr (map encJob (plJobs p)))
  , ("shopping_list", JArr (map encShop (plShopping p)))
  ]

encDecision :: NodeDecision -> JValue
encDecision d = JObj
  [ ("type_id", jInt (dTypeId d))
  , ("name", JStr (dName d))
  , ("decision", JStr (dDecision d))
  , ("unit_cost", jMaybeRat (dUnitCost d))
  , ("unit_buy", jMaybeRat (dUnitBuy d))
  , ("unit_make", jMaybeRat (dUnitMake d))
  , ("recipe_index", jMaybeInt (dRecipeIndex d))
  , ("place_id", jMaybeInt (dPlaceId d))
  , ("saved_per_unit", jRat (dSaved d))
  , ("activity", jMaybeInt (dActivity d))
  ]

encJob :: PlannedJob -> JValue
encJob j = JObj
  [ ("type_id", jInt (pjType j))
  , ("name", JStr (pjName j))
  , ("activity", jInt (pjActivity j))
  , ("place_id", jInt (pjPlaceId j))
  , ("place_name", JStr (pjPlaceName j))
  , ("slot_kind", JStr (pjSlotKind j))
  , ("runs", jInt (pjRuns j))
  , ("qty_out", jInt (pjQtyOut j))
  , ("time_s", jInt (pjTime j))
  , ("install_cost", jRat (pjInstall j))
  , ("bpc_cost", jRat (pjBpc j))
  , ("leaf_material_cost", jRat (pjLeafMat j))
  , ("inputs", JArr (map encInput (pjInputs j)))
  , ("buy_fallback_unit", jMaybeRat (pjBuyFallback j))
  , ("bounceable", JBool (pjBounceable j))
  , ("make_cost", jRat (pjInstall j + pjBpc j + pjLeafMat j))
  , ("buy_fallback_total", jMaybeRat (fmap (* fromIntegral (pjQtyOut j)) (pjBuyFallback j)))
  ]

encInput :: JobInput -> JValue
encInput i = JObj
  [ ("type_id", jInt (jiType i))
  , ("qty", jInt (jiQty i))
  , ("unit_cost", jRat (jiUnit i))
  , ("is_make", JBool (jiIsMake i))
  ]

encShop :: ShoppingLine -> JValue
encShop s = JObj
  [ ("type_id", jInt (slType s))
  , ("name", JStr (slName s))
  , ("qty", jInt (slQty s))
  , ("unit", jRat (slUnit s))
  , ("total", jRat (slTotal s))
  ]

jInt :: Int -> JValue
jInt = JInt . fromIntegral

-- | Carry an exact rational as [numerator, denominator].
jRat :: Rational -> JValue
jRat r = JArr [JInt (numerator r), JInt (denominator r)]

jMaybeRat :: Maybe Rational -> JValue
jMaybeRat = maybe JNull jRat

jMaybeInt :: Maybe Int -> JValue
jMaybeInt = maybe JNull jInt
