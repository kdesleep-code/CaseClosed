import { useEffect, useMemo, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'

import {
  createDictionaryEntry,
  deleteDictionaryEntry,
  listDictionaryEntries,
  updateDictionaryEntry,
} from './dictionaryApi'
import type { DictionaryEntry, DictionaryEntryInput } from './dictionaryApi'
import { t } from './i18n'
import { AppLink, TopNav, navigateTo } from './navigation'

type DictionaryForm = {
  headword: string
  aliases: string
  interpretation: string
  examples: string
  sourceUrls: string
  relatedEntryIds: string[]
}

const emptyForm: DictionaryForm = {
  headword: '',
  aliases: '',
  interpretation: '',
  examples: '',
  sourceUrls: '',
  relatedEntryIds: [],
}

function formFromEntry(entry: DictionaryEntry): DictionaryForm {
  return {
    headword: entry.headword,
    aliases: entry.aliases.join('\n'),
    interpretation: entry.interpretation,
    examples: entry.examples ?? '',
    sourceUrls: entry.source_urls.join('\n'),
    relatedEntryIds: entry.related_entry_ids,
  }
}

function splitValues(value: string) {
  return value
    .split(/[\n,、]+/)
    .map((item) => item.trim())
    .filter((item, index, items) => item !== '' && items.indexOf(item) === index)
}

function normalizeTerm(value: string) {
  return value.normalize('NFKC').toLocaleLowerCase()
}

function formatDate(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('ja-JP', {
    timeZone: 'Asia/Tokyo',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(date)
}

type LinkCandidate = {
  entry: DictionaryEntry
  terms: string[]
}

function autoLinkedPlainText(
  text: string,
  candidates: LinkCandidate[],
  linkedEntryIds: Set<string>,
  keyPrefix: string,
): ReactNode[] {
  const nodes: ReactNode[] = []
  let rest = text
  let nodeIndex = 0
  while (rest !== '') {
    const normalizedRest = normalizeTerm(rest)
    let best: { index: number; length: number; entry: DictionaryEntry } | null = null
    candidates.forEach(({ entry, terms }) => {
      if (linkedEntryIds.has(entry.id)) return
      terms.forEach((term) => {
        const normalized = normalizeTerm(term)
        if (normalized === '') return
        const index = normalizedRest.indexOf(normalized)
        if (
          index >= 0 &&
          (best === null || index < best.index || (index === best.index && term.length > best.length))
        ) {
          best = { index, length: term.length, entry }
        }
      })
    })
    if (best === null) {
      nodes.push(rest)
      break
    }
    const match = best as { index: number; length: number; entry: DictionaryEntry }
    if (match.index > 0) nodes.push(rest.slice(0, match.index))
    const label = rest.slice(match.index, match.index + match.length)
    linkedEntryIds.add(match.entry.id)
    nodes.push(
      <AppLink
        className="dictionary-auto-link"
        href={`/dictionary/${encodeURIComponent(match.entry.id)}`}
        key={`${keyPrefix}-auto-${nodeIndex}`}
      >
        {label}
      </AppLink>,
    )
    rest = rest.slice(match.index + match.length)
    nodeIndex += 1
  }
  return nodes
}

function linkedText(
  text: string,
  entries: DictionaryEntry[],
  currentEntryId: string,
): ReactNode {
  const termMap = new Map<string, DictionaryEntry>()
  const candidates: LinkCandidate[] = []
  entries.forEach((entry) => {
    if (entry.id === currentEntryId) return
    const terms = [entry.headword, ...entry.aliases]
    candidates.push({ entry, terms })
    terms.forEach((term) => termMap.set(normalizeTerm(term), entry))
  })
  candidates.sort((left, right) => {
    const leftLength = Math.max(...left.terms.map((term) => term.length))
    const rightLength = Math.max(...right.terms.map((term) => term.length))
    return rightLength - leftLength
  })

  const linkedEntryIds = new Set<string>()
  return text.split('\n').map((line, lineIndex) => {
    const nodes: ReactNode[] = []
    const tokenPattern = /(\[\[([^\]]+)\]\]|https?:\/\/[^\s]+)/g
    let cursor = 0
    let match: RegExpExecArray | null
    let tokenIndex = 0
    while ((match = tokenPattern.exec(line)) !== null) {
      if (match.index > cursor) {
        nodes.push(
          ...autoLinkedPlainText(
            line.slice(cursor, match.index),
            candidates,
            linkedEntryIds,
            `${lineIndex}-${tokenIndex}`,
          ),
        )
      }
      if (match[2] !== undefined) {
        const target = termMap.get(normalizeTerm(match[2].trim()))
        nodes.push(
          target === undefined ? (
            <span className="dictionary-unresolved-link" key={`explicit-${lineIndex}-${tokenIndex}`}>
              {match[0]}
            </span>
          ) : (
            <AppLink
              className="dictionary-explicit-link"
              href={`/dictionary/${encodeURIComponent(target.id)}`}
              key={`explicit-${lineIndex}-${tokenIndex}`}
            >
              {match[2]}
            </AppLink>
          ),
        )
        if (target !== undefined) linkedEntryIds.add(target.id)
      } else {
        nodes.push(
          <a
            href={match[0]}
            key={`url-${lineIndex}-${tokenIndex}`}
            rel="noopener noreferrer"
            target="_blank"
          >
            {match[0]}
          </a>,
        )
      }
      cursor = match.index + match[0].length
      tokenIndex += 1
    }
    if (cursor < line.length) {
      nodes.push(
        ...autoLinkedPlainText(
          line.slice(cursor),
          candidates,
          linkedEntryIds,
          `${lineIndex}-tail`,
        ),
      )
    }
    return (
      <span className="dictionary-text-line" key={`line-${lineIndex}`}>
        {nodes.length === 0 ? '\u00a0' : nodes}
      </span>
    )
  })
}

export default function DictionaryView({ entryId }: { entryId?: string }) {
  const [entries, setEntries] = useState<DictionaryEntry[]>([])
  const [query, setQuery] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [editingId, setEditingId] = useState<string | 'new' | null>(null)
  const [form, setForm] = useState<DictionaryForm>(emptyForm)
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [feedback, setFeedback] = useState<string | null>(null)

  useEffect(() => {
    let canceled = false
    listDictionaryEntries()
      .then((items) => {
        if (!canceled) setEntries(items)
      })
      .catch((requestError) => {
        if (!canceled) {
          setError(requestError instanceof Error ? requestError.message : t('app.requestFailed'))
        }
      })
      .finally(() => {
        if (!canceled) setIsLoading(false)
      })
    return () => {
      canceled = true
    }
  }, [])

  const selectedEntry = entries.find((entry) => entry.id === entryId) ?? null
  const normalizedQuery = normalizeTerm(query.trim())
  const visibleEntries = useMemo(
    () =>
      entries.filter((entry) =>
        normalizedQuery === '' ||
        normalizeTerm(
          [entry.headword, ...entry.aliases, entry.interpretation, entry.examples ?? ''].join(' '),
        ).includes(normalizedQuery),
      ),
    [entries, normalizedQuery],
  )

  function startCreate() {
    setEditingId('new')
    setForm(emptyForm)
    setError(null)
    setFeedback(null)
  }

  function startEdit(entry: DictionaryEntry) {
    setEditingId(entry.id)
    setForm(formFromEntry(entry))
    setError(null)
    setFeedback(null)
  }

  async function saveEntry(event: FormEvent) {
    event.preventDefault()
    const input: DictionaryEntryInput = {
      headword: form.headword,
      aliases: splitValues(form.aliases),
      interpretation: form.interpretation,
      examples: form.examples.trim() === '' ? null : form.examples,
      source_urls: splitValues(form.sourceUrls),
      related_entry_ids: form.relatedEntryIds,
    }
    setIsSaving(true)
    setError(null)
    try {
      const saved = editingId === 'new'
        ? await createDictionaryEntry(input)
        : await updateDictionaryEntry(editingId as string, input)
      setEntries((current) => {
        const withoutSaved = current.filter((entry) => entry.id !== saved.id)
        return [...withoutSaved, saved].sort((left, right) =>
          left.headword.localeCompare(right.headword, 'ja'),
        )
      })
      setEditingId(null)
      setFeedback(t('dictionary.saved'))
      navigateTo(`/dictionary/${encodeURIComponent(saved.id)}`, true)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('app.requestFailed'))
    } finally {
      setIsSaving(false)
    }
  }

  async function removeEntry(entry: DictionaryEntry) {
    if (!window.confirm(t('dictionary.deleteConfirm', { headword: entry.headword }))) return
    setError(null)
    try {
      await deleteDictionaryEntry(entry.id)
      setEntries((current) => current.filter((item) => item.id !== entry.id))
      setEditingId(null)
      setFeedback(t('dictionary.deleted'))
      navigateTo('/dictionary', true)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('app.requestFailed'))
    }
  }

  const relatedEntries = selectedEntry === null
    ? []
    : selectedEntry.related_entry_ids
        .map((relatedId) => entries.find((entry) => entry.id === relatedId))
        .filter((entry): entry is DictionaryEntry => entry !== undefined)

  return (
    <main className="app-shell">
      <div className="contacts-shell dictionary-shell">
        <header className="contacts-header dictionary-header">
          <div>
            <p>{t('app.name')}</p>
            <h1>{t('dictionary.heading')}</h1>
          </div>
          <TopNav
            ariaLabelKey="dictionary.navigation"
            items={[
              { href: '/', labelKey: 'top.heading' },
              { href: '/dictionary', labelKey: 'nav.dictionary' },
            ]}
          />
        </header>

        {(error !== null || feedback !== null) && (
          <div className="mail-feedback">
            {error !== null && <p role="alert">{error}</p>}
            {feedback !== null && <p>{feedback}</p>}
          </div>
        )}

        <section className="dictionary-toolbar">
          <label>
            <span>{t('dictionary.search')}</span>
            <input
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t('dictionary.searchPlaceholder')}
              type="search"
              value={query}
            />
          </label>
          <button onClick={startCreate} type="button">{t('dictionary.add')}</button>
        </section>

        <div className="dictionary-layout">
          <aside aria-label={t('dictionary.list')} className="dictionary-list">
            {isLoading ? (
              <p className="empty-state">{t('common.loading')}</p>
            ) : visibleEntries.length === 0 ? (
              <p className="empty-state">{t('dictionary.empty')}</p>
            ) : (
              visibleEntries.map((entry) => (
                <AppLink
                  className={`dictionary-list-item${entry.id === entryId ? ' is-active' : ''}`}
                  href={`/dictionary/${encodeURIComponent(entry.id)}`}
                  key={entry.id}
                >
                  <strong>{entry.headword}</strong>
                  {entry.aliases.length > 0 && <span>{entry.aliases.join('，')}</span>}
                  <small>{formatDate(entry.created_at)}</small>
                </AppLink>
              ))
            )}
          </aside>

          <section className="dictionary-detail">
            {editingId !== null ? (
              <form className="dictionary-form" onSubmit={saveEntry}>
                <div className="section-heading">
                  <h2>{editingId === 'new' ? t('dictionary.add') : t('dictionary.edit')}</h2>
                </div>
                <label>
                  <span>{t('dictionary.headword')}</span>
                  <input
                    autoFocus
                    maxLength={160}
                    onChange={(event) => setForm((current) => ({ ...current, headword: event.target.value }))}
                    required
                    value={form.headword}
                  />
                </label>
                <label>
                  <span>{t('dictionary.aliases')}</span>
                  <textarea
                    onChange={(event) => setForm((current) => ({ ...current, aliases: event.target.value }))}
                    placeholder={t('dictionary.aliasesHint')}
                    rows={3}
                    value={form.aliases}
                  />
                </label>
                <label>
                  <span>{t('dictionary.interpretation')}</span>
                  <textarea
                    onChange={(event) => setForm((current) => ({ ...current, interpretation: event.target.value }))}
                    required
                    rows={9}
                    value={form.interpretation}
                  />
                </label>
                <label>
                  <span>{t('dictionary.examples')}</span>
                  <textarea
                    onChange={(event) => setForm((current) => ({ ...current, examples: event.target.value }))}
                    rows={6}
                    value={form.examples}
                  />
                </label>
                <p className="dictionary-form-hint">{t('dictionary.internalLinkHint')}</p>
                <label>
                  <span>{t('dictionary.sources')}</span>
                  <textarea
                    onChange={(event) => setForm((current) => ({ ...current, sourceUrls: event.target.value }))}
                    placeholder={t('dictionary.sourcesHint')}
                    rows={3}
                    value={form.sourceUrls}
                  />
                </label>
                <fieldset className="dictionary-related-picker">
                  <legend>{t('dictionary.related')}</legend>
                  {entries.filter((entry) => entry.id !== editingId).length === 0 ? (
                    <p>{t('dictionary.relatedEmpty')}</p>
                  ) : (
                    entries
                      .filter((entry) => entry.id !== editingId)
                      .map((entry) => (
                        <label key={entry.id}>
                          <input
                            checked={form.relatedEntryIds.includes(entry.id)}
                            onChange={(event) =>
                              setForm((current) => ({
                                ...current,
                                relatedEntryIds: event.target.checked
                                  ? [...current.relatedEntryIds, entry.id]
                                  : current.relatedEntryIds.filter((id) => id !== entry.id),
                              }))
                            }
                            type="checkbox"
                          />
                          <span>{entry.headword}</span>
                        </label>
                      ))
                  )}
                </fieldset>
                <div className="dictionary-form-actions">
                  <button disabled={isSaving} type="submit">
                    {isSaving ? t('common.saving') : t('common.save')}
                  </button>
                  <button disabled={isSaving} onClick={() => setEditingId(null)} type="button">
                    {t('common.cancel')}
                  </button>
                </div>
              </form>
            ) : selectedEntry === null ? (
              <div className="dictionary-welcome">
                <h2>{t('dictionary.welcome')}</h2>
                <p>{t('dictionary.welcomeBody')}</p>
              </div>
            ) : (
              <article className="dictionary-entry">
                <header>
                  <div>
                    <p>{t('dictionary.entry')}</p>
                    <h2>{selectedEntry.headword}</h2>
                    {selectedEntry.aliases.length > 0 && (
                      <p className="dictionary-aliases">{selectedEntry.aliases.join('，')}</p>
                    )}
                  </div>
                  <div className="dictionary-entry-actions">
                    <button onClick={() => startEdit(selectedEntry)} type="button">{t('common.edit')}</button>
                    <button onClick={() => void removeEntry(selectedEntry)} type="button">{t('common.delete')}</button>
                  </div>
                </header>
                <section>
                  <h3>{t('dictionary.interpretation')}</h3>
                  <div className="dictionary-rich-text">
                    {linkedText(selectedEntry.interpretation, entries, selectedEntry.id)}
                  </div>
                </section>
                {selectedEntry.examples !== null && (
                  <section>
                    <h3>{t('dictionary.examples')}</h3>
                    <div className="dictionary-rich-text dictionary-examples">
                      {linkedText(selectedEntry.examples, entries, selectedEntry.id)}
                    </div>
                  </section>
                )}
                {relatedEntries.length > 0 && (
                  <section>
                    <h3>{t('dictionary.related')}</h3>
                    <div className="dictionary-related-links">
                      {relatedEntries.map((entry) => (
                        <AppLink href={`/dictionary/${encodeURIComponent(entry.id)}`} key={entry.id}>
                          {entry.headword}
                        </AppLink>
                      ))}
                    </div>
                  </section>
                )}
                {selectedEntry.source_urls.length > 0 && (
                  <section>
                    <h3>{t('dictionary.sources')}</h3>
                    <ul className="dictionary-source-list">
                      {selectedEntry.source_urls.map((url) => (
                        <li key={url}><a href={url} rel="noopener noreferrer" target="_blank">{url}</a></li>
                      ))}
                    </ul>
                  </section>
                )}
                <footer>
                  <span>{t('dictionary.registeredAt')}: {formatDate(selectedEntry.created_at)}</span>
                  <span>{t('dictionary.updatedAt')}: {formatDate(selectedEntry.updated_at)}</span>
                </footer>
              </article>
            )}
          </section>
        </div>
      </div>
    </main>
  )
}
