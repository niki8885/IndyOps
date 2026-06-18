import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { get, post, put, patch, del, download } from './client'

// Build a small fake Response object.
function makeRes({ ok = true, status = 200, contentType = 'application/json', json, text, blob } = {}) {
  return {
    ok,
    status,
    headers: { get: () => contentType },
    json: async () => json,
    text: async () => text,
    blob: async () => blob,
  }
}

beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('req (get/post/put/patch/del)', () => {
  it('adds Authorization header when token is in localStorage', async () => {
    localStorage.setItem('token', 'abc123')
    const fakeFetch = vi.fn().mockResolvedValue(makeRes({ json: { ok: true } }))
    vi.stubGlobal('fetch', fakeFetch)

    await get('/me')

    expect(fakeFetch).toHaveBeenCalledTimes(1)
    const [, opts] = fakeFetch.mock.calls[0]
    expect(opts.headers['Authorization']).toBe('Bearer abc123')
    expect(opts.headers['Content-Type']).toBe('application/json')
  })

  it('omits Authorization header when no token', async () => {
    const fakeFetch = vi.fn().mockResolvedValue(makeRes({ json: { ok: true } }))
    vi.stubGlobal('fetch', fakeFetch)

    await get('/me')

    const [, opts] = fakeFetch.mock.calls[0]
    expect(opts.headers['Authorization']).toBeUndefined()
  })

  it('prefixes the BASE path /api/v1', async () => {
    const fakeFetch = vi.fn().mockResolvedValue(makeRes({ json: {} }))
    vi.stubGlobal('fetch', fakeFetch)

    await get('/things')

    const [url] = fakeFetch.mock.calls[0]
    expect(url).toBe('/api/v1/things')
  })

  it('parses and returns JSON responses', async () => {
    const payload = { id: 1, name: 'thing' }
    const fakeFetch = vi.fn().mockResolvedValue(makeRes({ json: payload }))
    vi.stubGlobal('fetch', fakeFetch)

    const result = await get('/thing/1')

    expect(result).toEqual(payload)
  })

  it('returns null on 204 No Content', async () => {
    const fakeFetch = vi.fn().mockResolvedValue(makeRes({ status: 204, ok: true }))
    vi.stubGlobal('fetch', fakeFetch)

    const result = await del('/thing/1')

    expect(result).toBeNull()
  })

  it('treats a missing content-type header as non-JSON text', async () => {
    const fakeFetch = vi.fn().mockResolvedValue(
      makeRes({ contentType: null, text: 'raw body' }),
    )
    vi.stubGlobal('fetch', fakeFetch)

    const result = await get('/raw')

    expect(result).toBe('raw body')
  })

  it('returns plain text for non-JSON responses', async () => {
    const fakeFetch = vi.fn().mockResolvedValue(
      makeRes({ contentType: 'text/plain', text: 'hello world' }),
    )
    vi.stubGlobal('fetch', fakeFetch)

    const result = await get('/text')

    expect(result).toBe('hello world')
  })

  it('serializes body and method for POST', async () => {
    const fakeFetch = vi.fn().mockResolvedValue(makeRes({ json: {} }))
    vi.stubGlobal('fetch', fakeFetch)

    await post('/create', { a: 1, b: 'two' })

    const [url, opts] = fakeFetch.mock.calls[0]
    expect(url).toBe('/api/v1/create')
    expect(opts.method).toBe('POST')
    expect(opts.body).toBe(JSON.stringify({ a: 1, b: 'two' }))
  })

  it('sends undefined body when none provided', async () => {
    const fakeFetch = vi.fn().mockResolvedValue(makeRes({ json: {} }))
    vi.stubGlobal('fetch', fakeFetch)

    await get('/none')

    const [, opts] = fakeFetch.mock.calls[0]
    expect(opts.method).toBe('GET')
    expect(opts.body).toBeUndefined()
  })

  it('uses correct methods for put/patch/del', async () => {
    const fakeFetch = vi.fn().mockResolvedValue(makeRes({ json: {} }))
    vi.stubGlobal('fetch', fakeFetch)

    await put('/p', { x: 1 })
    await patch('/q', { y: 2 })
    await del('/r')

    expect(fakeFetch.mock.calls[0][1].method).toBe('PUT')
    expect(fakeFetch.mock.calls[0][1].body).toBe(JSON.stringify({ x: 1 }))
    expect(fakeFetch.mock.calls[1][1].method).toBe('PATCH')
    expect(fakeFetch.mock.calls[1][1].body).toBe(JSON.stringify({ y: 2 }))
    expect(fakeFetch.mock.calls[2][1].method).toBe('DELETE')
    expect(fakeFetch.mock.calls[2][1].body).toBeUndefined()
  })

  it('throws Error with detail from JSON error body', async () => {
    const fakeFetch = vi.fn().mockResolvedValue(
      makeRes({ ok: false, status: 400, json: { detail: 'Bad input' } }),
    )
    vi.stubGlobal('fetch', fakeFetch)

    await expect(get('/bad')).rejects.toThrow('Bad input')
  })

  it('throws Error with stringified JSON when detail absent', async () => {
    const body = { code: 'E1', extra: true }
    const fakeFetch = vi.fn().mockResolvedValue(
      makeRes({ ok: false, status: 422, json: body }),
    )
    vi.stubGlobal('fetch', fakeFetch)

    await expect(get('/bad')).rejects.toThrow(JSON.stringify(body))
  })

  it('throws Error with text body for non-JSON error', async () => {
    const fakeFetch = vi.fn().mockResolvedValue(
      makeRes({ ok: false, status: 500, contentType: 'text/plain', text: 'server boom' }),
    )
    vi.stubGlobal('fetch', fakeFetch)

    await expect(get('/bad')).rejects.toThrow('server boom')
  })

  it('falls back to HTTP <status> when text body is empty', async () => {
    const fakeFetch = vi.fn().mockResolvedValue(
      makeRes({ ok: false, status: 503, contentType: 'text/plain', text: '' }),
    )
    vi.stubGlobal('fetch', fakeFetch)

    await expect(get('/bad')).rejects.toThrow('HTTP 503')
  })
})

describe('download', () => {
  it('fetches a blob and triggers an anchor click', async () => {
    const blob = new Blob(['pdf-bytes'], { type: 'application/pdf' })
    const fakeFetch = vi.fn().mockResolvedValue(makeRes({ ok: true, blob }))
    vi.stubGlobal('fetch', fakeFetch)

    const createObjectURL = vi.fn(() => 'blob:fake-url')
    const revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL })

    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => {})

    await download('/report.pdf', 'report.pdf')

    expect(fakeFetch).toHaveBeenCalledWith('/api/v1/report.pdf', { headers: {} })
    expect(createObjectURL).toHaveBeenCalledWith(blob)
    expect(clickSpy).toHaveBeenCalledTimes(1)
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:fake-url')

    clickSpy.mockRestore()
  })

  it('includes the Authorization header when token present', async () => {
    localStorage.setItem('token', 'tok')
    const blob = new Blob(['x'])
    const fakeFetch = vi.fn().mockResolvedValue(makeRes({ ok: true, blob }))
    vi.stubGlobal('fetch', fakeFetch)
    vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'u'), revokeObjectURL: vi.fn() })
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => {})

    await download('/report.pdf', 'r.pdf')

    expect(fakeFetch).toHaveBeenCalledWith('/api/v1/report.pdf', {
      headers: { Authorization: 'Bearer tok' },
    })
    clickSpy.mockRestore()
  })

  it('throws on a non-ok response', async () => {
    const fakeFetch = vi.fn().mockResolvedValue(makeRes({ ok: false, status: 404 }))
    vi.stubGlobal('fetch', fakeFetch)

    await expect(download('/missing.pdf', 'x.pdf')).rejects.toThrow('HTTP 404')
  })
})
