import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import {
  createPaperJournalIconSetting,
  deletePaperJournalIconSetting,
  listPaperJournalIconSettings,
  listPapers,
  updatePaperJournalIconSetting,
} from './phase3Api'
import type { Paper, PaperJournalIconSetting } from './phase3Api'
import { t } from './i18n'
import { imageUploadAccept, imageUploadContentType } from './imageUpload'
import { TopNav } from './navigation'

function normalizeJournalName(value: string) {
  return value.trim().replace(/\s+/g, ' ').toLowerCase()
}

function journalNameForPaper(paper: Paper) {
  return (paper.journal_text || paper.bibtex_entry?.journal || '').trim().replace(/\s+/g, ' ')
}

function journalIsCovered(journal: string, items: PaperJournalIconSetting[]) {
  const normalizedJournal = normalizeJournalName(journal)
  if (normalizedJournal === '') return true
  return items.some((item) => {
    const normalizedMatch = normalizeJournalName(item.match_journal)
    return normalizedMatch !== '' && normalizedJournal.includes(normalizedMatch)
  })
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = reader.result
      if (typeof result !== 'string') {
        reject(new Error('Failed to read file.'))
        return
      }
      resolve(result.includes(',') ? result.slice(result.indexOf(',') + 1) : result)
    }
    reader.onerror = () => reject(reader.error ?? new Error('Failed to read file.'))
    reader.readAsDataURL(file)
  })
}

export default function PaperJournalIconsView() {
  const [items, setItems] = useState<PaperJournalIconSetting[]>([])
  const [papers, setPapers] = useState<Paper[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [matchJournal, setMatchJournal] = useState('')
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editingMatchJournal, setEditingMatchJournal] = useState('')
  const [editingFile, setEditingFile] = useState<File | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  function loadItems() {
    setIsLoading(true)
    setError(null)
    Promise.all([listPaperJournalIconSettings(), listPapers()])
      .then(([nextItems, nextPapers]) => {
        setItems(nextItems)
        setPapers(nextPapers)
      })
      .catch((caught) => setError(caught instanceof Error ? caught.message : t('app.requestFailed')))
      .finally(() => setIsLoading(false))
  }

  useEffect(() => {
    loadItems()
  }, [])

  const journalCandidates = useMemo(() => {
    const seen = new Set<string>()
    return papers.flatMap((paper) => {
      const journal = journalNameForPaper(paper)
      const normalized = normalizeJournalName(journal)
      if (journal === '' || seen.has(normalized)) return []
      seen.add(normalized)
      return [journal]
    }).sort((a, b) => a.localeCompare(b))
  }, [papers])

  const nextUncoveredJournal = useMemo(() => (
    journalCandidates.find((journal) => !journalIsCovered(journal, items)) ?? ''
  ), [items, journalCandidates])

  useEffect(() => {
    if (matchJournal.trim() === '' && nextUncoveredJournal !== '') {
      setMatchJournal(nextUncoveredJournal)
    }
  }, [matchJournal, nextUncoveredJournal])

  function startEdit(item: PaperJournalIconSetting) {
    setEditingId(item.id)
    setEditingMatchJournal(item.match_journal)
    setEditingFile(null)
    setNotice(null)
    setError(null)
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (selectedFile === null) return
    setIsSubmitting(true)
    setError(null)
    setNotice(null)
    try {
      const created = await createPaperJournalIconSetting({
        match_journal: matchJournal,
        icon_filename: selectedFile.name,
        icon_content_type: imageUploadContentType(selectedFile),
        icon_data_base64: await fileToBase64(selectedFile),
      })
      const nextItems = [...items, created].sort((a, b) => a.match_journal.localeCompare(b.match_journal))
      setItems(nextItems)
      setMatchJournal(journalCandidates.find((journal) => !journalIsCovered(journal, nextItems)) ?? '')
      setSelectedFile(null)
      setNotice(t('papers.journalIcons.created'))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t('app.requestFailed'))
    } finally {
      setIsSubmitting(false)
    }
  }

  async function handleUpdate(item: PaperJournalIconSetting) {
    setBusyId(item.id)
    setError(null)
    setNotice(null)
    try {
      const payload: Parameters<typeof updatePaperJournalIconSetting>[1] = {
        match_journal: editingMatchJournal,
      }
      if (editingFile !== null) {
        payload.icon_filename = editingFile.name
        payload.icon_content_type = imageUploadContentType(editingFile)
        payload.icon_data_base64 = await fileToBase64(editingFile)
      }
      const updated = await updatePaperJournalIconSetting(item.id, payload)
      setItems((current) => current.map((candidate) => candidate.id === item.id ? updated : candidate))
      setEditingId(null)
      setNotice(t('papers.journalIcons.updated'))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t('app.requestFailed'))
    } finally {
      setBusyId(null)
    }
  }

  async function handleDelete(item: PaperJournalIconSetting) {
    if (!window.confirm(t('papers.journalIcons.deleteConfirm', { journal: item.match_journal }))) return
    setBusyId(item.id)
    setError(null)
    setNotice(null)
    try {
      await deletePaperJournalIconSetting(item.id)
      setItems((current) => current.filter((candidate) => candidate.id !== item.id))
      setNotice(t('papers.journalIcons.deleted'))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t('app.requestFailed'))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <main className="app-shell">
      <div className="case-shell">
        <header className="maintenance-header">
          <div>
            <p>{t('app.name')}</p>
            <h1>{t('papers.journalIcons.heading')}</h1>
          </div>
          <TopNav
            ariaLabelKey="papers.navigation"
            items={[
              { href: '/papers', labelKey: 'nav.papers' },
              { href: '/', labelKey: 'top.heading' },
            ]}
          />
        </header>
        <section className="file-icons-panel">
          {error !== null && <p className="contact-error" role="alert">{error}</p>}
          {notice !== null && <p className="contact-notice">{notice}</p>}
          <div className="file-icons-table">
            <div className="file-icons-header" role="row">
              <span>{t('papers.journalIcons.icon')}</span>
              <span>{t('papers.journalIcons.matchJournal')}</span>
              <span>{t('papers.journalIcons.actions')}</span>
            </div>
            {isLoading ? (
              <p className="mail-empty">{t('session.checking.label')}</p>
            ) : items.length === 0 ? (
              <p className="mail-empty">{t('papers.journalIcons.empty')}</p>
            ) : (
              items.map((item) => (
                <div className="file-icons-row" key={item.id} role="row">
                  <div className="file-icon-preview-cell">
                    {item.icon_url != null && item.icon_url !== '' && <img alt="" aria-hidden="true" src={item.icon_url} />}
                    {editingId === item.id && (
                      <input accept={imageUploadAccept} onChange={(event) => setEditingFile(event.target.files?.[0] ?? null)} type="file" />
                    )}
                  </div>
                  <div>
                    {editingId === item.id ? (
                      <input onChange={(event) => setEditingMatchJournal(event.target.value)} value={editingMatchJournal} />
                    ) : (
                      <span>{item.match_journal}</span>
                    )}
                  </div>
                  <div className="file-icons-actions">
                    {editingId === item.id ? (
                      <>
                        <button disabled={busyId === item.id} onClick={() => void handleUpdate(item)} type="button">{t('common.save')}</button>
                        <button disabled={busyId === item.id} onClick={() => setEditingId(null)} type="button">{t('common.cancel')}</button>
                      </>
                    ) : (
                      <>
                        <button onClick={() => startEdit(item)} type="button">{t('common.edit')}</button>
                        <button disabled={busyId === item.id} onClick={() => void handleDelete(item)} type="button">{t('bookshelf.menu.delete')}</button>
                      </>
                    )}
                  </div>
                </div>
              ))
            )}
            <form className="file-icons-row file-icons-create-row" onSubmit={handleCreate}>
              <div>
                <input accept={imageUploadAccept} onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)} type="file" />
              </div>
              <div>
                <input
                  list="paper-journal-icon-candidates"
                  onChange={(event) => setMatchJournal(event.target.value)}
                  placeholder="Nature"
                  value={matchJournal}
                />
                <datalist id="paper-journal-icon-candidates">
                  {journalCandidates.map((journal) => <option key={journal} value={journal} />)}
                </datalist>
              </div>
              <div className="file-icons-actions">
                <button disabled={selectedFile === null || matchJournal.trim() === '' || isSubmitting} type="submit">
                  {t('papers.journalIcons.register')}
                </button>
              </div>
            </form>
          </div>
        </section>
      </div>
    </main>
  )
}
