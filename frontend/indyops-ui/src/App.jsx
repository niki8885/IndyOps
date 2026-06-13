import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from './store/AuthContext'
import PrivateRoute from './components/PrivateRoute'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import Layout from './pages/Layout'
import InventoryPage from './pages/InventoryPage'
import FacilitiesPage from './pages/FacilitiesPage'
import ProjectsPage from './pages/ProjectsPage'
import OrgsPage from './pages/OrgsPage'
import ManufacturingPage from './pages/ManufacturingPage'

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
              <Route path="/facilities"    element={<FacilitiesPage />} />
              <Route path="/projects"      element={<ProjectsPage />} />
              <Route path="/orgs"          element={<OrgsPage />} />
            </Route>
          </Route>
          <Route path="*" element={<Navigate to="/manufacturing" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
