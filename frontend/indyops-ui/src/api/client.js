const BASE = '/api/v1'

async function req(method, path, body) {
  const token = localStorage.getItem('token')
  const headers = { 'Content-Type': 'application/json' }
  if (token) headers['Authorization'] = `Bearer ${token}`

  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  })

  if (res.status === 204) return null
  const data = await res.json()
  if (!res.ok) throw new Error(data.detail || 'Request failed')
  return data
}

export const get    = (path)        => req('GET',    path)
export const post   = (path, body)  => req('POST',   path, body)
export const patch  = (path, body)  => req('PATCH',  path, body)
export const del    = (path)        => req('DELETE',  path)
