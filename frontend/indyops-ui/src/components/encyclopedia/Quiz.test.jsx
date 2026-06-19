import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('../../api/client', () => ({ post: vi.fn() }))
import { post } from '../../api/client'
import Quiz from './Quiz'

const Q = [
  { q: 'Q1?', options: ['Q1-A', 'Q1-B', 'Q1-C'], answer: 1 },
  { q: 'Q2?', options: ['Q2-A', 'Q2-B'], answer: 0 },
]

beforeEach(() => post.mockReset())

describe('Quiz', () => {
  it('scores answers and saves the result to the account', async () => {
    post.mockResolvedValue({ ok: true, score: 2, total: 2, best: 2, attempts: 1 })
    render(<Quiz section="finance" articleKey="monte-carlo" questions={Q} />)

    expect(screen.getByText('Submit answers')).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: /Q1-B/ }))   // correct
    fireEvent.click(screen.getByRole('button', { name: /Q2-A/ }))   // correct
    fireEvent.click(screen.getByText('Submit answers'))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/encyclopedia/quiz',
      { section: 'finance', article_key: 'monte-carlo', score: 2, total: 2 }))
    expect(screen.getByText(/Score 2\/2/)).toBeInTheDocument()
    expect(screen.getByText('PASS')).toBeInTheDocument()   // 100% ≥ 70%
    expect(await screen.findByText(/saved to your account/)).toBeInTheDocument()
  })

  it('marks a wrong answer and scores lower', async () => {
    post.mockResolvedValue({ ok: true, score: 1, total: 2, best: 1, attempts: 1 })
    render(<Quiz section="finance" articleKey="x" questions={Q} />)
    fireEvent.click(screen.getByRole('button', { name: /Q1-A/ }))   // wrong (answer is B)
    fireEvent.click(screen.getByRole('button', { name: /Q2-A/ }))   // correct
    fireEvent.click(screen.getByText('Submit answers'))
    await waitFor(() => expect(post).toHaveBeenCalled())
    expect(post.mock.calls[0][1].score).toBe(1)
    expect(screen.getByText(/Score 1\/2/)).toBeInTheDocument()
  })
})
