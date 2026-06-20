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
export const put    = (path, body)  => req('PUT',    path, body)
export const patch  = (path, body)  => req('PATCH',  path, body)
export const del    = (path)        => req('DELETE',  path)

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

// Fetch a binary response (e.g. a PDF) and trigger a browser download.
export async function download(path, filename) {
  const token = localStorage.getItem('token')
  const res = await fetch(`${BASE}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  triggerDownload(await res.blob(), filename)
}

// POST a JSON body and download the binary response (e.g. a generated PDF report).
export async function downloadPost(path, body, filename) {
  const token = localStorage.getItem('token')
  const headers = { 'Content-Type': 'application/json' }
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(`${BASE}${path}`, { method: 'POST', headers, body: JSON.stringify(body) })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  triggerDownload(await res.blob(), filename)
}
