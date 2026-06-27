import { useEffect, useMemo, useRef, useState } from 'react'
import type { ChangeEvent, FormEvent } from 'react'
import { deleteBookshelfMaterial, listStorageObjects, uploadBookshelfMaterial } from './phase3Api'
import type { StorageObject } from './phase3Api'
import { t } from './i18n'
import bookNoteIconUrl from './assets/book-note-icon.png'
import { navigateTo, TopNav } from './navigation'

const bookshelfDirectoryId = 'storage_directory_bookshelf'
const bookshelfTagsStorageKey = 'caseclosed.bookshelf.tags'
const bookshelfAuthorsStorageKey = 'caseclosed.bookshelf.authors'
const bookshelfTitlesStorageKey = 'caseclosed.bookshelf.titles'
const bookshelfTagHierarchyStorageKey = 'caseclosed.bookshelf.tagHierarchy'
const bookshelfTabsStorageKey = 'caseclosed.bookshelf.tabs'
const noTagFilterValue = '__caseclosed_bookshelf_no_tag__'
const maxCustomTabs = 4
const maxCustomTabNameLength = 12

type BookshelfCustomTab = {
  id: string
  label: string
  expression: string
}

function isBookshelfMaterialFile(file: File) {
  const filename = file.name.trim().toLowerCase()
  return filename.endsWith('.pdf') || filename.endsWith('.epub')
}

function bookTitle(book: StorageObject, titleOverride?: string) {
  const filename = titleOverride?.trim() || book.original_filename || t('bookshelf.untitled')
  return filename.replace(/\.pdf$/i, '')
}

function normalizeTag(tag: string) {
  return tag.trim().toLowerCase()
}

function parseTags(value: string) {
  const tags: string[] = []
  const seen = new Set<string>()
  value.split(',').forEach((rawTag) => {
    const tag = rawTag.trim()
    const normalized = normalizeTag(tag)
    if (tag === '' || seen.has(normalized)) return
    seen.add(normalized)
    tags.push(tag)
  })
  return tags
}

function readStoredTagHierarchy() {
  try {
    const rawValue = window.localStorage.getItem(bookshelfTagHierarchyStorageKey)
    if (rawValue === null) return {}
    const parsed = JSON.parse(rawValue)
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) return {}
    const result: Record<string, string> = {}
    Object.entries(parsed).forEach(([childTag, parentTag]) => {
      if (typeof parentTag !== 'string') return
      const normalizedChild = normalizeTag(childTag)
      const trimmedParent = parentTag.trim()
      if (normalizedChild === '' || trimmedParent === '' || normalizedChild === normalizeTag(trimmedParent)) return
      result[normalizedChild] = trimmedParent
    })
    return result
  } catch {
    return {}
  }
}

function tagsWithAncestors(tags: string[], tagParents: Record<string, string>) {
  const result: string[] = []
  const seen = new Set<string>()
  function addTag(tag: string) {
    const trimmedTag = tag.trim()
    const normalizedTag = normalizeTag(trimmedTag)
    if (trimmedTag === '' || seen.has(normalizedTag)) return false
    seen.add(normalizedTag)
    result.push(trimmedTag)
    return true
  }
  tags.forEach((tag) => {
    let currentTag = tag
    const visited = new Set<string>()
    for (let depth = 0; depth < 20; depth += 1) {
      const normalizedCurrent = normalizeTag(currentTag)
      if (visited.has(normalizedCurrent)) break
      visited.add(normalizedCurrent)
      addTag(currentTag)
      const parentTag = tagParents[normalizedCurrent]
      if (parentTag === undefined) break
      currentTag = parentTag
    }
  })
  return result
}

function readStoredTags() {
  try {
    const rawValue = window.localStorage.getItem(bookshelfTagsStorageKey)
    if (rawValue === null) return {}
    const parsed = JSON.parse(rawValue)
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) return {}
    const result: Record<string, string[]> = {}
    Object.entries(parsed).forEach(([bookId, value]) => {
      if (!Array.isArray(value)) return
      result[bookId] = value.filter((item): item is string => typeof item === 'string')
    })
    return result
  } catch {
    return {}
  }
}

function writeStoredTags(tagsByBookId: Record<string, string[]>) {
  window.localStorage.setItem(bookshelfTagsStorageKey, JSON.stringify(tagsByBookId))
}

function readStoredAuthors() {
  try {
    const rawValue = window.localStorage.getItem(bookshelfAuthorsStorageKey)
    if (rawValue === null) return {}
    const parsed = JSON.parse(rawValue)
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) return {}
    const result: Record<string, string> = {}
    Object.entries(parsed).forEach(([bookId, value]) => {
      if (typeof value !== 'string') return
      result[bookId] = value
    })
    return result
  } catch {
    return {}
  }
}

function writeStoredAuthors(authorsByBookId: Record<string, string>) {
  window.localStorage.setItem(bookshelfAuthorsStorageKey, JSON.stringify(authorsByBookId))
}

function readStoredTitles() {
  try {
    const rawValue = window.localStorage.getItem(bookshelfTitlesStorageKey)
    if (rawValue === null) return {}
    const parsed = JSON.parse(rawValue)
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) return {}
    const result: Record<string, string> = {}
    Object.entries(parsed).forEach(([bookId, value]) => {
      if (typeof value !== 'string') return
      result[bookId] = value
    })
    return result
  } catch {
    return {}
  }
}

function writeStoredTitles(titlesByBookId: Record<string, string>) {
  window.localStorage.setItem(bookshelfTitlesStorageKey, JSON.stringify(titlesByBookId))
}

function readStoredTabs() {
  try {
    const rawValue = window.localStorage.getItem(bookshelfTabsStorageKey)
    if (rawValue === null) return []
    const parsed = JSON.parse(rawValue)
    if (!Array.isArray(parsed)) return []
    return parsed.flatMap((item): BookshelfCustomTab[] => {
      if (item === null || typeof item !== 'object') return []
      const value = item as Partial<BookshelfCustomTab>
      if (typeof value.id !== 'string' || typeof value.label !== 'string' || typeof value.expression !== 'string') {
        return []
      }
      return [{ id: value.id, label: value.label, expression: value.expression }]
    })
  } catch {
    return []
  }
}

function writeStoredTabs(tabs: BookshelfCustomTab[]) {
  window.localStorage.setItem(bookshelfTabsStorageKey, JSON.stringify(tabs))
}

function expressionTerms(expression: string) {
  return expression
    .trim()
    .replace(/^\{|\}$/g, '')
    .split('&')
    .map((term) => term.trim())
    .filter(Boolean)
}

function customTabMatches(tags: string[], expression: string) {
  const normalizedTags = new Set(tags.map(normalizeTag))
  const terms = expressionTerms(expression)
  if (terms.length === 0) return true
  return terms.every((term) => {
    if (term.startsWith('!')) return !normalizedTags.has(normalizeTag(term.slice(1)))
    return normalizedTags.has(normalizeTag(term))
  })
}

export default function BookshelfView() {
  const [books, setBooks] = useState<StorageObject[]>([])
  const [tagsByBookId, setTagsByBookId] = useState<Record<string, string[]>>(() => readStoredTags())
  const [authorsByBookId, setAuthorsByBookId] = useState<Record<string, string>>(() => readStoredAuthors())
  const [titlesByBookId, setTitlesByBookId] = useState<Record<string, string>>(() => readStoredTitles())
  const tagParents = useMemo(() => readStoredTagHierarchy(), [])
  const [customTabs, setCustomTabs] = useState<BookshelfCustomTab[]>(() => readStoredTabs())
  const [selectedTagFilter, setSelectedTagFilter] = useState<string | null>(null)
  const [activeTabId, setActiveTabId] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [editingBookId, setEditingBookId] = useState<string | null>(null)
  const [openMenuBookId, setOpenMenuBookId] = useState<string | null>(null)
  const [titleDraft, setTitleDraft] = useState('')
  const [tagDraft, setTagDraft] = useState('')
  const [authorDraft, setAuthorDraft] = useState('')
  const [tabName, setTabName] = useState('')
  const [tabExpression, setTabExpression] = useState('')
  const [isTabEditorOpen, setIsTabEditorOpen] = useState(false)
  const [feedback, setFeedback] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const editBackdropPointerStartedRef = useRef(false)
  const [isLoading, setIsLoading] = useState(true)
  const [isUploading, setIsUploading] = useState(false)

  function loadBooks() {
    setIsLoading(true)
    setError(null)
    listStorageObjects({ directory_id: bookshelfDirectoryId, status: 'active', limit: 500 })
      .then((items) => setBooks(items))
      .catch((caught) => setError(caught instanceof Error ? caught.message : t('app.requestFailed')))
      .finally(() => setIsLoading(false))
  }

  useEffect(() => {
    loadBooks()
  }, [])

  useEffect(() => {
    writeStoredTags(tagsByBookId)
  }, [tagsByBookId])

  useEffect(() => {
    writeStoredAuthors(authorsByBookId)
  }, [authorsByBookId])

  useEffect(() => {
    writeStoredTitles(titlesByBookId)
  }, [titlesByBookId])

  useEffect(() => {
    writeStoredTabs(customTabs)
  }, [customTabs])

  const tagCounts = useMemo(() => {
    const counts = new Map<string, number>()
    books.forEach((book) => {
      tagsWithAncestors(tagsByBookId[book.id] ?? [], tagParents).forEach((tag) => {
        counts.set(tag, (counts.get(tag) ?? 0) + 1)
      })
    })
    return [...counts.entries()].sort((left, right) => left[0].localeCompare(right[0]))
  }, [books, tagParents, tagsByBookId])

  const noTagCount = useMemo(
    () => books.filter((book) => (tagsByBookId[book.id] ?? []).length === 0).length,
    [books, tagsByBookId],
  )

  const visibleBooks = useMemo(() => {
    const queryTerms = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
    const activeTab = customTabs.find((tab) => tab.id === activeTabId) ?? null
    return books
      .filter((book) => {
        const tags = tagsByBookId[book.id] ?? []
        const effectiveTags = tagsWithAncestors(tags, tagParents)
        if (selectedTagFilter === noTagFilterValue && tags.length !== 0) return false
        if (selectedTagFilter !== null && selectedTagFilter !== noTagFilterValue && !effectiveTags.some((tag) => normalizeTag(tag) === normalizeTag(selectedTagFilter))) {
          return false
        }
        if (activeTab !== null && !customTabMatches(effectiveTags, activeTab.expression)) return false
        if (queryTerms.length === 0) return true
        const searchableText = [bookTitle(book, titlesByBookId[book.id]), book.original_filename ?? '', authorsByBookId[book.id] ?? '', effectiveTags.join(' ')]
          .join(' ')
          .toLowerCase()
        return queryTerms.every((term) => searchableText.includes(term))
      })
      .toSorted((first, second) => bookTitle(first, titlesByBookId[first.id]).localeCompare(bookTitle(second, titlesByBookId[second.id])))
  }, [activeTabId, authorsByBookId, books, customTabs, query, selectedTagFilter, tagParents, tagsByBookId, titlesByBookId])

  const activeListTabId = activeTabId === null ? (isTabEditorOpen ? 'add' : 'all') : activeTabId
  const editingBook = editingBookId === null ? null : books.find((book) => book.id === editingBookId) ?? null

  async function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null
    event.target.value = ''
    if (file === null) return
    setFeedback(null)
    setError(null)
    if (!isBookshelfMaterialFile(file)) {
      setError(t('bookshelf.upload.materialOnly'))
      return
    }
    setIsUploading(true)
    try {
      await uploadBookshelfMaterial(file)
      setFeedback(t('bookshelf.upload.done', { filename: file.name }))
      loadBooks()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t('bookshelf.upload.failed'))
    } finally {
      setIsUploading(false)
    }
  }

  function startEditBook(book: StorageObject) {
    setEditingBookId(book.id)
    setTitleDraft(bookTitle(book, titlesByBookId[book.id]))
    setTagDraft((tagsByBookId[book.id] ?? []).join(', '))
    setAuthorDraft(authorsByBookId[book.id] ?? '')
    setOpenMenuBookId(null)
    setFeedback(null)
    setError(null)
  }

  function closeEditDialogFromBackdrop(event: React.PointerEvent<HTMLDivElement>) {
    const startedOnBackdrop = editBackdropPointerStartedRef.current
    editBackdropPointerStartedRef.current = false
    if (!startedOnBackdrop || event.target !== event.currentTarget) return
    setEditingBookId(null)
  }

  function updateBookMetadata(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (editingBook === null) return
    const nextTitle = titleDraft.trim()
    const nextAuthor = authorDraft.trim()
    setTitlesByBookId((current) => ({ ...current, [editingBook.id]: nextTitle }))
    setAuthorsByBookId((current) => ({ ...current, [editingBook.id]: nextAuthor }))
    setTagsByBookId((current) => ({ ...current, [editingBook.id]: parseTags(tagDraft) }))
    setEditingBookId(null)
    setFeedback(t('bookshelf.metadata.saved'))
  }

  async function deleteBook(book: StorageObject) {
    const title = bookTitle(book, titlesByBookId[book.id])
    if (!window.confirm(t('bookshelf.delete.confirm', { title }))) return
    setOpenMenuBookId(null)
    setFeedback(null)
    setError(null)
    try {
      await deleteBookshelfMaterial(book.id)
      setBooks((current) => current.filter((item) => item.id !== book.id))
      setTagsByBookId((current) => {
        const next = { ...current }
        delete next[book.id]
        return next
      })
      setAuthorsByBookId((current) => {
        const next = { ...current }
        delete next[book.id]
        return next
      })
      setTitlesByBookId((current) => {
        const next = { ...current }
        delete next[book.id]
        return next
      })
      setFeedback(t('bookshelf.delete.done', { title }))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t('app.requestFailed'))
    }
  }

  function createCustomTab(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const expression = tabExpression.trim()
    const label = (tabName.trim() || expression).slice(0, maxCustomTabNameLength)
    if (label === '' || expression === '') return
    const nextTab = { id: `bookshelf_tab_${Date.now()}`, label, expression }
    setCustomTabs((current) => [...current, nextTab].slice(0, maxCustomTabs))
    setActiveTabId(nextTab.id)
    setSelectedTagFilter(null)
    setQuery('')
    setTabName('')
    setTabExpression('')
    setIsTabEditorOpen(false)
  }

  function openCustomTabEditor() {
    setActiveTabId(null)
    setSelectedTagFilter(null)
    setQuery('')
    setIsTabEditorOpen(true)
  }

  function deleteCustomTab(tabId: string) {
    const nextTabs = customTabs.filter((tab) => tab.id !== tabId)
    setCustomTabs(nextTabs)
    setActiveTabId(null)
    setIsTabEditorOpen(false)
  }

  return (
    <main className="app-shell">
      <div className="contacts-shell bookshelf-shell">
        <header className="contacts-header">
          <div>
            <p>{t('app.name')}</p>
            <h1>{t('bookshelf.heading')}</h1>
          </div>
          <TopNav
            ariaLabelKey="bookshelf.navigation"
            items={[
              { href: '/', labelKey: 'top.heading' },
              { href: '/files', labelKey: 'nav.files' },
              { href: '/cases', labelKey: 'nav.cases' },
              { href: '/tasks', labelKey: 'nav.tasks' },
            ]}
          />
        </header>

        {error !== null && <p className="contact-error" role="alert">{error}</p>}
        {feedback !== null && <p className="contact-notice">{feedback}</p>}

        <section aria-labelledby="bookshelf-tools-heading" className="contact-panel contact-tools-panel">
          <div className="section-heading bookshelf-tools-heading-row">
            <h2 id="bookshelf-tools-heading">{t('bookshelf.tools.heading')}</h2>
            <button onClick={() => navigateTo('/bookshelf/tag-hierarchy')} type="button">{t('bookshelf.tagHierarchy.edit')}</button>
          </div>
          <div className="contact-tools bookshelf-tools">
            <div aria-label={t('bookshelf.search.region')} role="search">
              <label>
                <span>{t('bookshelf.search')}</span>
                <input
                  aria-label={t('bookshelf.search')}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder={t('bookshelf.searchPlaceholder')}
                  type="search"
                  value={query}
                />
              </label>
              <div
                aria-label={t('bookshelf.tags.filter')}
                className={`contact-tag-filters${tagCounts.length === 0 && noTagCount === 0 ? ' contact-tag-filters-placeholder' : ''}`}
              >
                {noTagCount > 0 && (
                  <button
                    aria-pressed={selectedTagFilter === noTagFilterValue}
                    className="is-reserved-contact-tag"
                    onClick={() => setSelectedTagFilter((current) => current === noTagFilterValue ? null : noTagFilterValue)}
                    type="button"
                  >
                    {t('bookshelf.tags.noTag')}
                    <span>{noTagCount}</span>
                  </button>
                )}
                {tagCounts.map(([tag, count]) => (
                  <button
                    aria-pressed={selectedTagFilter === tag}
                    key={tag}
                    onClick={() => setSelectedTagFilter((current) => current === tag ? null : tag)}
                    type="button"
                  >
                    {tag}
                    <span>{count}</span>
                  </button>
                ))}
              </div>
            </div>
            <div className="contact-tool-actions bookshelf-tool-actions">
              <label className={`bookshelf-upload-button button-loading-dot${isUploading ? ' is-loading' : ''}`}>
                <input
                  accept=".pdf,.epub,application/pdf,application/epub+zip"
                  disabled={isUploading}
                  onChange={(event) => { void handleFileChange(event) }}
                  type="file"
                />
                <span>{t('bookshelf.upload.add')}</span>
              </label>
            </div>
          </div>
        </section>

        <section className="contact-list-workspace bookshelf-list-workspace">
          <div aria-label={t('bookshelf.list.views')} className="contact-list-tabs" role="tablist">
            <div className="contact-list-tabs-left">
              <button
                aria-selected={activeListTabId === 'all'}
                onClick={() => {
                  setActiveTabId(null)
                  setIsTabEditorOpen(false)
                }}
                role="tab"
                type="button"
              >
                {t('bookshelf.tabs.all')}
              </button>
              {customTabs.map((tab) => (
                <button
                  aria-selected={activeListTabId === tab.id}
                  key={tab.id}
                  onClick={() => {
                    setActiveTabId(tab.id)
                    setIsTabEditorOpen(false)
                  }}
                  role="tab"
                  type="button"
                >
                  {tab.label}
                </button>
              ))}
            </div>
            <div className="contact-list-tabs-right">
              {customTabs.length < maxCustomTabs && (
                <button aria-selected={activeListTabId === 'add'} onClick={openCustomTabEditor} role="tab" type="button">
                  {t('bookshelf.tabs.add')}
                </button>
              )}
            </div>
          </div>
          <div className="contact-list-panel-surface">
            <div className="contact-list-panel" role="tabpanel" aria-label={t('bookshelf.list.heading')}>
              {isTabEditorOpen && (
                <form className="custom-tab-form custom-tab-form-panel" onSubmit={createCustomTab}>
                  <label>
                    <span>{t('bookshelf.tabs.name')}</span>
                    <input onChange={(event) => setTabName(event.target.value)} value={tabName} />
                  </label>
                  <label>
                    <span>{t('bookshelf.tabs.expression')}</span>
                    <input
                      onChange={(event) => setTabExpression(event.target.value)}
                      placeholder={t('bookshelf.tabs.expressionPlaceholder')}
                      value={tabExpression}
                    />
                  </label>
                  <button type="submit">{t('bookshelf.tabs.save')}</button>
                </form>
              )}
              {!isTabEditorOpen && (
                activeTabId !== null && customTabs.some((tab) => tab.id === activeTabId) ? (
                  <div className="custom-tab-actions">
                    <p>{customTabs.find((tab) => tab.id === activeTabId)?.expression}</p>
                    <button onClick={() => deleteCustomTab(activeTabId)} type="button">{t('bookshelf.tabs.delete')}</button>
                  </div>
                ) : (
                  <div aria-hidden="true" className="custom-tab-actions bookshelf-tab-actions-placeholder">
                    <p>&nbsp;</p>
                    <button disabled type="button">{t('bookshelf.tabs.delete')}</button>
                  </div>
                )
              )}
              <div className="contact-list bookshelf-list">
                {isLoading ? (
                  <p className="empty-state">{t('common.loading')}</p>
                ) : visibleBooks.length === 0 ? (
                  <p className="empty-state">{t('bookshelf.empty.body')}</p>
                ) : (
                  visibleBooks.map((book) => {
                    const tags = tagsByBookId[book.id] ?? []
                    return (
                      <article
                        className="contact-row bookshelf-row"
                        key={book.id}
                        onClick={() => navigateTo(`/bookshelf/${encodeURIComponent(book.id)}`)}
                      >
                        <div className="contact-identity">
                          <div className="contact-avatar bookshelf-avatar" aria-hidden="true">
                            <img alt="" src={bookNoteIconUrl} />
                          </div>
                          <div>
                            <h3>{bookTitle(book, titlesByBookId[book.id])}</h3>
                            <p>{book.original_filename ?? t('bookshelf.untitled')}</p>
                          </div>
                        </div>
                        <div className="contact-row-side bookshelf-row-side">
                          <div className="contact-row-meta bookshelf-row-meta">
                            <span>{authorsByBookId[book.id]?.trim() || t('bookshelf.author.empty')}</span>
                          </div>
                          <div className="contact-tags bookshelf-row-tags">
                            {tags.length === 0 ? (
                              <span className="is-reserved-contact-tag">{t('bookshelf.tags.noTag')}</span>
                            ) : (
                              tags.map((tag) => <span key={tag}>{tag}</span>)
                            )}
                          </div>
                          <div className="bookshelf-row-menu-wrap" onClick={(event) => event.stopPropagation()}>
                            <button
                              aria-expanded={openMenuBookId === book.id}
                              aria-label={t('bookshelf.menu.open')}
                              className="bookshelf-row-menu-button"
                              onClick={() => setOpenMenuBookId((current) => current === book.id ? null : book.id)}
                              type="button"
                            >
                              <span aria-hidden="true">☰</span>
                            </button>
                            {openMenuBookId === book.id && (
                              <div className="bookshelf-row-menu" role="menu">
                                <button onClick={() => startEditBook(book)} role="menuitem" type="button">
                                  {t('bookshelf.menu.edit')}
                                </button>
                                <a href={book.url} rel="noreferrer" role="menuitem" target="_blank">
                                  {t('bookshelf.open')}
                                </a>
                                <button onClick={() => { void deleteBook(book) }} role="menuitem" type="button">
                                  {t('bookshelf.menu.delete')}
                                </button>
                              </div>
                            )}
                          </div>
                        </div>
                      </article>
                    )
                  })
                )}
              </div>
            </div>
          </div>
        </section>

        {editingBook !== null && (
          <div
            className="bookshelf-edit-backdrop"
            onPointerDown={(event) => {
              editBackdropPointerStartedRef.current = event.target === event.currentTarget
            }}
            onPointerUp={closeEditDialogFromBackdrop}
            role="presentation"
          >
            <form
              aria-labelledby="bookshelf-edit-heading"
              className="contact-panel bookshelf-edit-dialog"
              onClick={(event) => event.stopPropagation()}
              onSubmit={updateBookMetadata}
            >
              <div className="section-heading">
                <div>
                  <p>{t('bookshelf.menu.edit')}</p>
                  <h2 id="bookshelf-edit-heading">{bookTitle(editingBook, titlesByBookId[editingBook.id])}</h2>
                </div>
              </div>
              <label>
                <span>{t('bookshelf.title.label')}</span>
                <input
                  autoFocus
                  onChange={(event) => setTitleDraft(event.target.value)}
                  placeholder={t('bookshelf.title.placeholder')}
                  value={titleDraft}
                />
              </label>
              <label>
                <span>{t('bookshelf.author.label')}</span>
                <input
                  onChange={(event) => setAuthorDraft(event.target.value)}
                  placeholder={t('bookshelf.author.placeholder')}
                  value={authorDraft}
                />
              </label>
              <label>
                <span>{t('bookshelf.tags.edit')}</span>
                <input
                  onChange={(event) => setTagDraft(event.target.value)}
                  placeholder={t('bookshelf.tags.placeholder')}
                  value={tagDraft}
                />
              </label>
              <div className="bookshelf-edit-actions">
                <button type="button" onClick={() => setEditingBookId(null)}>{t('common.cancel')}</button>
                <button type="submit">{t('bookshelf.metadata.save')}</button>
              </div>
            </form>
          </div>
        )}
      </div>
    </main>
  )
}
