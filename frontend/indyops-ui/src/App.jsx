import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from './store/AuthContext'
import PrivateRoute from './components/PrivateRoute'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import Layout from './pages/Layout'
import InventoryPage from './pages/InventoryPage'
import ManufacturingPage from './pages/ManufacturingPage'
import MarketPage from './pages/MarketPage'
import AnalysisPage from './pages/AnalysisPage'
import OrganisationsHub from './pages/OrganisationsHub'

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
              <Route path="/inventory"     element={<InventoryPage />} />
              <Route path="/market"        element={<MarketPage />} />
              <Route path="/analysis"      element={<AnalysisPage />} />
              <Route path="/organisations" element={<OrganisationsHub />} />
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
