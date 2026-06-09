import { useEffect, useMemo, useState } from 'react'
import { AppLink } from './navigation'
import { t } from './i18n'
import { isCaseOpenForSuggestion, listCases } from './phase7Api'
import type { CaseItem } from './phase7Api'
import { listTasks } from './phase8Api'
import type { TaskItem } from './phase8Api'

type TaskSortMode = 'priority' | 'due_asc' | 'due_desc' | 'updated_desc'
type TaskTab = 'inbox' | 'done' | 'not_started' | 'archived'

const ARCHIVE_AFTER_MS = 14 * 24 * 60 * 60 * 1000

function describeError(error: unknown) {
  return error instanceof Error ? error.message : t('tasks.requestFailed')
}

function formatShortDate(value: string | null) {
  if (value === null) return t('tasks.noDueDate')
  return value.slice(0, 10)
}

function todayKey() {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${day}`
}

function isTaskClosed(task: TaskItem) {
  return task.status === 'completed' || task.status === 'canceled'
}

function taskClosedAt(task: TaskItem) {
  return task.completed_at ?? task.canceled_at
}

function isTaskArchived(task: TaskItem) {
  const closedAt = taskClosedAt(task)
  if (closedAt === null) return false
  return Date.now() - new Date(closedAt).getTime() >= ARCHIVE_AFTER_MS
}

function isTaskNotStartedByDate(task: TaskItem) {
  if (isTaskClosed(task)) return false
  const today = todayKey()
  if (task.case_open_when_date !== null && task.case_open_when_date.slice(0, 10) > today) {
    return true
  }
  return task.start_at !== null && task.start_at.slice(0, 10) > today
}

function taskBelongsToTab(task: TaskItem, tab: TaskTab) {
  if (tab === 'archived') return isTaskArchived(task)
  if (tab === 'not_started') return isTaskNotStartedByDate(task)
  if (tab === 'done') return isTaskClosed(task) && !isTaskArchived(task)
  return !isTaskClosed(task) && !isTaskNotStartedByDate(task)
}

function taskStatusLabel(status: string) {
  if (status === 'not_started') return t('tasks.status.notStarted')
  if (status === 'in_progress') return t('tasks.status.inProgress')
  if (status === 'completed') return t('tasks.status.completed')
  if (status === 'canceled') return t('tasks.status.canceled')
  return status
}

function dueRank(task: TaskItem) {
  if (task.due_at === null) return Number.MAX_SAFE_INTEGER
  return new Date(task.due_at).getTime()
}

function priorityRank(task: TaskItem) {
  if (task.status === 'completed' || task.status === 'canceled') return 60
  if (task.priority === 'high') return 0
  if (task.priority === 'middle') return 10
  if (task.priority === 'low') return 20
  return 40
}

function sortTasks(tasks: TaskItem[], sortMode: TaskSortMode) {
  return [...tasks].sort((first, second) => {
    if (sortMode === 'priority') {
      const priorityDiff = priorityRank(first) - priorityRank(second)
      if (priorityDiff !== 0) return priorityDiff
      return dueRank(first) - dueRank(second)
    }
    if (sortMode === 'due_asc') {
      const dueDiff = dueRank(first) - dueRank(second)
      if (dueDiff !== 0) return dueDiff
      return second.updated_at.localeCompare(first.updated_at)
    }
    if (sortMode === 'due_desc') {
      const dueDiff = dueRank(second) - dueRank(first)
      if (dueDiff !== 0) return dueDiff
      return second.updated_at.localeCompare(first.updated_at)
    }
    return second.updated_at.localeCompare(first.updated_at)
  })
}

function TaskCard({ task }: { task: TaskItem }) {
  return (
    <AppLink
      className={`task-row task-row-${task.status}`}
      href={`/tasks/${encodeURIComponent(task.id)}`}
    >
      <div className="task-row-main">
        <div className="task-row-heading">
          <h3>{task.title}</h3>
          <span className="task-status-badge">{taskStatusLabel(task.status)}</span>
        </div>
        {task.description !== null && task.description.trim() !== '' && (
          <p>{task.description}</p>
        )}
        <div className="task-row-meta">
          <span>{task.case_name ?? t('tasks.noCase')}</span>
          <span>{t(`tasks.importance.${task.priority as 'high' | 'middle' | 'low'}`)}</span>
          {task.start_at !== null && <span>{t('tasks.start')}: {formatShortDate(task.start_at)}</span>}
          {task.source_type !== null && <span>{task.source_type}</span>}
        </div>
      </div>
      <div className="task-row-side">
        <span>{t('tasks.due')}</span>
        <strong>{formatShortDate(task.due_at)}</strong>
        {task.estimate_minutes !== null && (
          <small>{t('tasks.estimateMinutes', { value: String(task.estimate_minutes) })}</small>
        )}
      </div>
    </AppLink>
  )
}

export default function TaskView() {
  const [tasks, setTasks] = useState<TaskItem[]>([])
  const [cases, setCases] = useState<CaseItem[]>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(() => {
    const params = new URLSearchParams(window.location.search)
    const caseId = params.get('case_id')
    return caseId === null || caseId.trim() === '' ? null : caseId
  })
  const [sortMode, setSortMode] = useState<TaskSortMode>('priority')
  const [currentTab, setCurrentTab] = useState<TaskTab>('inbox')
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let isMounted = true
    setIsLoading(true)
    Promise.all([listTasks({ status: 'all', limit: 500 }), listCases('all')])
      .then(([nextTasks, nextCases]) => {
        if (!isMounted) return
        setTasks(nextTasks)
        setCases(nextCases)
        setError(null)
      })
      .catch((requestError) => {
        if (isMounted) setError(describeError(requestError))
      })
      .finally(() => {
        if (isMounted) setIsLoading(false)
      })
    return () => {
      isMounted = false
    }
  }, [])

  const normalizedQuery = searchQuery.trim().toLowerCase()
  const searchedTasks = useMemo(
    () =>
      tasks.filter((task) => {
        if (normalizedQuery === '') return true
        return [
          task.title,
          task.description ?? '',
          task.case_name ?? '',
          task.status,
          task.source_type ?? '',
        ]
          .join(' ')
          .toLowerCase()
          .includes(normalizedQuery)
      }),
    [normalizedQuery, tasks],
  )
  const visibleTasks = useMemo(
    () =>
      sortTasks(
        searchedTasks.filter((task) => {
          if (selectedCaseId !== null && task.case_id !== selectedCaseId) {
            return false
          }
          return taskBelongsToTab(task, currentTab)
        }),
        sortMode,
      ),
    [currentTab, searchedTasks, selectedCaseId, sortMode],
  )
  const caseTaskCounts = useMemo(
    () =>
      searchedTasks.reduce<Map<string, number>>((counts, task) => {
        counts.set(task.case_id, (counts.get(task.case_id) ?? 0) + 1)
        return counts
      }, new Map<string, number>()),
    [searchedTasks],
  )
  const caseChips = useMemo(
    () =>
      cases
        .filter((item) => isCaseOpenForSuggestion(item))
        .sort((first, second) => first.name.localeCompare(second.name)),
    [cases],
  )
  const openTaskCount = tasks.filter((task) => taskBelongsToTab(task, 'inbox')).length
  const overdueTaskCount = tasks.filter(
    (task) =>
      taskBelongsToTab(task, 'inbox') &&
      task.due_at !== null &&
      new Date(task.due_at).getTime() < Date.now(),
  ).length

  return (
    <main className="app-shell">
      <div className="task-shell">
        <header className="maintenance-header">
          <div>
            <p>{t('app.name')}</p>
            <h1>{t('tasks.heading')}</h1>
          </div>
          <nav aria-label={t('tasks.navigation')} className="maintenance-nav">
            <AppLink href="/">{t('top.heading')}</AppLink>
            <AppLink href="/cases">{t('cases.heading')}</AppLink>
          </nav>
        </header>

        {error !== null && (
          <div className="mail-feedback">
            <p role="alert">{error}</p>
          </div>
        )}

        <section aria-labelledby="task-tools-heading" className="task-tools-panel">
          <div className="section-heading">
            <h2 id="task-tools-heading">{t('tasks.tools.heading')}</h2>
          </div>
          <div className="task-tools">
            <div aria-label={t('tasks.search.region')} role="search">
              <label>
                <span>{t('tasks.search.label')}</span>
                <input
                  aria-label={t('tasks.search.label')}
                  onChange={(event) => setSearchQuery(event.target.value)}
                  placeholder={t('tasks.search.placeholder')}
                  type="search"
                  value={searchQuery}
                />
              </label>
            </div>
            <div aria-label={t('tasks.caseMask.label')} className="task-case-filters">
              <button
                aria-pressed={selectedCaseId === null}
                onClick={() => setSelectedCaseId(null)}
                type="button"
              >
                {t('tasks.caseMask.all')}
                <span>{searchedTasks.length}</span>
              </button>
              {caseChips.map((item) => (
                <button
                  aria-pressed={selectedCaseId === item.id}
                  key={item.id}
                  onClick={() =>
                    setSelectedCaseId((currentCaseId) =>
                      currentCaseId === item.id ? null : item.id,
                    )
                  }
                  type="button"
                >
                  {item.name}
                  <span>{caseTaskCounts.get(item.id) ?? 0}</span>
                </button>
              ))}
            </div>
          </div>
        </section>

        <div className="task-main-layout">
          <section aria-labelledby="task-list-heading" className="task-list-workspace">
            <nav aria-label={t('tasks.statusFilter')} className="task-tabs" role="tablist">
              <div className="task-tab-group">
                {(['inbox', 'done'] as TaskTab[]).map((tab) => (
                  <button
                    aria-selected={currentTab === tab}
                    key={tab}
                    onClick={() => setCurrentTab(tab)}
                    role="tab"
                    type="button"
                  >
                    {t(`tasks.tab.${tab}`)}
                  </button>
                ))}
              </div>
              <div className="task-tab-group">
                {(['not_started', 'archived'] as TaskTab[]).map((tab) => (
                  <button
                    aria-selected={currentTab === tab}
                    key={tab}
                    onClick={() => setCurrentTab(tab)}
                    role="tab"
                    type="button"
                  >
                    {t(`tasks.tab.${tab}`)}
                  </button>
                ))}
              </div>
            </nav>
            <div className="task-list-panel">
              <div className="section-heading">
                <div>
                  <h2 id="task-list-heading">{t(`tasks.tab.${currentTab}`)}</h2>
                  <p>{t('tasks.list.count', { value: String(visibleTasks.length) })}</p>
                </div>
              </div>
              {isLoading ? (
                <p className="task-empty">{t('tasks.loading')}</p>
              ) : visibleTasks.length === 0 ? (
                <p className="task-empty">{t('tasks.empty')}</p>
              ) : (
                <div className="task-list">
                  {visibleTasks.map((task) => (
                    <TaskCard key={task.id} task={task} />
                  ))}
                </div>
              )}
            </div>
          </section>

          <aside aria-label={t('tasks.gadgets.heading')} className="task-gadget-column">
            <section className="task-gadget-card">
              <h2>{t('tasks.create.heading')}</h2>
              <AppLink className="task-gadget-action" href="/tasks/new">
                {t('tasks.create.openPage')}
              </AppLink>
            </section>
            <section className="task-gadget-card">
              <h2>{t('tasks.gadgets.sort.heading')}</h2>
              <label className="task-sort-control">
                <span>{t('tasks.sort.label')}</span>
                <select
                  aria-label={t('tasks.sort.aria')}
                  onChange={(event) => setSortMode(event.target.value as TaskSortMode)}
                  value={sortMode}
                >
                  <option value="priority">{t('tasks.sort.priority')}</option>
                  <option value="due_asc">{t('tasks.sort.dueAsc')}</option>
                  <option value="due_desc">{t('tasks.sort.dueDesc')}</option>
                  <option value="updated_desc">{t('tasks.sort.updated')}</option>
                </select>
              </label>
            </section>
            <section className="task-gadget-card">
              <h2>{t('tasks.gadgets.summary.heading')}</h2>
              <div className="task-summary-grid">
                <span>{t('tasks.gadgets.summary.open')}</span>
                <strong>{openTaskCount}</strong>
                <span>{t('tasks.gadgets.summary.overdue')}</span>
                <strong>{overdueTaskCount}</strong>
              </div>
            </section>
          </aside>
        </div>
      </div>
    </main>
  )
}
