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

// Analysis and Market both pull in Plotly (~4MB) — load them on demand so they
// can never block the rest of the app and stay out of the main bundle.
const AnalysisPage = lazy(() => import('./pages/AnalysisPage'))
const MarketPage   = lazy(() => import('./pages/MarketPage'))

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login"    element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route element={<PrivateRoute />}>
            <Route element={<Layout />}>
              <Route index element={<Navigate to="/manufacturing" replace />} />
              <Route path="/manufacturing" element={<ManufacturingPage />} />
              <Route path="/ore"           element={<OreAcquisitionPage />} />
              <Route path="/inventory"     element={<InventoryPage />} />
              <Route path="/market"        element={
                <Suspense fallback={<div className="empty-state">Loading market…</div>}>
                  <MarketPage />
                </Suspense>
              } />
              <Route path="/analysis"      element={
                <Suspense fallback={<div className="empty-state">Loading analytics…</div>}>
                  <AnalysisPage />
                </Suspense>
              } />
              <Route path="/organisations" element={<OrganisationsHub />} />
              <Route path="/personal"      element={<PersonalFilePage />} />
              {/* legacy redirects */}
              <Route path="/facilities" element={<Navigate to="/organisations" replace />} />
              <Route path="/projects"   element={<Navigate to="/organisations" replace />} />
              <Route path="/orgs"       element={<Navigate to="/organisations" replace />} />
            </Route>
          </Route>
          <Route path="*" element={<Navigate to="/manufacturing" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
