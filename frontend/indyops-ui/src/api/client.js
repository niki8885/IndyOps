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

  const contentType = res.headers.get('content-type') || ''
  const isJson = contentType.includes('application/json')
  const data = isJson ? await res.json() : await res.text()

  if (!res.ok) {
    const msg = isJson
      ? (data.detail || JSON.stringify(data))
      : data || `HTTP ${res.status}`
    throw new Error(msg)
  }
  return data
}

export const get    = (path)        => req('GET',    path)
export const post   = (path, body)  => req('POST',   path, body)
export const patch  = (path, body)  => req('PATCH',  path, body)
export const del    = (path)        => req('DELETE',  path)
