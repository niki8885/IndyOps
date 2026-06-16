module Chain.Solver (solveChain) where
import Control.Monad (foldM)
import Control.Monad.State.Strict (State, execState, get, modify)
import Data.List (foldl', minimumBy, sortBy)
import qualified Data.Map.Strict as M
import Data.Maybe (fromMaybe, isJust, isNothing, maybeToList)
import Data.Ord (Down (..), comparing)
import qualified Data.Set as S

import Chain.Types

solveChain :: ChainRequest -> ChainPlan
solveChain req =
  let decs = decide req
      (jobs, shopping, total) = plan req decs
      rootUnit = M.lookup (reqTarget req) decs >>= dUnitCost
  in ChainPlan (reqTarget req) (reqQty req) rootUnit total (M.toList decs) jobs shopping

-- exact formulas (mirror chain._adj_* / install_per_unit)

installPerUnit :: RecipeLocation -> Rational
installPerUnit loc =
  locEivUnit loc * (locSci loc * (1 - locStructDiscount loc) + locTax loc + locScc loc)

adjQty :: Int -> Int -> Rational -> Int
adjQty base runs meMult = max runs (fromInteger (ceiling (fromIntegral (base * runs) * meMult)))

adjTime :: Int -> Int -> Rational -> Int
adjTime base runs teMult = fromInteger (ceiling (fromIntegral (base * runs) * teMult))

-- phase 1: decide

type Memo = M.Map Int NodeDecision

decide :: ChainRequest -> Memo
decide req = execState (goDecide (reqNodes req) S.empty (reqTarget req)) M.empty

goDecide :: M.Map Int Node -> S.Set Int -> Int -> State Memo NodeDecision
goDecide nodes stack tid = do
  m <- get
  case M.lookup tid m of
    Just d -> pure d
    Nothing -> case M.lookup tid nodes of
      Nothing ->
        ins (NodeDecision tid (show tid) "unobtainable" Nothing Nothing Nothing Nothing Nothing 0)
      Just node -> do
        best <- if S.member tid stack
                  then pure Nothing
                  else exploreRecipes nodes (S.insert tid stack) node
        ins (decideFrom node best)
  where
    ins d = modify (M.insert tid d) >> pure d

-- best = (make unit cost, recipe index, place id) for the cheapest (recipe, location)
exploreRecipes
  :: M.Map Int Node -> S.Set Int -> Node -> State Memo (Maybe (Rational, Int, Int))
exploreRecipes nodes stack node = foldM step Nothing (zip [0 ..] (ndRecipes node))
  where
    step best (ri, recipe) = do
      childUnits <- mapM (\(mtid, _) -> dUnitCost <$> goDecide nodes stack mtid) (rcInputs recipe)
      if any isNothing childUnits
        then pure best
        else
          let us = map (fromMaybe 0) childUnits
          in pure (foldl' (locStep ri recipe us) best (rcLocations recipe))

    locStep ri recipe us best loc =
      let mat = foldl' (+) 0
                  (zipWith (\u (_, mq) -> (u * fromIntegral mq) * locMeMult loc) us (rcInputs recipe))
                / fromIntegral (rcQtyPerRun recipe)
          makeUnit = mat + installPerUnit loc + locBpcUnit loc
      in case best of
           Just (bc, _, _) | makeUnit >= bc -> best   -- strictly-less replaces; first wins on tie
           _ -> Just (makeUnit, ri, locPlaceId loc)

decideFrom :: Node -> Maybe (Rational, Int, Int) -> NodeDecision
decideFrom node best =
  let unitBuy = ndBuyPrice node
      unitMake = fmap (\(c, _, _) -> c) best
      choices = [("buy", b) | b <- maybeToList unitBuy]
             ++ [("make", mk) | mk <- maybeToList unitMake]
  in case choices of
       [] -> NodeDecision tid name "unobtainable" Nothing unitBuy unitMake Nothing Nothing 0
       _  ->
         let (kind, unit) = minimumBy (comparing snd) choices   -- first min: buy beats make on tie
             saved = case (unitBuy, unitMake) of
               (Just b, Just mk) -> b - mk
               _                 -> 0
             (ri, pid)
               | kind == "make" = case best of
                   Just (_, r, p) -> (Just r, Just p)
                   Nothing        -> (Nothing, Nothing)
               | otherwise = (Nothing, Nothing)
         in NodeDecision tid name kind (Just unit) unitBuy unitMake ri pid saved
  where
    tid = ndTypeId node
    name = ndName node

-- phase 2: plan

plan :: ChainRequest -> Memo -> ([PlannedJob], [ShoppingLine], Rational)
plan req decs = (jobs, shopping, total)
  where
    nodes = reqNodes req
    target = reqTarget req
    order = topoMakeOrder nodes decs target

    seed = (M.singleton target (reqQty req), [], M.empty)
    (_, jobs, shopQty0) = foldl' stepNode seed order

    shopQty
      | maybe "" dDecision (M.lookup target decs) /= "make" =
          M.insertWith (+) target (reqQty req) shopQty0
      | otherwise = shopQty0

    shopping0 =
      [ ShoppingLine t (nm t) q unit (fromIntegral q * unit)
      | (t, q) <- M.toList shopQty
      , let unit = fromMaybe 0 (M.lookup t nodes >>= ndBuyPrice)
      ]
    shopTotal = foldl' (\a s -> a + slTotal s) 0 shopping0
    jobsConv = foldl' (\a j -> a + pjInstall j + pjBpc j) 0 jobs
    total = shopTotal + jobsConv
    shopping = sortBy (comparing (Down . slTotal)) shopping0

    nm t = maybe (show t) ndName (M.lookup t nodes)

    stepNode acc@(demand, jacc, shop) tid =
      let need = fromMaybe 0 (M.lookup tid demand)
      in if need <= 0
           then acc
           else
             let node = nodes M.! tid
                 dec = decs M.! tid
                 recipe = ndRecipes node !! fromMaybe 0 (dRecipeIndex dec)
                 loc = chooseLoc recipe (dPlaceId dec)
                 totalRuns = ceiling (fromIntegral need / fromIntegral (rcQtyPerRun recipe) :: Rational)
                 cap = fromMaybe totalRuns (rcMaxRuns recipe)
                 (newJobs, consumed) = foldl' (mkJob node recipe loc) ([], M.empty) (splitRuns cap totalRuns)
                 (demand', shop') = M.foldlWithKey' (pushConsume dec) (demand, shop) consumed
             in (demand', jacc ++ newJobs, shop')

    pushConsume _ (dm, sh) mtid cq =
      if dDecision (decs M.! mtid) == "make"
        then (M.insertWith (+) mtid cq dm, sh)
        else (dm, M.insertWith (+) mtid cq sh)

    mkJob node recipe loc (js, cons) r =
      let qtyOut = r * rcQtyPerRun recipe
          eivJob = locEivUnit loc * fromIntegral qtyOut
          install = eivJob * (locSci loc * (1 - locStructDiscount loc) + locTax loc + locScc loc)
          bpc = locBpcUnit loc * fromIntegral qtyOut
          timeS = adjTime (rcBaseTime recipe) r (locTeMult loc)
          (insRev, leafMat, cons') = foldl' (mkInput loc r) ([], 0, cons) (rcInputs recipe)
          inputs = reverse insRev
          bounceable = isJust (ndBuyPrice node) && all (not . jiIsMake) inputs
          job = PlannedJob
            { pjType = ndTypeId node, pjName = ndName node, pjActivity = rcActivity recipe
            , pjPlaceId = locPlaceId loc, pjPlaceName = locPlaceName loc, pjSlotKind = locSlotKind loc
            , pjRuns = r, pjQtyOut = qtyOut, pjTime = timeS
            , pjInstall = install, pjBpc = bpc, pjLeafMat = leafMat
            , pjInputs = inputs, pjBuyFallback = ndBuyPrice node, pjBounceable = bounceable
            }
      in (js ++ [job], cons')

    mkInput loc r (insRev, leaf, cons) (mtid, mbase) =
      let cq = adjQty mbase r (locMeMult loc)
          childDec = decs M.! mtid
          isMk = dDecision childDec == "make"
          unit = fromMaybe 0 (dUnitCost childDec)
          leaf' = if isMk then leaf else leaf + fromIntegral cq * unit
          ji = JobInput mtid cq unit isMk
      in (ji : insRev, leaf', M.insertWith (+) mtid cq cons)

chooseLoc :: Recipe -> Maybe Int -> RecipeLocation
chooseLoc recipe mpid =
  case filter (\l -> Just (locPlaceId l) == mpid) (rcLocations recipe) of
    (l : _) -> l
    []      -> head (rcLocations recipe)

splitRuns :: Int -> Int -> [Int]
splitRuns cap total
  | total <= 0 = []
  | otherwise  = let r = min cap total in r : splitRuns cap (total - r)

-- Reverse post-order DFS: a valid topological sort even when a node is shared by
-- several parents, so 'plan' has the full demand for a node before it is consumed.
-- A pre-order ('ordered ++ [t]' before visiting children) drops every parent after
-- the first for a shared node, undercounting its inputs and the total cost.
topoMakeOrder :: M.Map Int Node -> Memo -> Int -> [Int]
topoMakeOrder nodes decs target = reverse acc
  where
    isMake t = maybe False ((== "make") . dDecision) (M.lookup t decs)
    chosen t = ndRecipes (nodes M.! t) !! fromMaybe 0 (dRecipeIndex (decs M.! t))
    visit st@(seen, ordered) t
      | S.member t seen = st
      | not (isMake t) = st
      | otherwise =
          let (seen', ordered') =
                foldl' (\s (mt, _) -> visit s mt) (S.insert t seen, ordered) (rcInputs (chosen t))
          in (seen', ordered' ++ [t])   -- post-order: append after all children
    (seen1, acc1) = visit (S.empty, []) target
    makeIds = [t | (t, d) <- M.toList decs, dDecision d == "make"]
    (_, acc) = foldl' visit (seen1, acc1) makeIds
