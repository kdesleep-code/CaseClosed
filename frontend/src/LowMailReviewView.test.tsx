import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import LowMailReviewView, { LowMailReviewDetailView } from './LowMailReviewView'
import { navigateTo } from './navigation'
import {
  getLowMailReviewDetail,
  listTodayLowMailReview,
  promoteReviewMailToMiddle,
} from './phase4Api'

vi.mock('./authApi', () => ({ logout: vi.fn() }))
vi.mock('./navigation', () => ({ navigateTo: vi.fn() }))
vi.mock('./phase4Api', () => ({
  getLowMailReviewDetail: vi.fn(),
  listTodayLowMailReview: vi.fn(),
  promoteReviewMailToMiddle: vi.fn(),
}))

const mail = {
  id: 'mail_review_1',
  gmail_message_id: 'gmail_review_1',
  gmail_thread_id: 'thread_review_1',
  received_at: '2026-07-13T10:30:00+09:00',
  subject: 'Please inspect this',
  from_address: 'sender@example.com',
  from_name: 'Review Sender',
  reply_to_address: null,
  list_id: null,
  processed_status: 'unprocessed',
  user_importance: 'low',
  effective_importance: 'low',
  external_importance: null,
  suggested_importance: null,
  llm_run_id: null,
  pending_reason: null,
  snippet: 'A short list preview.',
}

const detailMail = {
  ...mail,
  body_text: 'The full message body.',
}

describe('LowMailReviewView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.localStorage.setItem('caseclosed.uiLanguage', 'en')
    vi.mocked(listTodayLowMailReview).mockResolvedValue({
      date: '2026-07-13',
      items: [mail],
    })
    vi.mocked(getLowMailReviewDetail).mockResolvedValue(detailMail)
    vi.mocked(promoteReviewMailToMiddle).mockResolvedValue({
      id: mail.id,
      importance: 'middle',
    })
  })

  it('opens a separate detail page when the list item is tapped', async () => {
    render(<LowMailReviewView />)

    const item = await screen.findByRole('button', { name: /Please inspect this/ })
    expect(screen.getByText('A short list preview.')).toBeInTheDocument()
    expect(screen.queryByText('The full message body.')).not.toBeInTheDocument()

    fireEvent.click(item)

    expect(navigateTo).toHaveBeenCalledWith('/mail/review/mail_review_1')
  })

  it('shows the full body in detail and returns to the list after promoting', async () => {
    render(<LowMailReviewDetailView messageId={mail.id} />)

    expect(await screen.findByText('The full message body.')).toBeInTheDocument()
    expect(getLowMailReviewDetail).toHaveBeenCalledWith(mail.id)
    fireEvent.click(screen.getByRole('button', { name: 'Move to Middle' }))

    await waitFor(() => {
      expect(promoteReviewMailToMiddle).toHaveBeenCalledWith(mail.id)
      expect(navigateTo).toHaveBeenCalledWith('/mail/review', true)
    })
  })
})
