import { useEffect, useMemo, useRef, useState } from 'react'
import type { ChangeEvent, FormEvent, PointerEvent } from 'react'
import { deletePaper, listPapers, updatePaper, uploadPaper } from './phase3Api'
import type { Paper } from './phase3Api'
import { t } from './i18n'
import { navigateTo, TopNav } from './navigation'

const bookshelfTagHierarchyStorageKey = 'caseclosed.bookshelf.tagHierarchy'
const paperTabsStorageKey = 'caseclosed.papers.tabs'
const noTagFilterValue = '__caseclosed_papers_no_tag__'
const maxCustomTabs = 4
const maxCustomTabNameLength = 12

type PaperCustomTab = {
  id: string
  label: string
  expression: string
}

function isPaperFile(file: File) {
  return file.name.trim().toLowerCase().endsWith('.pdf')
}

function isCitationFile(file: File) {
  const filename = file.name.trim().toLowerCase()
  return filename.endsWith('.bib') || filename.endsWith('.bibtex') || filename.endsWith('.ris') || filename.endsWith('.nbib')
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
    if (trimmedTag === '' || seen.has(normalizedTag)) return
    seen.add(normalizedTag)
    result.push(trimmedTag)
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

function readStoredTabs() {
  try {
    const rawValue = window.localStorage.getItem(paperTabsStorageKey)
    if (rawValue === null) return []
    const parsed = JSON.parse(rawValue)
    if (!Array.isArray(parsed)) return []
    return parsed.flatMap((item): PaperCustomTab[] => {
      if (item === null || typeof item !== 'object') return []
      const value = item as Partial<PaperCustomTab>
      if (typeof value.id !== 'string' || typeof value.label !== 'string' || typeof value.expression !== 'string') return []
      return [{ id: value.id, label: value.label, expression: value.expression }]
    })
  } catch {
    return []
  }
}

function writeStoredTabs(tabs: PaperCustomTab[]) {
  window.localStorage.setItem(paperTabsStorageKey, JSON.stringify(tabs))
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

function paperUrl(paper: Paper) {
  return paper.storage_object?.url ?? null
}

function paperAuthorSummary(authorsText: string) {
  const trimmedAuthors = authorsText.trim()
  const separator = /\s+and\s+/i.test(trimmedAuthors) ? /\s+and\s+/i : trimmedAuthors.includes(';') ? /;/ : /,/
  const authors = trimmedAuthors
    .split(separator)
    .map((author) => author.trim())
    .filter(Boolean)
  if (authors.length === 0) return t('papers.author.empty')
  if (authors.length === 1) return authors[0]
  return `${authors[0]}, ... ,${authors[authors.length - 1]}`
}

export default function PaperShelfView() {
  const [papers, setPapers] = useState<Paper[]>([])
  const tagParents = useMemo(() => readStoredTagHierarchy(), [])
  const [customTabs, setCustomTabs] = useState<PaperCustomTab[]>(() => readStoredTabs())
  const [selectedTagFilter, setSelectedTagFilter] = useState<string | null>(null)
  const [activeTabId, setActiveTabId] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [editingPaperId, setEditingPaperId] = useState<string | null>(null)
  const [openMenuPaperId, setOpenMenuPaperId] = useState<string | null>(null)
  const [titleDraft, setTitleDraft] = useState('')
  const [authorsDraft, setAuthorsDraft] = useState('')
  const [tagDraft, setTagDraft] = useState('')
  const [bibtexDraft, setBibtexDraft] = useState('')
  const [tabName, setTabName] = useState('')
  const [tabExpression, setTabExpression] = useState('')
  const [isTabEditorOpen, setIsTabEditorOpen] = useState(false)
  const [feedback, setFeedback] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const editBackdropPointerStartedRef = useRef(false)
  const [isLoading, setIsLoading] = useState(true)
  const [isUploading, setIsUploading] = useState(false)
  const [isUploadFormOpen, setIsUploadFormOpen] = useState(false)
  const [uploadPdfFile, setUploadPdfFile] = useState<File | null>(null)
  const [uploadBibtexFile, setUploadBibtexFile] = useState<File | null>(null)

  function loadPapers() {
    setIsLoading(true)
    setError(null)
    listPapers()
      .then((items) => setPapers(items))
      .catch((caught) => setError(caught instanceof Error ? caught.message : t('app.requestFailed')))
      .finally(() => setIsLoading(false))
  }

  useEffect(() => {
    loadPapers()
  }, [])

  useEffect(() => {
    writeStoredTabs(customTabs)
  }, [customTabs])

  const tagCounts = useMemo(() => {
    const counts = new Map<string, number>()
    papers.forEach((paper) => {
      tagsWithAncestors(paper.tags, tagParents).forEach((tag) => {
        counts.set(tag, (counts.get(tag) ?? 0) + 1)
      })
    })
    return [...counts.entries()].sort((left, right) => left[0].localeCompare(right[0]))
  }, [papers, tagParents])

  const noTagCount = useMemo(() => papers.filter((paper) => paper.tags.length === 0).length, [papers])

  const visiblePapers = useMemo(() => {
    const queryTerms = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
    const activeTab = customTabs.find((tab) => tab.id === activeTabId) ?? null
    return papers
      .filter((paper) => {
        const effectiveTags = tagsWithAncestors(paper.tags, tagParents)
        if (selectedTagFilter === noTagFilterValue && paper.tags.length !== 0) return false
        if (selectedTagFilter !== null && selectedTagFilter !== noTagFilterValue && !effectiveTags.some((tag) => normalizeTag(tag) === normalizeTag(selectedTagFilter))) return false
        if (activeTab !== null && !customTabMatches(effectiveTags, activeTab.expression)) return false
        if (queryTerms.length === 0) return true
        const searchableText = [
          paper.title,
          paper.authors_text,
          paper.bibtex,
          paper.storage_object?.original_filename ?? '',
          effectiveTags.join(' '),
        ].join(' ').toLowerCase()
        return queryTerms.every((term) => searchableText.includes(term))
      })
      .toSorted((first, second) => first.title.localeCompare(second.title))
  }, [activeTabId, customTabs, papers, query, selectedTagFilter, tagParents])

  const activeListTabId = activeTabId === null ? (isTabEditorOpen ? 'add' : 'all') : activeTabId
  const editingPaper = editingPaperId === null ? null : papers.find((paper) => paper.id === editingPaperId) ?? null

  function handlePdfFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null
    setFeedback(null)
    setError(null)
    if (file !== null && !isPaperFile(file)) {
      setUploadPdfFile(null)
      setError(t('papers.upload.pdfOnly'))
      return
    }
    setUploadPdfFile(file)
  }

  function handleBibtexFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null
    setFeedback(null)
    setError(null)
    if (file !== null && !isCitationFile(file)) {
      setUploadBibtexFile(null)
      setError(t('papers.upload.bibtexOnly'))
      return
    }
    setUploadBibtexFile(file)
  }

  async function submitPaperUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    setFeedback(null)
    setError(null)
    if (uploadPdfFile === null || uploadBibtexFile === null) {
      setError(t('papers.upload.pdfAndBibtexOnly'))
      return
    }
    setIsUploading(true)
    try {
      const response = await uploadPaper(uploadPdfFile, uploadBibtexFile)
      setPapers((current) => [...current, response.paper])
      setFeedback(t('papers.upload.done', { filename: uploadPdfFile.name }))
      setUploadPdfFile(null)
      setUploadBibtexFile(null)
      form.reset()
      setIsUploadFormOpen(false)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t('papers.upload.failed'))
    } finally {
      setIsUploading(false)
    }
  }

  function startEditPaper(paper: Paper) {
    setEditingPaperId(paper.id)
    setTitleDraft(paper.title)
    setAuthorsDraft(paper.authors_text)
    setTagDraft(paper.tags.join(', '))
    setBibtexDraft(paper.bibtex)
    setOpenMenuPaperId(null)
    setFeedback(null)
    setError(null)
  }

  function closeEditDialogFromBackdrop(event: PointerEvent<HTMLDivElement>) {
    const startedOnBackdrop = editBackdropPointerStartedRef.current
    editBackdropPointerStartedRef.current = false
    if (!startedOnBackdrop || event.target !== event.currentTarget) return
    setEditingPaperId(null)
  }

  async function updatePaperMetadata(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (editingPaper === null) return
    const nextTitle = titleDraft.trim()
    if (nextTitle === '') return
    setFeedback(null)
    setError(null)
    try {
      const updatedPaper = await updatePaper(editingPaper.id, {
        title: nextTitle,
        authors_text: authorsDraft,
        bibtex: bibtexDraft,
        tags: parseTags(tagDraft),
      })
      setPapers((current) => current.map((paper) => paper.id === updatedPaper.id ? updatedPaper : paper))
      setEditingPaperId(null)
      setFeedback(t('papers.metadata.saved'))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t('app.requestFailed'))
    }
  }

  async function removePaper(paper: Paper) {
    if (!window.confirm(t('papers.delete.confirm', { title: paper.title }))) return
    setOpenMenuPaperId(null)
    setFeedback(null)
    setError(null)
    try {
      await deletePaper(paper.id)
      setPapers((current) => current.filter((item) => item.id !== paper.id))
      setFeedback(t('papers.delete.done', { title: paper.title }))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t('app.requestFailed'))
    }
  }

  function createCustomTab(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const expression = tabExpression.trim()
    const label = (tabName.trim() || expression).slice(0, maxCustomTabNameLength)
    if (label === '' || expression === '') return
    const nextTab = { id: `papers_tab_${Date.now()}`, label, expression }
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
    setCustomTabs(customTabs.filter((tab) => tab.id !== tabId))
    setActiveTabId(null)
    setIsTabEditorOpen(false)
  }

  return (
    <main className="app-shell">
      <div className="contacts-shell bookshelf-shell papers-shell">
        <header className="contacts-header">
          <div>
            <p>{t('app.name')}</p>
            <h1>{t('papers.heading')}</h1>
          </div>
          <TopNav
            ariaLabelKey="papers.navigation"
            items={[
              { href: '/', labelKey: 'top.heading' },
              { href: '/bookshelf', labelKey: 'nav.bookshelf' },
              { href: '/files', labelKey: 'nav.files' },
              { href: '/tasks', labelKey: 'nav.tasks' },
            ]}
          />
        </header>

        {error !== null && <p className="contact-error" role="alert">{error}</p>}
        {feedback !== null && <p className="contact-notice">{feedback}</p>}

        <section aria-labelledby="papers-tools-heading" className="contact-panel contact-tools-panel">
          <div className="section-heading bookshelf-tools-heading-row">
            <h2 id="papers-tools-heading">{t('papers.tools.heading')}</h2>
            <div className="paper-tools-actions">
              <button
                aria-expanded={isUploadFormOpen}
                onClick={() => {
                  setIsUploadFormOpen((current) => !current)
                  setUploadPdfFile(null)
                  setUploadBibtexFile(null)
                  setFeedback(null)
                  setError(null)
                }}
                type="button"
              >
                {isUploadFormOpen ? t('common.cancel') : t('papers.upload.add')}
              </button>
              <button onClick={() => navigateTo('/paper-journal-icons')} type="button">{t('papers.journalIcons.open')}</button>
              <button onClick={() => navigateTo('/bookshelf/tag-hierarchy')} type="button">{t('bookshelf.tagHierarchy.edit')}</button>
            </div>
          </div>
          {isUploadFormOpen && (
            <form className="paper-upload-form" onSubmit={(event) => { void submitPaperUpload(event) }}>
              <label>
                <span>{t('papers.upload.pdf')}</span>
                <input
                  accept=".pdf,application/pdf"
                  disabled={isUploading}
                  onChange={handlePdfFileChange}
                  type="file"
                />
              </label>
              <label>
                <span>{t('papers.upload.bibtex')}</span>
                <input
                  accept=".bib,.bibtex,.ris,.nbib,text/plain,application/x-research-info-systems,application/x-nbib"
                  disabled={isUploading}
                  onChange={handleBibtexFileChange}
                  type="file"
                />
              </label>
              <button
                className={`button-loading-dot${isUploading ? ' is-loading' : ''}`}
                disabled={isUploading || uploadPdfFile === null || uploadBibtexFile === null}
                type="submit"
              >
                {t('papers.upload.submit')}
              </button>
            </form>
          )}
          <div className="contact-tools bookshelf-tools">
            <div aria-label={t('papers.search.region')} role="search">
              <label>
                <span>{t('papers.search')}</span>
                <input
                  aria-label={t('papers.search')}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder={t('papers.searchPlaceholder')}
                  type="search"
                  value={query}
                />
              </label>
              <div
                aria-label={t('papers.tags.filter')}
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
          </div>
        </section>

        <section className="contact-list-workspace bookshelf-list-workspace">
          <div aria-label={t('papers.list.views')} className="contact-list-tabs" role="tablist">
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
            <div className="contact-list-panel" role="tabpanel" aria-label={t('papers.list.heading')}>
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
                ) : visiblePapers.length === 0 ? (
                  <p className="empty-state">{t('papers.empty.body')}</p>
                ) : (
                  visiblePapers.map((paper) => {
                    const url = paperUrl(paper)
                    const detailHref = '/papers/' + encodeURIComponent(paper.id)
                    return (
                      <article
                        className="contact-row bookshelf-row papers-row"
                        key={paper.id}
                        onClick={() => navigateTo(detailHref)}
                      >
                        <div className="papers-row-icon" aria-hidden="true">
                          {paper.journal_icon_url !== null && paper.journal_icon_url !== '' ? (
                            <img alt="" src={paper.journal_icon_url} />
                          ) : (
                            <span>{t('papers.journalIcons.placeholder')}</span>
                          )}
                        </div>
                        <div className="papers-row-main">
                          <h3>{paper.title}</h3>
                          <div className="papers-row-subline">
                            <span>{paperAuthorSummary(paper.authors_text)}</span>
                            {paper.journal_text.trim() !== '' && <span>{paper.journal_text}</span>}
                            {paper.bibtex_entry?.year.trim() !== '' && (
                              <span>{paper.bibtex_entry?.year}</span>
                            )}
                            <div className="contact-tags bookshelf-row-tags papers-row-tags">
                              {paper.tags.length === 0 ? (
                                <span className="is-reserved-contact-tag">{t('bookshelf.tags.noTag')}</span>
                              ) : (
                                paper.tags.map((tag) => <span key={tag}>{tag}</span>)
                              )}
                            </div>
                          </div>
                        </div>
                        <div className="bookshelf-row-menu-wrap" onClick={(event) => event.stopPropagation()}>
                            <button
                              aria-expanded={openMenuPaperId === paper.id}
                              aria-label={t('papers.menu.open')}
                              className="bookshelf-row-menu-button"
                              onClick={() => setOpenMenuPaperId((current) => current === paper.id ? null : paper.id)}
                              type="button"
                            >
                              <span aria-hidden="true">☰</span>
                            </button>
                            {openMenuPaperId === paper.id && (
                              <div className="bookshelf-row-menu" role="menu">
                                <button onClick={() => startEditPaper(paper)} role="menuitem" type="button">
                                  {t('bookshelf.menu.edit')}
                                </button>
                                {url !== null && (
                                  <button onClick={() => navigateTo(detailHref)} role="menuitem" type="button">
                                    {t('papers.open')}
                                  </button>
                                )}
                                <button onClick={() => { void removePaper(paper) }} role="menuitem" type="button">
                                  {t('bookshelf.menu.delete')}
                                </button>
                              </div>
                            )}
                          </div>
                      </article>
                    )
                  })
                )}
              </div>
            </div>
          </div>
        </section>

        {editingPaper !== null && (
          <div
            className="bookshelf-edit-backdrop"
            onPointerDown={(event) => {
              editBackdropPointerStartedRef.current = event.target === event.currentTarget
            }}
            onPointerUp={closeEditDialogFromBackdrop}
            role="presentation"
          >
            <form
              aria-labelledby="papers-edit-heading"
              className="contact-panel bookshelf-edit-dialog papers-edit-dialog"
              onClick={(event) => event.stopPropagation()}
              onSubmit={updatePaperMetadata}
            >
              <div className="section-heading">
                <div>
                  <p>{t('bookshelf.menu.edit')}</p>
                  <h2 id="papers-edit-heading">{editingPaper.title}</h2>
                </div>
              </div>
              <label>
                <span>{t('papers.title.label')}</span>
                <input
                  autoFocus
                  onChange={(event) => setTitleDraft(event.target.value)}
                  placeholder={t('papers.title.placeholder')}
                  value={titleDraft}
                />
              </label>
              <label>
                <span>{t('papers.author.label')}</span>
                <input
                  onChange={(event) => setAuthorsDraft(event.target.value)}
                  placeholder={t('papers.author.placeholder')}
                  value={authorsDraft}
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
              <label>
                <span>{t('papers.bibtex.label')}</span>
                <textarea
                  onChange={(event) => setBibtexDraft(event.target.value)}
                  placeholder={t('papers.bibtex.placeholder')}
                  value={bibtexDraft}
                />
              </label>
              <div className="bookshelf-edit-actions">
                <button type="button" onClick={() => setEditingPaperId(null)}>{t('common.cancel')}</button>
                <button type="submit">{t('bookshelf.metadata.save')}</button>
              </div>
            </form>
          </div>
        )}
      </div>
    </main>
  )
}
