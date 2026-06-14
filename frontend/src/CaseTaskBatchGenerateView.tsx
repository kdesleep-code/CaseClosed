import { useEffect, useState } from 'react'
import { t } from './i18n'
import { TopNav, navigateTo } from './navigation'
import type { StorageObject } from './phase3Api'
import { getCase } from './phase7Api'
import type { CaseDetail } from './phase7Api'
import { prefillTasksFromHandover } from './phase8Api'
import StorageBrowser from './StorageBrowser'

function describeError(error: unknown) {
  return error instanceof Error ? error.message : t('storage.requestFailed')
}

export default function CaseTaskBatchGenerateView({ caseId }: { caseId: string }) {
  const [detail, setDetail] = useState<CaseDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selectedObjects, setSelectedObjects] = useState<StorageObject[]>([])
  const [additionalPrompt, setAdditionalPrompt] = useState('')
  const [isGenerating, setIsGenerating] = useState(false)

  useEffect(() => {
    let isMounted = true
    setError(null)
    getCase(caseId)
      .then((nextDetail) => {
        if (!isMounted) return
        setDetail(nextDetail)
      })
      .catch((requestError) => {
        if (!isMounted) return
        setError(describeError(requestError))
      })
    return () => {
      isMounted = false
    }
  }, [caseId])

  function toggleSelectedObject(object: StorageObject) {
    setSelectedObjects((currentObjects) => {
      if (currentObjects.some((currentObject) => currentObject.id === object.id)) {
        return currentObjects.filter((currentObject) => currentObject.id !== object.id)
      }
      return [...currentObjects, object]
    })
  }

  async function handleGenerate() {
    if (detail === null || selectedObjects.length === 0 || isGenerating) return
    setIsGenerating(true)
    setError(null)
    try {
      const result = await prefillTasksFromHandover({
        case_id: detail.case.id,
        storage_object_ids: selectedObjects.map((object) => object.id),
        additional_prompt: additionalPrompt.trim() || null,
      })
      if (result.suggestions.length === 0) {
        setError(t('cases.taskBatch.noSuggestions'))
        return
      }
      const batchKey = `task_batch_${result.llm_run_id}`
      window.sessionStorage.setItem(
        batchKey,
        JSON.stringify({
          case_id: detail.case.id,
          case_name: detail.case.name,
          llm_run_id: result.llm_run_id,
          source_file_ids: selectedObjects.map((object) => object.id),
          suggestions: result.suggestions,
        }),
      )
      navigateTo(
        `/tasks/new?case_id=${encodeURIComponent(detail.case.id)}&batch_key=${encodeURIComponent(
          batchKey,
        )}&batch_index=0`,
      )
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsGenerating(false)
    }
  }

  return (
    <main className="app-shell">
      <div className="task-shell">
        <header className="maintenance-header">
          <div>
            <p>{t('app.name')}</p>
            <h1>{t('cases.taskBatch.heading')}</h1>
          </div>
          <TopNav
            ariaLabelKey="tasks.navigation"
            items={[
              {
                href: `/cases/${encodeURIComponent(caseId)}`,
                labelKey: 'cases.detailHeading',
              },
              { href: '/cases', labelKey: 'cases.heading' },
              { href: '/tasks', labelKey: 'tasks.heading' },
              { href: '/', labelKey: 'top.heading' },
            ]}
          />
        </header>

        {error !== null && (
          <div className="mail-feedback">
            <p role="alert">{error}</p>
          </div>
        )}

        {detail === null ? (
          <section className="mail-panel task-detail-panel">
            <p>{t('cases.loading')}</p>
          </section>
        ) : (
          <div className="task-batch-generate-layout">
            <section className="mail-panel task-detail-panel task-batch-source-panel">
              <div className="section-heading">
                <div>
                  <h2>{detail.case.name}</h2>
                  <p>{t('cases.taskBatch.body')}</p>
                </div>
              </div>
              <StorageBrowser
                body={t('cases.taskBatch.storageBody')}
                caseId={detail.case.id}
                deleteMode="case"
                heading={t('cases.taskBatch.storageHeading')}
                onOpenObject={toggleSelectedObject}
                panelClassName="case-storage-drop-zone"
                rootDirectoryId={detail.case.handover_storage_directory_id}
                rootLabel={t('cases.taskBatch.handoverRoot')}
                showPath
              />
            </section>

            <aside className="task-batch-selection-column">
              <section className="mail-panel">
                <div className="section-heading">
                  <div>
                    <h2>{t('cases.taskBatch.selectedHeading')}</h2>
                    <p>{t('cases.taskBatch.selectedCount', { count: selectedObjects.length })}</p>
                  </div>
                </div>
                {selectedObjects.length === 0 ? (
                  <p>{t('cases.taskBatch.selectedEmpty')}</p>
                ) : (
                  <div className="task-batch-selected-list">
                    {selectedObjects.map((object) => (
                      <button
                        className="task-batch-selected-item"
                        key={object.id}
                        onClick={() => toggleSelectedObject(object)}
                        type="button"
                      >
                        <span>{object.original_filename ?? object.id}</span>
                        <small>{t('cases.taskBatch.selectedRemove')}</small>
                      </button>
                    ))}
                  </div>
                )}
              </section>
              <section className="mail-panel">
                <div className="section-heading">
                  <div>
                    <h2>{t('cases.taskBatch.promptHeading')}</h2>
                    <p>{t('cases.taskBatch.promptBody')}</p>
                  </div>
                </div>
                <label className="task-batch-prompt-field">
                  <span>{t('cases.taskBatch.promptLabel')}</span>
                  <textarea
                    onChange={(event) => setAdditionalPrompt(event.target.value)}
                    placeholder={t('cases.taskBatch.promptPlaceholder')}
                    rows={7}
                    value={additionalPrompt}
                  />
                </label>
                <button
                  className="case-gadget-action task-batch-generate-button"
                  disabled={selectedObjects.length === 0 || isGenerating}
                  onClick={() => {
                    void handleGenerate()
                  }}
                  type="button"
                >
                  {isGenerating ? t('cases.taskBatch.generating') : t('cases.taskBatch.generate')}
                </button>
              </section>
            </aside>
          </div>
        )}
      </div>
    </main>
  )
}
