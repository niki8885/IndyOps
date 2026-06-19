import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from './store/AuthContext'
import PrivateRoute from './components/PrivateRoute'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import Layout from './pages/Layout'
import InventoryPage from './pages/InventoryPage'
import ManufacturingPage from './pages/ManufacturingPage'
import OreAcquisitionPage from './pages/OreAcquisitionPage'
import OrganisationsHub from './pages/OrganisationsHub'
import PersonalFilePage from './pages/PersonalFilePage'
import MarketHub from './pages/MarketHub'
import AgendaPage from './pages/AgendaPage'

// Analysis pulls in Plotly (~4MB) — load it on demand so it can never block the
// rest of the app and stays out of the main bundle. (The Market Browser is lazy
// the same way, internally, inside MarketHub.)
const AnalysisPage = lazy(() => import('./pages/AnalysisPage'))
// The Encyclopedia carries 2 long articles + inline SVG figures — load on demand.
const EncyclopediaPage = lazy(() => import('./pages/EncyclopediaPage'))

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login"    element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route element={<PrivateRoute />}>
            <Route element={<Layout />}>
              <Route index element={<Navigate to="/agenda" replace />} />
              <Route path="/agenda"        element={<AgendaPage />} />
              <Route path="/manufacturing" element={<ManufacturingPage />} />
              <Route path="/ore"           element={<OreAcquisitionPage />} />
              <Route path="/inventory"     element={<InventoryPage />} />
              <Route path="/market"        element={<MarketHub />} />
              <Route path="/analysis"      element={
                <Suspense fallback={<div className="empty-state">Loading analytics…</div>}>
                  <AnalysisPage />
                </Suspense>
              } />
              <Route path="/organisations" element={<OrganisationsHub />} />
              <Route path="/personal"      element={<PersonalFilePage />} />
              <Route path="/encyclopedia"  element={
                <Suspense fallback={<div className="empty-state">Loading encyclopedia…</div>}>
                  <EncyclopediaPage />
                </Suspense>
              } />
              {/* legacy redirects */}
              <Route path="/trade"      element={<Navigate to="/market" replace />} />
              <Route path="/facilities" element={<Navigate to="/organisations" replace />} />
              <Route path="/projects"   element={<Navigate to="/organisations" replace />} />
              <Route path="/orgs"       element={<Navigate to="/organisations" replace />} />
            </Route>
          </Route>
          <Route path="*" element={<Navigate to="/agenda" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
