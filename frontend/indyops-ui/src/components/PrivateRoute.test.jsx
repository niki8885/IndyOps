import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

// Control what useAuth() returns per-test.
vi.mock('../store/AuthContext', () => ({
  useAuth: vi.fn(),
}))
import { useAuth } from '../store/AuthContext'

import PrivateRoute from './PrivateRoute'

beforeEach(() => useAuth.mockReset())

// PrivateRoute renders an <Outlet/>, so it must sit inside a routed tree. We
// mount it as a layout route guarding a protected child, with a /login sink.
function renderGuarded() {
  return render(
    <MemoryRouter initialEntries={['/secret']}>
      <Routes>
        <Route element={<PrivateRoute />}>
          <Route path="/secret" element={<div>protected content</div>} />
        </Route>
        <Route path="/login" element={<div>login page</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('PrivateRoute', () => {
  it('redirects to /login when there is no user', () => {
    useAuth.mockReturnValue({ user: null })
    renderGuarded()
    expect(screen.getByText('login page')).toBeInTheDocument()
    expect(screen.queryByText('protected content')).not.toBeInTheDocument()
  })

  it('renders the protected child when a user is logged in', () => {
    useAuth.mockReturnValue({ user: { id: 1, username: 'pilot' } })
    renderGuarded()
    expect(screen.getByText('protected content')).toBeInTheDocument()
    expect(screen.queryByText('login page')).not.toBeInTheDocument()
  })
})
