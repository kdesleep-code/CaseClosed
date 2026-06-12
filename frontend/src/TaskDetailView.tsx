import { useEffect, useState } from 'react'
import type { MouseEvent as ReactMouseEvent } from 'react'
import { AppLink } from './navigation'
import { CaseStorageWindow } from './CaseView'
import { t } from './i18n'
import gmailIconUrl from './assets/gmail-icon-2020.svg'
import settingsGearIconUrl from './assets/settings-gear.svg'
import {
  completeTask,
  createTaskProgressEntry,
  deleteTask,
  deleteTaskProgressEntry,
  getTask,
  updateTask,
  updateTaskProgressEntry,
} from './phase8Api'
import type { TaskItem, TaskProgressEntry } from './phase8Api'

const recurrenceWeekdays = [
  { value: 0, labelKey: 'tasks.recurrence.weekday.sun' },
  { value: 1, labelKey: 'tasks.recurrence.weekday.mon' },
  { value: 2, labelKey: 'tasks.recurrence.weekday.tue' },
  { value: 3, labelKey: 'tasks.recurrence.weekday.wed' },
  { value: 4, labelKey: 'tasks.recurrence.weekday.thu' },
  { value: 5, labelKey: 'tasks.recurrence.weekday.fri' },
  { value: 6, labelKey: 'tasks.recurrence.weekday.sat' },
] as const

const recurrenceMonthWeeks = [
  { value: 1, labelKey: 'tasks.recurrence.week.first' },
  { value: 2, labelKey: 'tasks.recurrence.week.second' },
  { value: 3, labelKey: 'tasks.recurrence.week.third' },
  { value: 4, labelKey: 'tasks.recurrence.week.fourth' },
  { value: 5, labelKey: 'tasks.recurrence.week.fifth' },
  { value: -1, labelKey: 'tasks.recurrence.week.last' },
] as const

function describeError(error: unknown) {
  return error instanceof Error ? error.message : t('tasks.requestFailed')
}

function formatDate(value: string | null) {
  if (value === null) return t('tasks.noDueDate')
  return value.slice(0, 10)
}

function formatStoredDate(value: string) {
  return value.slice(0, 10)
}

function todayKey() {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${day}`
}

function groupProgressEntriesByDate(entries: TaskProgressEntry[]) {
  const groups: Array<{ date: string; entries: TaskProgressEntry[] }> = []
  for (const entry of entries) {
    const date = formatStoredDate(entry.created_at)
    const lastGroup = groups.at(-1)
    if (lastGroup?.date === date) {
      lastGroup.entries.push(entry)
    } else {
      groups.push({ date, entries: [entry] })
    }
  }
  return groups
}

function taskStatusLabel(status: string) {
  if (status === 'not_started') return t('tasks.status.notStarted')
  if (status === 'in_progress') return t('tasks.status.inProgress')
  if (status === 'completed') return t('tasks.status.completed')
  if (status === 'canceled') return t('tasks.status.canceled')
  return status
}

function taskImportance(task: TaskItem) {
  if (task.priority === 'high' || task.priority === 'middle' || task.priority === 'low') {
    return task.priority
  }
  return 'middle'
}

function recurrenceSummary(task: TaskItem) {
  if (task.recurrence_rule_type === null) return t('tasks.recurrence.none')
  const startBefore = Math.abs(task.recurrence_start_offset_days ?? -7)
  if (task.recurrence_rule_type === 'monthly' || task.recurrence_rule_type === 'yearly') {
    const week = recurrenceMonthWeeks.find(
      (item) => item.value === task.recurrence_month_week,
    )
    const weekday = recurrenceWeekdays.find(
      (item) => item.value === task.recurrence_month_weekday,
    )
    if (week !== undefined && weekday !== undefined) {
      return t(
        task.recurrence_rule_type === 'yearly'
          ? 'tasks.recurrence.summaryYearlyWeekday'
          : 'tasks.recurrence.summaryMonthlyWeekday',
        {
          month: String(task.recurrence_year_month ?? 1),
          week: t(week.labelKey),
          weekday: t(weekday.labelKey),
          start: String(startBefore),
        },
      )
    }
    if (task.recurrence_rule_type === 'yearly') {
      return t('tasks.recurrence.summaryYearly', {
        month: String(task.recurrence_year_month ?? 1),
        day: String(task.recurrence_month_day ?? 0),
        start: String(startBefore),
      })
    }
    return t('tasks.recurrence.summaryMonthly', {
      day: String(task.recurrence_month_day ?? 0),
      start: String(startBefore),
    })
  }
  const weekdayNames = recurrenceWeekdays
    .filter((weekday) => task.recurrence_weekdays.includes(weekday.value))
    .map((weekday) => t(weekday.labelKey))
    .join(', ')
  return t(
    task.recurrence_rule_type === 'biweekly'
      ? 'tasks.recurrence.summaryBiweekly'
      : 'tasks.recurrence.summaryWeekly',
    { weekdays: weekdayNames, start: String(startBefore) },
  )
}

function taskReturnToFallback(task: TaskItem) {
  return `/tasks?case_id=${encodeURIComponent(task.case_id)}`
}

function taskReturnTo(task: TaskItem) {
  const params = new URLSearchParams(window.location.search)
  const returnTo = params.get('return_to')
  if (returnTo !== null && (returnTo === '/tasks' || returnTo.startsWith('/tasks?'))) {
    return returnTo
  }
  return taskReturnToFallback(task)
}

export default function TaskDetailView({ taskId }: { taskId: string }) {
  const [task, setTask] = useState<TaskItem | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isCompleting, setIsCompleting] = useState(false)
  const [isEditing, setIsEditing] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [isSavingProgressMemo, setIsSavingProgressMemo] = useState(false)
  const [isUpdatingProgressEntry, setIsUpdatingProgressEntry] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)
  const [titleDraft, setTitleDraft] = useState('')
  const [descriptionDraft, setDescriptionDraft] = useState('')
  const [doneWhenDraft, setDoneWhenDraft] = useState('')
  const [priorityDraft, setPriorityDraft] = useState('middle')
  const [startAtDraft, setStartAtDraft] = useState('')
  const [dueAtDraft, setDueAtDraft] = useState('')
  const [estimateMinutesDraft, setEstimateMinutesDraft] = useState('')
  const [recurrenceRuleTypeDraft, setRecurrenceRuleTypeDraft] = useState('')
  const [recurrenceMonthDayDraft, setRecurrenceMonthDayDraft] = useState('0')
  const [recurrenceYearMonthDraft, setRecurrenceYearMonthDraft] = useState('1')
  const [recurrenceMonthPatternDraft, setRecurrenceMonthPatternDraft] = useState<'day' | 'weekday'>('day')
  const [recurrenceMonthWeekDraft, setRecurrenceMonthWeekDraft] = useState('1')
  const [recurrenceMonthWeekdayDraft, setRecurrenceMonthWeekdayDraft] = useState('1')
  const [recurrenceWeekdaysDraft, setRecurrenceWeekdaysDraft] = useState<number[]>([])
  const [recurrenceStartBeforeDaysDraft, setRecurrenceStartBeforeDaysDraft] = useState('7')
  const [progressMemoDraft, setProgressMemoDraft] = useState('')
  const [progressEntryMenu, setProgressEntryMenu] = useState<{
    entry: TaskProgressEntry
    x: number
    y: number
  } | null>(null)
  const [editingProgressEntryId, setEditingProgressEntryId] = useState<string | null>(null)
  const [editingProgressEntryBody, setEditingProgressEntryBody] = useState('')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let isMounted = true
    setIsLoading(true)
    getTask(taskId)
      .then((nextTask) => {
        if (!isMounted) return
        setTask(nextTask)
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

  useEffect(() => {
    if (task?.status === 'completed' || task?.status === 'canceled') {
      setProgressMemoDraft(task.progress_memo ?? '')
    }
  }, [task?.id, task?.progress_memo, task?.status])

  function handleComplete() {
    if (task === null) return
    setIsCompleting(true)
    completeTask(task.id)
      .then((completedTask) => {
        setTask(completedTask)
        setError(null)
        window.setTimeout(() => {
          window.location.href = taskReturnTo(completedTask)
        }, 1000)
      })
      .catch((requestError) => {
        setError(describeError(requestError))
      })
      .finally(() => setIsCompleting(false))
  }

  function startEdit() {
    if (task === null) return
    setTitleDraft(task.title)
    setDescriptionDraft(task.description ?? '')
    setDoneWhenDraft(task.done_when_text ?? '')
    setPriorityDraft(task.priority)
    setStartAtDraft(task.start_at?.slice(0, 10) ?? '')
    setDueAtDraft(task.due_at?.slice(0, 10) ?? '')
    setEstimateMinutesDraft(task.estimate_minutes === null ? '' : String(task.estimate_minutes))
    setRecurrenceRuleTypeDraft(task.recurrence_rule_type ?? '')
    setRecurrenceMonthDayDraft(
      task.recurrence_month_day === null ? '0' : String(task.recurrence_month_day),
    )
    setRecurrenceYearMonthDraft(
      task.recurrence_year_month === null ? '1' : String(task.recurrence_year_month),
    )
    setRecurrenceMonthPatternDraft(
      task.recurrence_month_week !== null && task.recurrence_month_weekday !== null
        ? 'weekday'
        : 'day',
    )
    setRecurrenceMonthWeekDraft(
      task.recurrence_month_week === null ? '1' : String(task.recurrence_month_week),
    )
    setRecurrenceMonthWeekdayDraft(
      task.recurrence_month_weekday === null ? '1' : String(task.recurrence_month_weekday),
    )
    setRecurrenceWeekdaysDraft(task.recurrence_weekdays ?? [])
    setRecurrenceStartBeforeDaysDraft(
      task.recurrence_start_offset_days === null
        ? '7'
        : String(Math.abs(task.recurrence_start_offset_days)),
    )
    setIsEditing(true)
  }

  function cancelEdit() {
    setIsEditing(false)
  }

  function handleSave() {
    if (task === null || isSaving) return
    const title = titleDraft.trim()
    if (title === '') {
      setError(t('tasks.create.required'))
      return
    }
    const estimateText = estimateMinutesDraft.trim()
    const parsedEstimate = estimateText === '' ? null : Number(estimateText)
    if (
      parsedEstimate !== null &&
      (!Number.isFinite(parsedEstimate) || parsedEstimate < 0)
    ) {
      setError(t('tasks.create.invalidEstimate'))
      return
    }
    const parsedRecurrenceStartBefore = Number(recurrenceStartBeforeDaysDraft)
    if (
      recurrenceRuleTypeDraft !== '' &&
      (!Number.isInteger(parsedRecurrenceStartBefore) || parsedRecurrenceStartBefore < 0)
    ) {
      setError(t('tasks.recurrence.invalidStartBefore'))
      return
    }
    const parsedMonthDay = Number(recurrenceMonthDayDraft)
    if (
      (recurrenceRuleTypeDraft === 'monthly' || recurrenceRuleTypeDraft === 'yearly') &&
      recurrenceMonthPatternDraft === 'day' &&
      (!Number.isInteger(parsedMonthDay) || parsedMonthDay > 31 || parsedMonthDay < -30)
    ) {
      setError(t('tasks.recurrence.invalidMonthDay'))
      return
    }
    const parsedYearMonth = Number(recurrenceYearMonthDraft)
    if (
      recurrenceRuleTypeDraft === 'yearly' &&
      (!Number.isInteger(parsedYearMonth) || parsedYearMonth < 1 || parsedYearMonth > 12)
    ) {
      setError(t('tasks.recurrence.invalidYearMonth'))
      return
    }
    const parsedMonthWeek = Number(recurrenceMonthWeekDraft)
    const parsedMonthWeekday = Number(recurrenceMonthWeekdayDraft)
    if (
      (recurrenceRuleTypeDraft === 'monthly' || recurrenceRuleTypeDraft === 'yearly') &&
      recurrenceMonthPatternDraft === 'weekday' &&
      (!Number.isInteger(parsedMonthWeek) ||
        ![-1, 1, 2, 3, 4, 5].includes(parsedMonthWeek) ||
        !Number.isInteger(parsedMonthWeekday) ||
        parsedMonthWeekday < 0 ||
        parsedMonthWeekday > 6)
    ) {
      setError(t('tasks.recurrence.invalidMonthWeek'))
      return
    }
    if (
      (recurrenceRuleTypeDraft === 'weekly' || recurrenceRuleTypeDraft === 'biweekly') &&
      recurrenceWeekdaysDraft.length === 0
    ) {
      setError(t('tasks.recurrence.weekdayRequired'))
      return
    }
    setIsSaving(true)
    updateTask(task.id, {
      base_version: task.version,
      title,
      description: descriptionDraft.trim() || null,
      done_when_text: doneWhenDraft.trim() || null,
      priority: priorityDraft,
      start_at: startAtDraft || null,
      due_at: dueAtDraft || null,
      estimate_minutes: parsedEstimate,
      recurrence_rule_type: recurrenceRuleTypeDraft || null,
      recurrence_month_day:
        (recurrenceRuleTypeDraft === 'monthly' || recurrenceRuleTypeDraft === 'yearly') &&
        recurrenceMonthPatternDraft === 'day'
          ? parsedMonthDay
          : null,
      recurrence_year_month: recurrenceRuleTypeDraft === 'yearly' ? parsedYearMonth : null,
      recurrence_month_week:
        (recurrenceRuleTypeDraft === 'monthly' || recurrenceRuleTypeDraft === 'yearly') &&
        recurrenceMonthPatternDraft === 'weekday'
          ? parsedMonthWeek
          : null,
      recurrence_month_weekday:
        (recurrenceRuleTypeDraft === 'monthly' || recurrenceRuleTypeDraft === 'yearly') &&
        recurrenceMonthPatternDraft === 'weekday'
          ? parsedMonthWeekday
          : null,
      recurrence_weekdays:
        recurrenceRuleTypeDraft === 'weekly' || recurrenceRuleTypeDraft === 'biweekly'
          ? recurrenceWeekdaysDraft
          : null,
      recurrence_start_offset_days:
        recurrenceRuleTypeDraft === '' ? null : -parsedRecurrenceStartBefore,
    })
      .then((updatedTask) => {
        setTask(updatedTask)
        setIsEditing(false)
        setError(null)
      })
      .catch((requestError) => {
        setError(describeError(requestError))
      })
      .finally(() => setIsSaving(false))
  }

  function handleSaveProgressMemo() {
    if (task === null || isSavingProgressMemo) return
    const body = progressMemoDraft.trim()
    if (body === '') {
      setError(t('tasks.detail.progressMemoRequired'))
      return
    }
    if (
      !isDone &&
      task.status === 'not_started' &&
      ((task.start_at !== null && task.start_at.slice(0, 10) > todayKey()) ||
        (task.case_open_when_date !== null && task.case_open_when_date.slice(0, 10) > todayKey())) &&
      !window.confirm(t('tasks.detail.startEarlyConfirm'))
    ) {
      return
    }
    setIsSavingProgressMemo(true)
    const saveRequest = isDone
      ? updateTask(task.id, { base_version: task.version, progress_memo: body }).then(
          (updatedTask) => ({ task: updatedTask }),
        )
      : createTaskProgressEntry(task.id, body).then((result) => result)
    saveRequest
      .then((result) => {
        setTask(result.task)
        if (!isDone) {
          setProgressMemoDraft('')
        }
        setError(null)
      })
      .catch((requestError) => {
        setError(describeError(requestError))
      })
      .finally(() => setIsSavingProgressMemo(false))
  }

  function startEditProgressEntry(entry: TaskProgressEntry) {
    setEditingProgressEntryId(entry.id)
    setEditingProgressEntryBody(entry.body)
    setProgressEntryMenu(null)
  }

  function cancelEditProgressEntry() {
    setEditingProgressEntryId(null)
    setEditingProgressEntryBody('')
  }

  function handleUpdateProgressEntry(entryId: string) {
    if (task === null || isUpdatingProgressEntry) return
    const body = editingProgressEntryBody.trim()
    if (body === '') {
      setError(t('tasks.detail.progressMemoRequired'))
      return
    }
    setIsUpdatingProgressEntry(true)
    updateTaskProgressEntry(task.id, entryId, body)
      .then((result) => {
        setTask(result.task)
        setEditingProgressEntryId(null)
        setEditingProgressEntryBody('')
        setError(null)
      })
      .catch((requestError) => {
        setError(describeError(requestError))
      })
      .finally(() => setIsUpdatingProgressEntry(false))
  }

  function handleDeleteProgressEntry(entry: TaskProgressEntry) {
    if (task === null || isUpdatingProgressEntry) return
    if (!window.confirm(t('tasks.detail.deleteProgressMemoConfirm'))) return
    setIsUpdatingProgressEntry(true)
    setProgressEntryMenu(null)
    deleteTaskProgressEntry(task.id, entry.id)
      .then((result) => {
        setTask(result.task)
        if (editingProgressEntryId === entry.id) {
          setEditingProgressEntryId(null)
          setEditingProgressEntryBody('')
        }
        setError(null)
      })
      .catch((requestError) => {
        setError(describeError(requestError))
      })
      .finally(() => setIsUpdatingProgressEntry(false))
  }

  function handleDelete() {
    if (task === null || isDeleting) return
    if (!window.confirm(t('tasks.detail.deleteConfirm', { title: task.title }))) {
      return
    }
    setIsDeleting(true)
    deleteTask(task.id)
      .then(() => {
        window.location.href = '/tasks'
      })
      .catch((requestError) => {
        setError(describeError(requestError))
      })
      .finally(() => setIsDeleting(false))
  }

  function openProgressEntryMenu(event: ReactMouseEvent<HTMLElement>, entry: TaskProgressEntry) {
    event.preventDefault()
    setProgressEntryMenu({ entry, x: event.clientX, y: event.clientY })
  }

  const isDone = task?.status === 'completed' || task?.status === 'canceled'
  const sourceMailHref =
    task?.source_type === 'mail' && task.source_id !== null
      ? `/mail/${encodeURIComponent(task.source_id)}`
      : null
  const progressEntries = task?.progress_entries ?? []
  const progressEntryGroups = groupProgressEntriesByDate(progressEntries)
  const showLegacyProgressMemo =
    !isDone &&
    progressEntries.length === 0 &&
    task?.progress_memo !== null &&
    task?.progress_memo !== undefined

  function renderProgressEntry(entry: TaskProgressEntry) {
    const isEntryEditing = editingProgressEntryId === entry.id
    return (
      <article
        className="task-progress-entry"
        key={entry.id}
        onContextMenu={(event) => openProgressEntryMenu(event, entry)}
      >
        {isEntryEditing ? (
          <div className="task-progress-entry-edit">
            <textarea
              aria-label={t('tasks.detail.progressMemoInput')}
              disabled={isUpdatingProgressEntry}
              onChange={(event) => setEditingProgressEntryBody(event.target.value)}
              rows={4}
              value={editingProgressEntryBody}
            />
            <div>
              <button
                disabled={isUpdatingProgressEntry}
                onClick={() => handleUpdateProgressEntry(entry.id)}
                type="button"
              >
                {isUpdatingProgressEntry ? t('common.saving') : t('common.save')}
              </button>
              <button
                disabled={isUpdatingProgressEntry}
                onClick={cancelEditProgressEntry}
                type="button"
              >
                {t('common.cancel')}
              </button>
            </div>
          </div>
        ) : (
          <p>{entry.body}</p>
        )}
      </article>
    )
  }

  return (
    <main className="app-shell" onClick={() => setProgressEntryMenu(null)}>
      {progressEntryMenu !== null ? (
        <div
          className="task-progress-context-menu"
          onClick={(event) => event.stopPropagation()}
          style={{ left: progressEntryMenu.x, top: progressEntryMenu.y }}
        >
          <button onClick={() => startEditProgressEntry(progressEntryMenu.entry)} type="button">
            {t('common.edit')}
          </button>
          <button onClick={() => handleDeleteProgressEntry(progressEntryMenu.entry)} type="button">
            {t('common.delete')}
          </button>
        </div>
      ) : null}
      <div className="task-shell">
        <header className="maintenance-header">
          <div>
            <p>{t('app.name')}</p>
            <h1>{task?.title ?? t('tasks.detail.heading')}</h1>
          </div>
          <nav aria-label={t('tasks.navigation')} className="maintenance-nav">
            <AppLink href="/">{t('top.heading')}</AppLink>
            <AppLink href="/tasks">{t('tasks.heading')}</AppLink>
            <AppLink href="/cases">{t('cases.heading')}</AppLink>
          </nav>
        </header>

        {error !== null && (
          <div className="mail-feedback">
            <p role="alert">{error}</p>
          </div>
        )}

        <div className="task-detail-layout">
          <section aria-label={t('tasks.detail.heading')} className="task-detail-panel">
            {isLoading ? (
              <p className="task-empty">{t('tasks.loading')}</p>
            ) : task === null ? (
              <p className="task-empty">{t('tasks.detail.notFound')}</p>
            ) : (
              <>
                <div className="task-detail-hero">
                  <div>
                    {isEditing ? (
                      <label className="task-create-field">
                        <span>{t('tasks.create.title')}</span>
                        <input
                          autoFocus
                          onChange={(event) => setTitleDraft(event.target.value)}
                          value={titleDraft}
                        />
                      </label>
                    ) : null}
                    <p className="task-detail-hero-meta">
                      <span>{task.case_name ?? t('tasks.noCase')}</span>
                      <span>
                        {isEditing ? (
                          <input
                            aria-label={t('tasks.create.estimate')}
                            min="0"
                            onChange={(event) => setEstimateMinutesDraft(event.target.value)}
                            type="number"
                            value={estimateMinutesDraft}
                          />
                        ) : task.estimate_minutes === null
                          ? t('common.none')
                          : t('tasks.estimateMinutes', {
                              value: String(task.estimate_minutes),
                            })}
                      </span>
                    </p>
                  </div>
                </div>
                <section className="task-detail-section">
                  <h3>{t('tasks.detail.summary')}</h3>
                  {isEditing ? (
                    <textarea
                      aria-label={t('tasks.detail.summary')}
                      className="task-detail-edit-textarea"
                      onChange={(event) => setDescriptionDraft(event.target.value)}
                      rows={5}
                      value={descriptionDraft}
                    />
                  ) : (
                    <p>{task.description ?? t('tasks.detail.noDescription')}</p>
                  )}
                </section>
                <section className="task-detail-section">
                  <h3>{t('tasks.detail.doneWhen')}</h3>
                  {isEditing ? (
                    <textarea
                      aria-label={t('tasks.detail.doneWhen')}
                      className="task-detail-edit-textarea"
                      onChange={(event) => setDoneWhenDraft(event.target.value)}
                      rows={4}
                      value={doneWhenDraft}
                    />
                  ) : (
                    <p>{task.done_when_text ?? t('tasks.detail.doneWhenEmpty')}</p>
                  )}
                </section>
                <section className="task-detail-section task-calendar-event-panel">
                  <div className="task-section-heading-row">
                    <h3>{t('tasks.detail.calendarEvents')}</h3>
                    <button
                      aria-label={t('tasks.detail.linkCalendar')}
                      className="case-icon-button"
                      disabled
                      title={t('tasks.detail.linkCalendar')}
                      type="button"
                    >
                      <img alt="" aria-hidden="true" src={settingsGearIconUrl} />
                    </button>
                  </div>
                  <div className="task-calendar-event-list">
                    <p>{t('tasks.detail.noCalendar')}</p>
                  </div>
                </section>
                <section className="task-detail-section">
                  <h3>{t('tasks.detail.progressMemo')}</h3>
                  <div className="task-progress-timeline">
                    {progressEntries.length === 0 && !showLegacyProgressMemo ? (
                      <p>{t('tasks.detail.noProgressMemo')}</p>
                    ) : null}
                    {showLegacyProgressMemo ? (
                      <article className="task-progress-entry">
                        <header>
                          <strong>{t('tasks.detail.progressMemoLegacy')}</strong>
                        </header>
                        <p>{task.progress_memo}</p>
                      </article>
                    ) : null}
                    {progressEntryGroups.map((group) => (
                      <section className="task-progress-date-group" key={group.date}>
                        <div className="task-progress-date-heading">
                          <time dateTime={group.date}>{group.date}</time>
                        </div>
                        {group.entries.map((entry) => (
                          renderProgressEntry(entry)
                        ))}
                      </section>
                    ))}
                    {isDone ? (
                      <section className="task-progress-date-group">
                        <div className="task-progress-done-heading">
                          <span>{t('tasks.detail.progressMemoDone')}</span>
                        </div>
                        <article className="task-progress-entry">
                          <p>{task.progress_memo ?? t('tasks.detail.doneMemoEmpty')}</p>
                        </article>
                      </section>
                    ) : null}
                  </div>
                  <textarea
                    aria-label={
                      isDone ? t('tasks.detail.doneMemoInput') : t('tasks.detail.progressMemoInput')
                    }
                    disabled={isSavingProgressMemo}
                    onChange={(event) => setProgressMemoDraft(event.target.value)}
                    placeholder={
                      isDone ? t('tasks.detail.doneMemoInput') : t('tasks.detail.progressMemoInput')
                    }
                    rows={4}
                    value={progressMemoDraft}
                  />
                  <div className="task-detail-actions">
                    <button
                      disabled={isSavingProgressMemo}
                      onClick={handleSaveProgressMemo}
                      type="button"
                    >
                      {isSavingProgressMemo
                        ? t('tasks.detail.savingProgressMemo')
                        : isDone
                          ? t('tasks.detail.saveDoneMemo')
                          : t('tasks.detail.addProgressMemo')}
                    </button>
                  </div>
                </section>
              </>
            )}
          </section>

          <aside aria-label={t('tasks.gadgets.heading')} className="task-gadget-column">
            {task !== null && (
              <>
                <section className="task-gadget-card">
                  <h2>{t('tasks.detail.meta')}</h2>
                  <dl className="task-gadget-meta">
                    <div>
                      <dt>{t('tasks.detail.importance')}</dt>
                      <dd>
                        {isEditing ? (
                          <select
                            onChange={(event) => setPriorityDraft(event.target.value)}
                            value={priorityDraft}
                          >
                            <option value="high">{t('tasks.importance.high')}</option>
                            <option value="middle">{t('tasks.importance.middle')}</option>
                            <option value="low">{t('tasks.importance.low')}</option>
                          </select>
                        ) : (
                          <span className={`task-importance-badge task-importance-${taskImportance(task)}`}>
                            {t(`tasks.importance.${taskImportance(task)}`)}
                          </span>
                        )}
                      </dd>
                    </div>
                    <div>
                      <dt>{t('tasks.detail.status')}</dt>
                      <dd>{taskStatusLabel(task.status)}</dd>
                    </div>
                    <div>
                      <dt>{t('tasks.create.start')}</dt>
                      <dd>
                        {isEditing ? (
                          <input
                            onChange={(event) => setStartAtDraft(event.target.value)}
                            type="date"
                            value={startAtDraft}
                          />
                        ) : (
                          formatDate(task.start_at)
                        )}
                      </dd>
                    </div>
                    <div>
                      <dt>{t('tasks.due')}</dt>
                      <dd>
                        {isEditing ? (
                          <input
                            onChange={(event) => setDueAtDraft(event.target.value)}
                            type="date"
                            value={dueAtDraft}
                          />
                        ) : (
                          formatDate(task.due_at)
                        )}
                      </dd>
                    </div>
                  </dl>
                  <div className="task-recurrence-editor">
                    <label className="task-create-gadget-field">
                      <span>{t('tasks.recurrence.heading')}</span>
                      {isEditing ? (
                        <select
                          onChange={(event) => setRecurrenceRuleTypeDraft(event.target.value)}
                          value={recurrenceRuleTypeDraft}
                        >
                          <option value="">{t('tasks.recurrence.none')}</option>
                          <option value="monthly">{t('tasks.recurrence.monthly')}</option>
                          <option value="yearly">{t('tasks.recurrence.yearly')}</option>
                          <option value="weekly">{t('tasks.recurrence.weekly')}</option>
                          <option value="biweekly">{t('tasks.recurrence.biweekly')}</option>
                        </select>
                      ) : (
                        <strong>{recurrenceSummary(task)}</strong>
                      )}
                    </label>
                    {isEditing && recurrenceRuleTypeDraft === 'yearly' && (
                      <label className="task-create-gadget-field">
                        <span>{t('tasks.recurrence.yearMonth')}</span>
                        <input
                          max="12"
                          min="1"
                          onChange={(event) => setRecurrenceYearMonthDraft(event.target.value)}
                          type="number"
                          value={recurrenceYearMonthDraft}
                        />
                      </label>
                    )}
                    {isEditing &&
                      (recurrenceRuleTypeDraft === 'monthly' ||
                        recurrenceRuleTypeDraft === 'yearly') && (
                        <>
                          <label className="task-create-gadget-field">
                            <span>{t('tasks.recurrence.monthPattern')}</span>
                            <select
                              onChange={(event) =>
                                setRecurrenceMonthPatternDraft(
                                  event.target.value as 'day' | 'weekday',
                                )
                              }
                              value={recurrenceMonthPatternDraft}
                            >
                              <option value="day">{t('tasks.recurrence.patternDay')}</option>
                              <option value="weekday">
                                {t('tasks.recurrence.patternWeekday')}
                              </option>
                            </select>
                          </label>
                          {recurrenceMonthPatternDraft === 'day' ? (
                            <label className="task-create-gadget-field">
                              <span>{t('tasks.recurrence.monthDay')}</span>
                              <input
                                onChange={(event) =>
                                  setRecurrenceMonthDayDraft(event.target.value)
                                }
                                type="number"
                                value={recurrenceMonthDayDraft}
                              />
                            </label>
                          ) : (
                            <>
                              <label className="task-create-gadget-field">
                                <span>{t('tasks.recurrence.monthWeek')}</span>
                                <select
                                  onChange={(event) =>
                                    setRecurrenceMonthWeekDraft(event.target.value)
                                  }
                                  value={recurrenceMonthWeekDraft}
                                >
                                  {recurrenceMonthWeeks.map((week) => (
                                    <option key={week.value} value={week.value}>
                                      {t(week.labelKey)}
                                    </option>
                                  ))}
                                </select>
                              </label>
                              <label className="task-create-gadget-field">
                                <span>{t('tasks.recurrence.monthWeekday')}</span>
                                <select
                                  onChange={(event) =>
                                    setRecurrenceMonthWeekdayDraft(event.target.value)
                                  }
                                  value={recurrenceMonthWeekdayDraft}
                                >
                                  {recurrenceWeekdays.map((weekday) => (
                                    <option key={weekday.value} value={weekday.value}>
                                      {t(weekday.labelKey)}
                                    </option>
                                  ))}
                                </select>
                              </label>
                            </>
                          )}
                        </>
                      )}
                    {isEditing &&
                      (recurrenceRuleTypeDraft === 'weekly' ||
                        recurrenceRuleTypeDraft === 'biweekly') && (
                        <div className="task-create-gadget-field">
                          <span>{t('tasks.recurrence.weekdays')}</span>
                          <div className="task-recurrence-weekdays">
                            {recurrenceWeekdays.map((weekday) => (
                              <label key={weekday.value}>
                                <input
                                  checked={recurrenceWeekdaysDraft.includes(weekday.value)}
                                  onChange={(event) => {
                                    setRecurrenceWeekdaysDraft((current) =>
                                      event.target.checked
                                        ? [...current, weekday.value].sort((a, b) => a - b)
                                        : current.filter((value) => value !== weekday.value),
                                    )
                                  }}
                                  type="checkbox"
                                />
                                <span>{t(weekday.labelKey)}</span>
                              </label>
                            ))}
                          </div>
                        </div>
                      )}
                    {isEditing && recurrenceRuleTypeDraft !== '' && (
                      <label className="task-create-gadget-field">
                        <span>{t('tasks.recurrence.startBeforeDays')}</span>
                        <input
                          min="0"
                          onChange={(event) => setRecurrenceStartBeforeDaysDraft(event.target.value)}
                          type="number"
                          value={recurrenceStartBeforeDaysDraft}
                        />
                      </label>
                    )}
                  </div>
                  <div className="task-gadget-icon-actions">
                    {sourceMailHref === null ? (
                      <button
                        aria-label={t('tasks.detail.sourceMail')}
                        className="task-gadget-icon-action"
                        disabled
                        title={t('tasks.detail.noSourceMail')}
                        type="button"
                      >
                        <img alt="" aria-hidden="true" src={gmailIconUrl} />
                      </button>
                    ) : (
                      <AppLink
                        aria-label={t('tasks.detail.sourceMail')}
                        className="task-gadget-icon-action"
                        href={sourceMailHref}
                        title={t('tasks.detail.sourceMail')}
                      >
                        <img alt="" aria-hidden="true" src={gmailIconUrl} />
                      </AppLink>
                    )}
                    <AppLink
                      aria-label={t('tasks.detail.openCase')}
                      className="task-gadget-icon-action"
                      href={`/cases/${encodeURIComponent(task.case_id)}`}
                      title={t('tasks.detail.openCase')}
                    >
                      <span aria-hidden="true">C</span>
                    </AppLink>
                  </div>
                </section>
                <section className="task-gadget-card task-files-gadget-card">
                  {task.storage_directory_id === null ? (
                    <>
                      <h2>{t('tasks.files.heading')}</h2>
                      <p className="task-gadget-empty">{t('tasks.files.unavailable')}</p>
                    </>
                  ) : (
                    <>
                      <h2>{t('tasks.files.heading')}</h2>
                      <CaseStorageWindow
                        body={t('tasks.files.body')}
                        caseId={task.case_id}
                        deleteMode="physical"
                        heading={t('tasks.files.heading')}
                        rootDirectoryId={task.storage_directory_id}
                        rootLabel={t('tasks.files.root')}
                        rootListMode="directory"
                      />
                    </>
                  )}
                </section>
              </>
            )}
            <section className="task-gadget-card">
              <h2>{t('tasks.detail.actions')}</h2>
              {isEditing ? (
                <>
                  <button
                    className="task-gadget-secondary-action"
                    disabled={isSaving}
                    onClick={handleSave}
                    type="button"
                  >
                    {isSaving ? t('tasks.detail.saving') : t('tasks.detail.save')}
                  </button>
                  <button
                    className="task-gadget-secondary-action"
                    disabled={isSaving}
                    onClick={cancelEdit}
                    type="button"
                  >
                    {t('common.cancel')}
                  </button>
                </>
              ) : (
                <button
                  className="task-gadget-secondary-action"
                  disabled={task === null}
                  onClick={startEdit}
                  type="button"
                >
                  {t('tasks.detail.edit')}
                </button>
              )}
              <button
                className="task-gadget-secondary-action"
                disabled={task === null || isDeleting}
                onClick={handleDelete}
                type="button"
              >
                {isDeleting ? t('tasks.detail.deleting') : t('tasks.detail.delete')}
              </button>
              {!isEditing && (
                <button
                  className="task-gadget-action"
                  disabled={task === null || isDone || isCompleting}
                  onClick={handleComplete}
                  type="button"
                >
                  {isCompleting ? t('tasks.detail.completing') : t('tasks.detail.markDone')}
                </button>
              )}
            </section>
          </aside>
        </div>
      </div>
    </main>
  )
}
