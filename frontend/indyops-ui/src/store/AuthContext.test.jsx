import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { AuthProvider, useAuth } from './AuthContext'
import { post } from '../api/client'

vi.mock('../api/client', () => ({ post: vi.fn() }))

const wrapper = ({ children }) => <AuthProvider>{children}</AuthProvider>

beforeEach(() => {
  localStorage.clear()
  post.mockReset()
})

describe('AuthProvider / useAuth', () => {
  it('starts with user null when localStorage is empty', () => {
    const { result } = renderHook(() => useAuth(), { wrapper })
    expect(result.current.user).toBeNull()
  })

  it('initialises user from localStorage "user"', () => {
    localStorage.setItem('user', JSON.stringify({ id: 7, username: 'pilot' }))
    const { result } = renderHook(() => useAuth(), { wrapper })
    expect(result.current.user).toEqual({ id: 7, username: 'pilot' })
  })

  it('falls back to null when localStorage "user" is invalid JSON', () => {
    localStorage.setItem('user', 'not-json{')
    const { result } = renderHook(() => useAuth(), { wrapper })
    expect(result.current.user).toBeNull()
  })

  it('login() stores token + user and updates state', async () => {
    post.mockResolvedValue({ access_token: 'jwt-123', user_id: 42, username: 'capsuleer' })
    const { result } = renderHook(() => useAuth(), { wrapper })

    await act(async () => {
      await result.current.login('capsuleer', 'secret')
    })

    expect(post).toHaveBeenCalledWith('/login', { username: 'capsuleer', password: 'secret' })
    expect(localStorage.getItem('token')).toBe('jwt-123')
    expect(JSON.parse(localStorage.getItem('user'))).toEqual({ id: 42, username: 'capsuleer' })
    expect(result.current.user).toEqual({ id: 42, username: 'capsuleer' })
  })

  it('logout() clears localStorage and user state', async () => {
    localStorage.setItem('token', 'jwt-123')
    localStorage.setItem('user', JSON.stringify({ id: 42, username: 'capsuleer' }))
    const { result } = renderHook(() => useAuth(), { wrapper })

    expect(result.current.user).toEqual({ id: 42, username: 'capsuleer' })

    act(() => {
      result.current.logout()
    })

    expect(localStorage.getItem('token')).toBeNull()
    expect(localStorage.getItem('user')).toBeNull()
    expect(result.current.user).toBeNull()
  })
})
