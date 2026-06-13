import { createContext, useContext, useState, useCallback } from 'react'
import { post } from '../api/client'

const Ctx = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    try { return JSON.parse(localStorage.getItem('user')) } catch { return null }
  })

  const login = useCallback(async (username, password) => {
    const data = await post('/login', { username, password })
    localStorage.setItem('token', data.access_token)
    localStorage.setItem('user', JSON.stringify({ id: data.user_id, username: data.username }))
    setUser({ id: data.user_id, username: data.username })
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    setUser(null)
  }, [])

  return <Ctx.Provider value={{ user, login, logout }}>{children}</Ctx.Provider>
}

export const useAuth = () => useContext(Ctx)
