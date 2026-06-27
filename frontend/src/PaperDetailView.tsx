import { useEffect, useMemo, useState } from 'react'
import { readPaper, updatePaper } from './phase3Api'
import type { Paper } from './phase3Api'
import { t } from './i18n'
import { TopNav } from './navigation'

type PaperDetailViewProps = {
  paperId: string
}

function paperPdfUrl(paper: Paper | null) {
  return paper?.storage_object?.url ?? null
}

function joinAuthors(paper: Paper) {
  const bibtexAuthors = paper.bibtex_entry?.authors ?? []
  if (bibtexAuthors.length > 0) return bibtexAuthors.join(', ')
  return paper.authors_text.trim()
}

function metadataValue(value: string | undefined | null) {
  return value?.trim() ?? ''
}

export default function PaperDetailView({ paperId }: PaperDetailViewProps) {
  const [paper, setPaper] = useState<Paper | null>(null)
  const [summaryDraft, setSummaryDraft] = useState('')
  const [isEditingSummary, setIsEditingSummary] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    let isActive = true
    setIsLoading(true)
    setError(null)
    readPaper(paperId)
      .then((nextPaper) => {
        if (!isActive) return
        setPaper(nextPaper)
        setSummaryDraft(nextPaper.summary)
      })
      .catch((caught) => {
        if (!isActive) return
        setError(caught instanceof Error ? caught.message : t('app.requestFailed'))
      })
      .finally(() => {
        if (isActive) setIsLoading(false)
      })
    return () => {
      isActive = false
    }
  }, [paperId])

  const pdfUrl = useMemo(() => paperPdfUrl(paper), [paper])

  async function saveSummary() {
    if (paper === null) return
    setIsSaving(true)
    setError(null)
    setNotice(null)
    try {
      const nextPaper = await updatePaper(paper.id, { summary: summaryDraft })
      setPaper(nextPaper)
      setSummaryDraft(nextPaper.summary)
      setIsEditingSummary(false)
      setNotice(t('papers.detail.summarySaved'))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t('app.requestFailed'))
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <main className="app-shell">
      <div className="contacts-shell paper-detail-shell">
        <header className="contacts-header">
          <div>
            <p>{t('app.name')}</p>
            <h1>{paper?.title ?? t('papers.heading')}</h1>
          </div>
          <TopNav
            ariaLabelKey="papers.navigation"
            items={[
              { href: '/papers', labelKey: 'nav.papers' },
              { href: '/', labelKey: 'top.heading' },
              { href: '/bookshelf', labelKey: 'nav.bookshelf' },
              { href: '/files', labelKey: 'nav.files' },
            ]}
          />
        </header>

        {error !== null && <p className="contact-error" role="alert">{error}</p>}
        {notice !== null && <p className="contact-notice">{notice}</p>}

        {isLoading ? (
          <section className="contact-panel paper-detail-panel">
            <p className="empty-state">{t('common.loading')}</p>
          </section>
        ) : paper === null ? (
          <section className="contact-panel paper-detail-panel">
            <p className="empty-state">{t('papers.detail.notFound')}</p>
          </section>
        ) : (
          <>
            <section className="contact-panel paper-detail-panel paper-detail-info">
              <div className="section-heading paper-detail-heading-row">
                <div>
                  <p>{t('papers.detail.metadata')}</p>
                  <h2>{paper.title}</h2>
                </div>
                {pdfUrl !== null && (
                  <a className="paper-detail-open-pdf" href={pdfUrl} rel="noreferrer" target="_blank">
                    {t('papers.openPdf')}
                  </a>
                )}
              </div>

              <dl className="paper-detail-metadata">
                {metadataValue(joinAuthors(paper)) !== '' && (
                  <div className="paper-detail-meta-card paper-detail-meta-card-wide paper-detail-meta-authors">
                    <dt>{t('papers.author.label')}</dt>
                    <dd>{joinAuthors(paper)}</dd>
                  </div>
                )}
                {metadataValue(paper.journal_text || paper.bibtex_entry?.journal) !== '' && (
                  <div className="paper-detail-meta-card paper-detail-meta-journal">
                    <dt>{t('papers.detail.journal')}</dt>
                    <dd>{paper.journal_text || paper.bibtex_entry?.journal}</dd>
                  </div>
                )}
                {metadataValue(paper.bibtex_entry?.year) !== '' && (
                  <div className="paper-detail-meta-card paper-detail-meta-compact">
                    <dt>{t('papers.detail.year')}</dt>
                    <dd>{paper.bibtex_entry?.year}</dd>
                  </div>
                )}
                {metadataValue(paper.bibtex_entry?.doi) !== '' && (
                  <div className="paper-detail-meta-card paper-detail-meta-card-wide paper-detail-meta-identifier">
                    <dt>{t('papers.detail.doi')}</dt>
                    <dd>
                      <a
                        href={paper.bibtex_entry?.doi.startsWith('http')
                          ? paper.bibtex_entry.doi
                          : `https://doi.org/${paper.bibtex_entry?.doi}`}
                        rel="noreferrer"
                        target="_blank"
                      >
                        {paper.bibtex_entry?.doi}
                      </a>
                    </dd>
                  </div>
                )}
              </dl>

              <section className="paper-detail-summary-section">
                <div className="section-heading paper-detail-summary-heading">
                  <div>
                    <p>{t('papers.detail.summaryLabel')}</p>
                    <h2>{t('papers.detail.summaryHeading')}</h2>
                  </div>
                  {!isEditingSummary && (
                    <button onClick={() => setIsEditingSummary(true)} type="button">
                      {t('common.edit')}
                    </button>
                  )}
                </div>
                {isEditingSummary ? (
                  <div className="paper-detail-summary-editor">
                    <textarea
                      autoFocus
                      onChange={(event) => setSummaryDraft(event.target.value)}
                      placeholder={t('papers.detail.summaryPlaceholder')}
                      value={summaryDraft}
                    />
                    <div>
                      <button
                        onClick={() => {
                          setSummaryDraft(paper.summary)
                          setIsEditingSummary(false)
                        }}
                        type="button"
                      >
                        {t('common.cancel')}
                      </button>
                      <button
                        className={`button-loading-dot${isSaving ? ' is-loading' : ''}`}
                        disabled={isSaving}
                        onClick={() => { void saveSummary() }}
                        type="button"
                      >
                        {t('common.save')}
                      </button>
                    </div>
                  </div>
                ) : paper.summary.trim() === '' ? (
                  <p className="paper-detail-summary-empty">{t('papers.detail.summaryEmpty')}</p>
                ) : (
                  <p className="paper-detail-summary-text">{paper.summary}</p>
                )}
              </section>

              {paper.bibtex.trim() !== '' && (
                <details className="paper-detail-bibtex">
                  <summary>{t('papers.bibtex.label')}</summary>
                  <pre>{paper.bibtex}</pre>
                </details>
              )}
            </section>

            <section className="contact-panel paper-detail-reader-panel">
              <div className="section-heading">
                <div>
                  <p>{t('papers.detail.readerLabel')}</p>
                  <h2>{t('papers.detail.readerHeading')}</h2>
                </div>
              </div>
              {pdfUrl === null ? (
                <p className="empty-state">{t('papers.detail.noPdf')}</p>
              ) : (
                <iframe className="paper-detail-reader" src={pdfUrl} title={paper.title} />
              )}
            </section>
          </>
        )}
      </div>
    </main>
  )
}
