import { useEffect, useMemo, useState } from 'react'
import { AppLink } from './navigation'
import { t } from './i18n'
import { completeTask, createTaskProgressEntry, getTask, listTasks, updateTask } from './phase8Api'
import type { TaskItem, TaskProgressEntry } from './phase8Api'
import './MobileTaskView.css'

function todayKey() {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Tokyo',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
    .formatToParts(new Date())
    .reduce<Record<string, string>>((values, part) => {
      values[part.type] = part.value
      return values
    }, {})

  return `${parts.year}-${parts.month}-${parts.day}`
}

function describeError(error: unknown) {
  return error instanceof Error ? error.message : t('tasks.requestFailed')
}

function isClosed(task: TaskItem) {
  return task.status === 'completed' || task.status === 'canceled'
}

function dueDateKey(value: string | null) {
  return value === null ? null : value.slice(0, 10)
}

function dueRank(task: TaskItem) {
  if (task.due_at === null) return Number.MAX_SAFE_INTEGER
  const time = new Date(task.due_at).getTime()
  return Number.isFinite(time) ? time : Number.MAX_SAFE_INTEGER - 1
}

function priorityRank(task: TaskItem) {
  if (task.priority === 'high') return 0
  if (task.priority === 'middle') return 10
  if (task.priority === 'low') return 20
  return 40
}

function formatDue(value: string | null) {
  if (value === null) return t('tasks.noDueDate')
  const date = dueDateKey(value)
  if (date === null) return t('tasks.noDueDate')
  if (value.length <= 10) return date
  return `${date} ${value.slice(11, 16)}`
}

function dueTone(task: TaskItem) {
  const due = dueDateKey(task.due_at)
  if (due === null || isClosed(task)) return ''
  const today = todayKey()
  if (due < today) return ' overdue'
  if (due === today) return ' today'
  return ''
}

function taskStatusLabel(status: string) {
  if (status === 'not_started') return t('tasks.status.notStarted')
  if (status === 'in_progress') return t('tasks.status.inProgress')
  if (status === 'completed') return t('tasks.status.completed')
  if (status === 'canceled') return t('tasks.status.canceled')
  return status
}

function sortedTasks(tasks: TaskItem[]) {
  return [...tasks].sort((left, right) => {
    const closedDiff = Number(isClosed(left)) - Number(isClosed(right))
    if (closedDiff !== 0) return closedDiff
    const dueDiff = dueRank(left) - dueRank(right)
    if (dueDiff !== 0) return dueDiff
    const priorityDiff = priorityRank(left) - priorityRank(right)
    if (priorityDiff !== 0) return priorityDiff
    return right.updated_at.localeCompare(left.updated_at)
  })
}

function progressEntries(task: TaskItem) {
  return task.progress_entries ?? []
}

function latestProgressBody(task: TaskItem) {
  const entries = progressEntries(task)
  const latestEntry = entries.at(-1)
  return latestEntry?.body ?? task.progress_memo
}

function taskCaseLabel(task: TaskItem) {
  return task.case_name ?? t('tasks.noCase')
}

function progressDate(entry: TaskProgressEntry) {
  return entry.created_at.slice(0, 10)
}

export function MobileTaskListView() {
  const [tasks, setTasks] = useState<TaskItem[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let isMounted = true
    setIsLoading(true)
    listTasks({ status: 'all', limit: 500 })
      .then((items) => {
        if (!isMounted) return
        setTasks(sortedTasks(items.filter((task) => !isClosed(task))))
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

  const groupedTasks = useMemo(() => {
    const groups = new Map<string, TaskItem[]>()
    for (const task of tasks) {
      const key = dueDateKey(task.due_at) ?? t('tasks.noDueDate')
      groups.set(key, [...(groups.get(key) ?? []), task])
    }
    return [...groups.entries()]
  }, [tasks])

  return (
    <main className="mobile-shell mobile-task-shell">
      <header className="mobile-topbar">
        <div>
          <p>CaseClosed</p>
          <h1>{t('mobile.tasks.heading')}</h1>
        </div>
        <AppLink className="mobile-topbar-link" href="/m">
          {t('common.backToList')}
        </AppLink>
      </header>

      {error !== null && <p className="mobile-alert" role="alert">{error}</p>}
      {isLoading ? <p className="mobile-loading">{t('common.loading')}</p> : null}

      {!isLoading && error === null && groupedTasks.length === 0 ? (
        <section className="mobile-panel">
          <p className="mobile-empty">{t('mobile.tasks.empty')}</p>
        </section>
      ) : null}

      <div className="mobile-task-groups">
        {groupedTasks.map(([date, items]) => (
          <section className="mobile-task-day" key={date}>
            <h2>{date}</h2>
            <ol className="mobile-task-list">
              {items.map((task) => (
                <li key={task.id}>
                  <AppLink href={`/m/tasks/${encodeURIComponent(task.id)}`}>
                    <div className="mobile-task-row-main">
                      <strong>{task.title}</strong>
                      <span className="mobile-task-case-badge">{taskCaseLabel(task)}</span>
                      {latestProgressBody(task) !== null ? <span>{latestProgressBody(task)}</span> : null}
                    </div>
                    <div className={`mobile-task-due${dueTone(task)}`}>
                      <span>{t('tasks.due')}</span>
                      <strong>{formatDue(task.due_at)}</strong>
                    </div>
                  </AppLink>
                </li>
              ))}
            </ol>
          </section>
        ))}
      </div>
    </main>
  )
}

export function MobileTaskDetailView({ taskId }: { taskId: string }) {
  const [task, setTask] = useState<TaskItem | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isCompleting, setIsCompleting] = useState(false)
  const [isSavingMemo, setIsSavingMemo] = useState(false)
  const [memoDraft, setMemoDraft] = useState('')
  const [error, setError] = useState<string | null>(null)
  const isDone = task !== null && isClosed(task)

  useEffect(() => {
    let isMounted = true
    setIsLoading(true)
    getTask(taskId)
      .then((nextTask) => {
        if (!isMounted) return
        setTask(nextTask)
        setMemoDraft(isClosed(nextTask) ? nextTask.progress_memo ?? '' : '')
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
  }, [taskId])

  function handleComplete() {
    if (task === null || isCompleting || isDone) return
    setIsCompleting(true)
    completeTask(task.id)
      .then((completedTask) => {
        setTask(completedTask)
        setMemoDraft(completedTask.progress_memo ?? '')
        setError(null)
      })
      .catch((requestError) => setError(describeError(requestError)))
      .finally(() => setIsCompleting(false))
  }

  function handleSaveMemo() {
    if (task === null || isSavingMemo) return
    const body = memoDraft.trim()
    if (body === '') {
      setError(t('tasks.detail.progressMemoRequired'))
      return
    }
    setIsSavingMemo(true)
    const request = isDone
      ? updateTask(task.id, { base_version: task.version, progress_memo: body })
      : createTaskProgressEntry(task.id, body).then((result) => result.task)
    request
      .then((updatedTask) => {
        setTask(updatedTask)
        if (!isClosed(updatedTask)) setMemoDraft('')
        setError(null)
      })
      .catch((requestError) => setError(describeError(requestError)))
      .finally(() => setIsSavingMemo(false))
  }

  return (
    <main className="mobile-shell mobile-task-shell">
      <header className="mobile-topbar">
        <div>
          <p>{t('mobile.tasks.heading')}</p>
          <h1>{task?.title ?? t('mobile.tasks.detailHeading')}</h1>
        </div>
        <AppLink className="mobile-topbar-link" href="/m/tasks">
          {t('common.backToList')}
        </AppLink>
      </header>

      {error !== null && <p className="mobile-alert" role="alert">{error}</p>}
      {isLoading ? <p className="mobile-loading">{t('common.loading')}</p> : null}

      {task !== null ? (
        <>
          <section className="mobile-panel mobile-task-detail-card">
            <div className={`mobile-task-detail-due${dueTone(task)}`}>
              <span>{t('tasks.due')}</span>
              <strong>{formatDue(task.due_at)}</strong>
            </div>
            <span className="mobile-task-case-badge mobile-task-case-badge-detail">{taskCaseLabel(task)}</span>
            <dl className="mobile-task-detail-meta">
              <div>
                <dt>{t('tasks.detail.status')}</dt>
                <dd>{taskStatusLabel(task.status)}</dd>
              </div>
            </dl>
            {task.description !== null && task.description.trim() !== '' ? (
              <p>{task.description}</p>
            ) : null}
            {!isDone ? (
              <button disabled={isCompleting} onClick={handleComplete} type="button">
                {isCompleting ? t('common.loading') : t('tasks.status.completed')}
              </button>
            ) : null}
          </section>

          <section className="mobile-panel mobile-task-memo-panel">
            <h2>{t('tasks.detail.progressMemo')}</h2>
            <div className="mobile-task-progress-list">
              {progressEntries(task).length === 0 && task.progress_memo === null ? (
                <p className="mobile-empty">{t('mobile.tasks.memoEmpty')}</p>
              ) : null}
              {progressEntries(task).map((entry) => (
                <article key={entry.id}>
                  <time>{progressDate(entry)}</time>
                  <p>{entry.body}</p>
                </article>
              ))}
              {task.progress_memo !== null ? (
                <article>
                  <time>{t('tasks.detail.progressMemoDone')}</time>
                  <p>{task.progress_memo}</p>
                </article>
              ) : null}
            </div>
            <textarea
              disabled={isSavingMemo}
              onChange={(event) => setMemoDraft(event.target.value)}
              placeholder={isDone ? t('tasks.detail.doneMemoInput') : t('tasks.detail.progressMemoInput')}
              rows={4}
              value={memoDraft}
            />
            <button disabled={isSavingMemo} onClick={handleSaveMemo} type="button">
              {isSavingMemo
                ? t('tasks.detail.savingProgressMemo')
                : isDone
                  ? t('tasks.detail.saveDoneMemo')
                  : t('tasks.detail.addProgressMemo')}
            </button>
          </section>
        </>
      ) : null}
    </main>
  )
}
