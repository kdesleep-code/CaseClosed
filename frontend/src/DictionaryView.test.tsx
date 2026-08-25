import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import DictionaryView from './DictionaryView'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('DictionaryView', () => {
  it('shows registered dates and links registered terms without changing source text', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(
          new Response(
            JSON.stringify({
              ok: true,
              data: {
                items: [
                  {
                    id: 'entry_source',
                    headword: 'Source term',
                    aliases: [],
                    interpretation: 'The Target term appears here. Target term appears twice.',
                    examples: 'See [[Target term]] for a precise relationship.',
                    source_urls: ['https://example.com/source'],
                    related_entry_ids: ['entry_target'],
                    created_at: '2026-08-15T10:00:00+09:00',
                    updated_at: '2026-08-15T11:00:00+09:00',
                    version: 1,
                  },
                  {
                    id: 'entry_target',
                    headword: 'Target term',
                    aliases: ['Target alias'],
                    interpretation: 'The linked entry.',
                    examples: null,
                    source_urls: [],
                    related_entry_ids: [],
                    created_at: '2026-08-14T10:00:00+09:00',
                    updated_at: '2026-08-14T10:00:00+09:00',
                    version: 1,
                  },
                ],
              },
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ),
        ),
      ),
    )

    render(<DictionaryView entryId="entry_source" />)

    expect(await screen.findByRole('heading', { name: 'Source term' })).toBeInTheDocument()
    expect(screen.getByText('Registered: 2026/08/15')).toBeInTheDocument()
    const automaticLink = screen
      .getAllByRole('link', { name: 'Target term' })
      .find((link) => link.classList.contains('dictionary-auto-link'))
    expect(automaticLink).toHaveAttribute('href', '/dictionary/entry_target')
    expect(screen.getByRole('link', { name: 'https://example.com/source' })).toHaveAttribute(
      'target',
      '_blank',
    )
  })
})
