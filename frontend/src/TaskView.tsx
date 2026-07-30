import { useEffect, useMemo, useState } from 'react'
import type { CSSProperties } from 'react'
import { AppLink, TopNav } from './navigation'
import { t } from './i18n'
import { isCaseOpenForSuggestion, listCaseGenres, listCases } from './phase7Api'
import type { CaseGenre, CaseItem } from './phase7Api'
import { listTasks } from './phase8Api'
import type { TaskItem } from './phase8Api'

type TaskSortMode = 'priority' | 'due_asc' | 'due_desc' | 'updated_desc'
type TaskTab = 'inbox' | 'done' | 'not_started' | 'frozen' | 'archived'

const ARCHIVE_AFTER_MS = 14 * 24 * 60 * 60 * 1000

function describeError(error: unknown) {
  return error instanceof Error ? error.message : t('tasks.requestFailed')
}

function formatShortDate(value: string | null) {
  if (value === null) return t('tasks.noDueDate')
  return value.slice(0, 10)
}

function formatDueDate(value: string | null) {
  if (value === null) return t('tasks.noDueDate')
  return `~ ${value.slice(0, 10)}`
}

function todayKey() {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${day}`
}

function isOverdueDate(value: string | null) {
  if (value === null) return false
  if (value.length <= 10) {
    return value.slice(0, 10) < todayKey()
  }
  const dueTime = new Date(value).getTime()
  return Number.isFinite(dueTime) && dueTime < Date.now()
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
  if (tab === 'frozen') return task.status === 'frozen'
  if (tab === 'not_started') return task.status !== 'frozen' && isTaskNotStartedByDate(task)
  if (tab === 'done') return isTaskClosed(task) && !isTaskArchived(task)
  return task.status !== 'frozen' && !isTaskClosed(task) && !isTaskNotStartedByDate(task)
}

function taskStatusLabel(status: string) {
  if (status === 'not_started') return t('tasks.status.notStarted')
  if (status === 'in_progress') return t('tasks.status.inProgress')
  if (status === 'completed') return t('tasks.status.completed')
  if (status === 'frozen') return t('tasks.status.frozen')
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

function defaultSortForTab(tab: TaskTab): TaskSortMode {
  return tab === 'not_started' ? 'due_asc' : 'priority'
}

function TaskCard({ task, returnTo }: { task: TaskItem; returnTo: string }) {
  return (
    <AppLink
      className={`task-row task-row-${task.status} task-importance-row-${task.priority}`}
      href={`/tasks/${encodeURIComponent(task.id)}?return_to=${encodeURIComponent(returnTo)}`}
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
        <strong className={isOverdueDate(task.due_at) ? 'task-due-overdue' : undefined}>
          {formatDueDate(task.due_at)}
        </strong>
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
  const [genres, setGenres] = useState<CaseGenre[]>([])
  const [searchQuery, setSearchQuery] = useState(() => {
    const params = new URLSearchParams(window.location.search)
    return params.get('q') ?? ''
  })
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(() => {
    const params = new URLSearchParams(window.location.search)
    const caseId = params.get('case_id')
    return caseId === null || caseId.trim() === '' ? null : caseId
  })
  const [isCaseMaskOpen, setIsCaseMaskOpen] = useState(false)
  const [sortMode, setSortMode] = useState<TaskSortMode>(() => {
    const params = new URLSearchParams(window.location.search)
    const value = params.get('sort')
    if (value === 'due_asc' || value === 'due_desc' || value === 'updated_desc') {
      return value
    }
    const tab = params.get('tab')
    return tab === 'not_started' ? 'due_asc' : 'priority'
  })
  const [currentTab, setCurrentTab] = useState<TaskTab>(() => {
    const params = new URLSearchParams(window.location.search)
    const value = params.get('tab')
    return value === 'done' || value === 'not_started' || value === 'frozen' || value === 'archived'
      ? value
      : 'inbox'
  })
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let isMounted = true
    setIsLoading(true)
    Promise.all([listTasks({ status: 'all', limit: 500 }), listCases('all'), listCaseGenres()])
      .then(([nextTasks, nextCases, nextGenres]) => {
        if (!isMounted) return
        setTasks(nextTasks)
        setCases(nextCases)
        setGenres(nextGenres)
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
  const genreById = useMemo(() => new Map(genres.map((genre) => [genre.id, genre])), [genres])
  const genreOrderById = useMemo(
    () => new Map(genres.map((genre, index) => [genre.id, index])),
    [genres],
  )
  const caseChips = useMemo(
    () =>
      cases
        .filter((item) => isCaseOpenForSuggestion(item))
        .sort((first, second) => {
          const firstOrder =
            first.genre_id !== null ? (genreOrderById.get(first.genre_id) ?? 9998) : 9999
          const secondOrder =
            second.genre_id !== null ? (genreOrderById.get(second.genre_id) ?? 9998) : 9999
          if (firstOrder !== secondOrder) return firstOrder - secondOrder
          return first.name.localeCompare(second.name)
        }),
    [cases, genreOrderById],
  )
  const openTaskCount = tasks.filter((task) => taskBelongsToTab(task, 'inbox')).length
  const overdueTaskCount = tasks.filter(
    (task) =>
      taskBelongsToTab(task, 'inbox') &&
      task.due_at !== null &&
      new Date(task.due_at).getTime() < Date.now(),
  ).length
  const returnTo = useMemo(() => {
    const params = new URLSearchParams()
    if (currentTab !== 'inbox') params.set('tab', currentTab)
    if (selectedCaseId !== null) params.set('case_id', selectedCaseId)
    if (searchQuery.trim() !== '') params.set('q', searchQuery.trim())
    if (sortMode !== 'priority') params.set('sort', sortMode)
    const query = params.toString()
    return query === '' ? '/tasks' : `/tasks?${query}`
  }, [currentTab, searchQuery, selectedCaseId, sortMode])

  return (
    <main className="app-shell">
      <div className="task-shell">
        <header className="maintenance-header">
          <div>
            <p>{t('app.name')}</p>
            <h1>{t('tasks.heading')}</h1>
          </div>
          <TopNav
            ariaLabelKey="tasks.navigation"
            items={[
              { href: '/', labelKey: 'top.heading' },
              { href: '/cases', labelKey: 'nav.cases' },
              { href: '/mail', labelKey: 'nav.mail' },
              { href: '/calendar', labelKey: 'nav.calendar' },
              { href: '/files', labelKey: 'nav.files' },
            ]}
          />
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
            <div className="task-case-mask-shell">
              <button
                aria-expanded={isCaseMaskOpen}
                className="task-case-mask-toggle"
                onClick={() => setIsCaseMaskOpen((current) => !current)}
                type="button"
              >
                <span>{t('tasks.caseMask.label')}</span>
                <strong>{selectedCaseId === null ? t('tasks.caseMask.all') : cases.find((item) => item.id === selectedCaseId)?.name ?? t('tasks.caseMask.label')}</strong>
              </button>
            </div>
            {isCaseMaskOpen && (
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
                    style={
                      {
                        '--task-case-genre-color':
                          item.genre_id === null
                            ? '#ffffff'
                            : genreById.get(item.genre_id)?.color_hex ?? '#ffffff',
                      } as CSSProperties
                    }
                    type="button"
                  >
                    {item.name}
                    <span>{caseTaskCounts.get(item.id) ?? 0}</span>
                  </button>
                ))}
              </div>
            )}
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
                    onClick={() => {
                      setCurrentTab(tab)
                      setSortMode(defaultSortForTab(tab))
                    }}
                    role="tab"
                    type="button"
                  >
                    {t(`tasks.tab.${tab}`)}
                  </button>
                ))}
              </div>
              <div className="task-tab-group">
                {(['not_started', 'frozen', 'archived'] as TaskTab[]).map((tab) => (
                  <button
                    aria-selected={currentTab === tab}
                    key={tab}
                    onClick={() => {
                      setCurrentTab(tab)
                      setSortMode(defaultSortForTab(tab))
                    }}
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
                    <TaskCard key={task.id} returnTo={returnTo} task={task} />
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
