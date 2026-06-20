module Invention.Types
  ( Decryptor(..)
  , Mat(..)
  , Product(..)
  , Request(..)
  , Cand(..)
  , decodeRequest
  , encodeRanked
  ) where

import Json

-- request -------------------------------------------------------------------

data Decryptor = Decryptor
  { dName    :: !String
  , dProbMod :: !Double   -- percent: +20 → ×1.20
  , dMeMod   :: !Int
  , dTeMod   :: !Int
  , dRunsMod :: !Int
  , dPrice   :: !Double
  }

data Mat = Mat { mQty :: !Integer, mPrice :: !Double }

data Product = Product
  { pTypeId             :: !Int
  , pName               :: !String
  , pBaseProb           :: !Double
  , pBaseRuns           :: !Int
  , pUnitsPerRun        :: !Int
  , pDatacoreCost       :: !Double
  , pInventionInstall   :: !Double
  , pManufInstallPerRun :: !Double
  , pSellPerUnit        :: !Double
  , pMaterials          :: ![Mat]
  , pMatExtraMult       :: !Double
  , pEncryption         :: !Int
  , pSci1               :: !Int
  , pSci2               :: !Int
  }

data Request = Request
  { reqProducts   :: ![Product]
  , reqDecryptors :: ![Decryptor]
  , reqWeights    :: ![(String, Double)]
  }

-- evaluated candidate (response row) ----------------------------------------

data Cand = Cand
  { cLabel          :: !String
  , cProductTypeId  :: !Int
  , cProductName    :: !String
  , cDecryptor      :: !String
  , cProbability    :: !Double
  , cBpcRuns        :: !Int
  , cBpcMe          :: !Int
  , cBpcTe          :: !Int
  , cCostPerAttempt :: !Double
  , cCostPerBpc     :: !Double
  , cCostPerRun     :: !Double
  , cManufCostPerRun:: !Double
  , cUnitsPerRun    :: !Int
  , cSellPerUnit    :: !Double
  , cCostPerUnit    :: !Double
  , cProfitPerUnit  :: !Double
  , cProfitPerRun   :: !Double
  , cMarginPct      :: !Double
  , cRank           :: !Int
  , cScore          :: !Double
  }

-- decode --------------------------------------------------------------------

decodeRequest :: JValue -> Either String Request
decodeRequest v = do
  prodsV <- field "products" v >>= asArr
  prods  <- mapM decProduct prodsV
  decsV  <- field "decryptors" v >>= asArr
  decs   <- mapM decDecryptor decsV
  wts    <- decWeights v
  Right (Request prods decs wts)

decWeights :: JValue -> Either String [(String, Double)]
decWeights v = do
  mw <- fieldMaybe "weights" v
  case mw of
    Nothing -> Right []
    Just wv -> asObj wv >>= mapM (\(k, x) -> (,) k <$> asDouble x)

decDecryptor :: JValue -> Either String Decryptor
decDecryptor v = Decryptor
  <$> (field "name" v >>= asString)
  <*> (field "prob_mod" v >>= asDouble)
  <*> (field "me_mod" v >>= asInt)
  <*> (field "te_mod" v >>= asInt)
  <*> (field "runs_mod" v >>= asInt)
  <*> (field "price" v >>= asDouble)

decMat :: JValue -> Either String Mat
decMat v = Mat
  <$> (field "qty" v >>= asInteger)
  <*> (field "price" v >>= asDouble)

decProduct :: JValue -> Either String Product
decProduct v = Product
  <$> (field "product_type_id" v >>= asInt)
  <*> (field "product_name" v >>= asString)
  <*> num "base_prob"
  <*> (field "base_runs" v >>= asInt)
  <*> (field "units_per_run" v >>= asInt)
  <*> num "datacore_cost"
  <*> num "invention_install"
  <*> num "manuf_install_per_run"
  <*> num "sell_per_unit"
  <*> (field "materials" v >>= asArr >>= mapM decMat)
  <*> num "mat_extra_mult"
  <*> (field "encryption" v >>= asInt)
  <*> (field "sci1" v >>= asInt)
  <*> (field "sci2" v >>= asInt)
  where num k = field k v >>= asDouble

asInteger :: JValue -> Either String Integer
asInteger x = toInteger <$> asInt x

-- encode --------------------------------------------------------------------

encodeRanked :: [Cand] -> JValue
encodeRanked cs = JObj [("ranked", JArr (map enc cs))]
  where
    enc c = JObj
      [ ("rank",               JInt (fromIntegral (cRank c)))
      , ("score",              JNum (toRational (cScore c)))
      , ("label",              JStr (cLabel c))
      , ("product_type_id",    JInt (fromIntegral (cProductTypeId c)))
      , ("product_name",       JStr (cProductName c))
      , ("decryptor",          JStr (cDecryptor c))
      , ("probability",        JNum (toRational (cProbability c)))
      , ("bpc_runs",           JInt (fromIntegral (cBpcRuns c)))
      , ("bpc_me",             JInt (fromIntegral (cBpcMe c)))
      , ("bpc_te",             JInt (fromIntegral (cBpcTe c)))
      , ("cost_per_attempt",   JNum (toRational (cCostPerAttempt c)))
      , ("cost_per_bpc",       JNum (toRational (cCostPerBpc c)))
      , ("cost_per_run",       JNum (toRational (cCostPerRun c)))
      , ("manuf_cost_per_run", JNum (toRational (cManufCostPerRun c)))
      , ("units_per_run",      JInt (fromIntegral (cUnitsPerRun c)))
      , ("sell_per_unit",      JNum (toRational (cSellPerUnit c)))
      , ("cost_per_unit",      JNum (toRational (cCostPerUnit c)))
      , ("profit_per_unit",    JNum (toRational (cProfitPerUnit c)))
      , ("profit_per_run",     JNum (toRational (cProfitPerRun c)))
      , ("margin_pct",         JNum (toRational (cMarginPct c)))
      ]
