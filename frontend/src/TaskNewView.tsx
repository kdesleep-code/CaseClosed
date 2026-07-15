import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { AppLink, TopNav, navigateTo, returnToOrFallback } from './navigation'
import { t } from './i18n'
import { isCaseOpenForSuggestion, listCases } from './phase7Api'
import type { CaseItem } from './phase7Api'
import { createTask, prefillTask } from './phase8Api'
import type { TaskPrefill } from './phase8Api'
import SuggestInput from './SuggestInput'

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

function defaultStartDateFromDue(dueDate: string | null | undefined) {
  if (dueDate === null || dueDate === undefined || dueDate.trim() === '') {
    return ''
  }
  const due = new Date(`${dueDate.slice(0, 10)}T00:00:00`)
  if (Number.isNaN(due.getTime())) {
    return ''
  }
  due.setDate(due.getDate() - 7)
  return due.toISOString().slice(0, 10)
}

type TaskBatchQueue = {
  case_id: string
  case_name: string
  llm_run_id?: string
  source_file_ids?: string[]
  suggestions: TaskPrefill[]
}

function readTaskBatchQueue(batchKey: string | null): TaskBatchQueue | null {
  if (batchKey === null || batchKey.trim() === '') return null
  try {
    const raw = window.sessionStorage.getItem(batchKey)
    if (raw === null) return null
    const parsed = JSON.parse(raw) as Partial<TaskBatchQueue>
    if (
      typeof parsed.case_id !== 'string' ||
      typeof parsed.case_name !== 'string' ||
      !Array.isArray(parsed.suggestions)
    ) {
      return null
    }
    return {
      case_id: parsed.case_id,
      case_name: parsed.case_name,
      llm_run_id: typeof parsed.llm_run_id === 'string' ? parsed.llm_run_id : undefined,
      source_file_ids: Array.isArray(parsed.source_file_ids)
        ? parsed.source_file_ids.filter((item): item is string => typeof item === 'string')
        : [],
      suggestions: parsed.suggestions,
    }
  } catch {
    return null
  }
}

export default function TaskNewView() {
  const currentParams = new URLSearchParams(window.location.search)
  const batchKey = currentParams.get('batch_key')
  const batchIndex = Number(currentParams.get('batch_index') ?? '0')
  const [cases, setCases] = useState<CaseItem[]>([])
  const [batchQueue, setBatchQueue] = useState<TaskBatchQueue | null>(null)
  const [caseText, setCaseText] = useState(() => {
    const params = new URLSearchParams(window.location.search)
    return params.get('case_name')?.trim() ?? ''
  })
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [doneWhenText, setDoneWhenText] = useState('')
  const [priority, setPriority] = useState('middle')
  const [startAt, setStartAt] = useState('')
  const [dueAt, setDueAt] = useState('')
  const [estimateMinutes, setEstimateMinutes] = useState('')
  const [recurrenceRuleType, setRecurrenceRuleType] = useState('')
  const [recurrenceMonthDay, setRecurrenceMonthDay] = useState('0')
  const [recurrenceYearMonth, setRecurrenceYearMonth] = useState('1')
  const [recurrenceMonthPattern, setRecurrenceMonthPattern] = useState<'day' | 'weekday'>('day')
  const [recurrenceMonthWeek, setRecurrenceMonthWeek] = useState('1')
  const [recurrenceMonthWeekday, setRecurrenceMonthWeekday] = useState('1')
  const [recurrenceWeekdayValues, setRecurrenceWeekdayValues] = useState<number[]>([])
  const [recurrenceStartBeforeDays, setRecurrenceStartBeforeDays] = useState('7')
  const [llmPrompt, setLlmPrompt] = useState('')
  const [isPrefilling, setIsPrefilling] = useState(false)
  const [prefillNotice, setPrefillNotice] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isCreating, setIsCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const safeBatchIndex = Number.isFinite(batchIndex) && batchIndex >= 0 ? Math.floor(batchIndex) : 0
  const batchSuggestion =
    batchQueue !== null ? batchQueue.suggestions[safeBatchIndex] ?? null : null
  const isBatchMode = batchKey !== null && batchQueue !== null && batchSuggestion !== null
  const returnHref = returnToOrFallback('/tasks')

  useEffect(() => {
    let isMounted = true
    listCases('all')
      .then((nextCases) => {
        if (!isMounted) return
        const params = new URLSearchParams(window.location.search)
        const initialCaseId = params.get('case_id')?.trim() ?? ''
        const initialCase = nextCases.find(
          (item) =>
            item.id === initialCaseId &&
            item.archived_at === null &&
            item.closed_at === null,
        )
        const caseMap = new Map<string, CaseItem>()
        nextCases
          .filter((item) => isCaseOpenForSuggestion(item))
          .forEach((item) => caseMap.set(item.id, item))
        if (initialCase !== undefined) {
          caseMap.set(initialCase.id, initialCase)
        }
        const selectableCases = Array.from(caseMap.values())
        setCases(selectableCases)
        setCaseText((currentCaseText) =>
          currentCaseText || initialCase?.name || '',
        )
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

  useEffect(() => {
    const queue = readTaskBatchQueue(batchKey)
    setBatchQueue(queue)
    if (batchKey === null) {
      return
    }
    if (queue === null) {
      setError(t('tasks.create.batchMissing'))
      return
    }
    const suggestion = queue.suggestions[safeBatchIndex]
    if (suggestion === undefined) {
      setError(t('tasks.create.batchMissing'))
      return
    }
    setCaseText(queue.case_name)
    setTitle(suggestion.title ?? '')
    setDescription(suggestion.description ?? '')
    setDoneWhenText(suggestion.done_when_text ?? '')
    setPriority(suggestion.priority || 'middle')
    setStartAt(defaultStartDateFromDue(suggestion.due_at))
    setDueAt(suggestion.due_at ?? '')
    setEstimateMinutes(
      suggestion.estimate_minutes === null ? '' : String(suggestion.estimate_minutes),
    )
    setRecurrenceRuleType('')
    setRecurrenceMonthDay('0')
    setRecurrenceYearMonth('1')
    setRecurrenceMonthPattern('day')
    setRecurrenceMonthWeek('1')
    setRecurrenceMonthWeekday('1')
    setRecurrenceWeekdayValues([])
    setRecurrenceStartBeforeDays('7')
    setLlmPrompt('')
    setPrefillNotice(
      t('tasks.create.batchProgress', {
        current: safeBatchIndex + 1,
        total: queue.suggestions.length,
      }),
    )
    setError(null)
  }, [batchKey, safeBatchIndex])

  function selectedCase() {
    const trimmedCaseText = caseText.trim()
    if (trimmedCaseText === '') {
      return cases.find((item) => item.name.toLocaleLowerCase() === 'bucket')
    }
    return cases.find(
      (item) =>
        item.name.toLocaleLowerCase() === trimmedCaseText.toLocaleLowerCase() ||
        item.id.toLocaleLowerCase() === trimmedCaseText.toLocaleLowerCase(),
    )
  }

  async function handleLlmPrefill() {
    const prompt = llmPrompt.trim()
    if (prompt === '' || isPrefilling) return
    setIsPrefilling(true)
    setError(null)
    setPrefillNotice(null)
    try {
      const selectedCaseItem = selectedCase()
      const { prefill } = await prefillTask({
        prompt,
        case_id: selectedCaseItem?.id ?? null,
        current_fields: {
          title,
          description,
          done_when_text: doneWhenText,
          priority,
          start_at: startAt,
          due_at: dueAt,
          estimate_minutes: estimateMinutes,
        },
      })
      if (title.trim() === '' && prefill.title !== null) setTitle(prefill.title)
      if (description.trim() === '' && prefill.description !== null) {
        setDescription(prefill.description)
      }
      if (doneWhenText.trim() === '' && prefill.done_when_text !== null) {
        setDoneWhenText(prefill.done_when_text)
      }
      if (priority === 'middle' && prefill.priority !== '') setPriority(prefill.priority)
      if (dueAt.trim() === '' && prefill.due_at !== null) setDueAt(prefill.due_at)
      if (startAt.trim() === '' && prefill.due_at !== null) {
        setStartAt(defaultStartDateFromDue(prefill.due_at))
      }
      if (estimateMinutes.trim() === '' && prefill.estimate_minutes !== null) {
        setEstimateMinutes(String(prefill.estimate_minutes))
      }
      setPrefillNotice(t('tasks.create.llmApplied'))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsPrefilling(false)
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const trimmedTitle = title.trim()
    const selectedCaseItem = selectedCase()
    if (trimmedTitle === '' || selectedCaseItem === undefined) {
      setError(t('tasks.create.required'))
      return
    }
    const estimateText = estimateMinutes.trim()
    const parsedEstimate = estimateText === '' ? null : Number(estimateText)
    if (
      parsedEstimate !== null &&
      (!Number.isFinite(parsedEstimate) || parsedEstimate < 0)
    ) {
      setError(t('tasks.create.invalidEstimate'))
      return
    }
    const parsedRecurrenceStartBefore = Number(recurrenceStartBeforeDays)
    if (
      recurrenceRuleType !== '' &&
      (!Number.isInteger(parsedRecurrenceStartBefore) || parsedRecurrenceStartBefore < 0)
    ) {
      setError(t('tasks.recurrence.invalidStartBefore'))
      return
    }
    const parsedMonthDay = Number(recurrenceMonthDay)
    if (
      (recurrenceRuleType === 'monthly' || recurrenceRuleType === 'yearly') &&
      recurrenceMonthPattern === 'day' &&
      (!Number.isInteger(parsedMonthDay) || parsedMonthDay > 31 || parsedMonthDay < -30)
    ) {
      setError(t('tasks.recurrence.invalidMonthDay'))
      return
    }
    const parsedYearMonth = Number(recurrenceYearMonth)
    if (
      recurrenceRuleType === 'yearly' &&
      (!Number.isInteger(parsedYearMonth) || parsedYearMonth < 1 || parsedYearMonth > 12)
    ) {
      setError(t('tasks.recurrence.invalidYearMonth'))
      return
    }
    const parsedMonthWeek = Number(recurrenceMonthWeek)
    const parsedMonthWeekday = Number(recurrenceMonthWeekday)
    if (
      (recurrenceRuleType === 'monthly' || recurrenceRuleType === 'yearly') &&
      recurrenceMonthPattern === 'weekday' &&
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
      (recurrenceRuleType === 'weekly' || recurrenceRuleType === 'biweekly') &&
      recurrenceWeekdayValues.length === 0
    ) {
      setError(t('tasks.recurrence.weekdayRequired'))
      return
    }

    setIsCreating(true)
    createTask({
      case_id: selectedCaseItem.id,
      title: trimmedTitle,
      description: description.trim() || null,
      done_when_text: doneWhenText.trim() || null,
      priority,
      start_at: startAt || null,
      due_at: dueAt || null,
      estimate_minutes: parsedEstimate,
      recurrence_rule_type: recurrenceRuleType || null,
      recurrence_month_day:
        (recurrenceRuleType === 'monthly' || recurrenceRuleType === 'yearly') &&
        recurrenceMonthPattern === 'day'
          ? parsedMonthDay
          : null,
      recurrence_year_month: recurrenceRuleType === 'yearly' ? parsedYearMonth : null,
      recurrence_month_week:
        (recurrenceRuleType === 'monthly' || recurrenceRuleType === 'yearly') &&
        recurrenceMonthPattern === 'weekday'
          ? parsedMonthWeek
          : null,
      recurrence_month_weekday:
        (recurrenceRuleType === 'monthly' || recurrenceRuleType === 'yearly') &&
        recurrenceMonthPattern === 'weekday'
          ? parsedMonthWeekday
          : null,
      recurrence_weekdays:
        recurrenceRuleType === 'weekly' || recurrenceRuleType === 'biweekly'
          ? recurrenceWeekdayValues
          : null,
      recurrence_start_offset_days:
        recurrenceRuleType === '' ? null : -parsedRecurrenceStartBefore,
      source_type: isBatchMode ? 'llm' : 'manual',
      source_id: isBatchMode ? batchQueue.llm_run_id ?? null : null,
    })
      .then(() => {
        navigateAfterBatchStep()
      })
      .catch((requestError) => {
        setError(describeError(requestError))
      })
      .finally(() => setIsCreating(false))
  }

  function navigateAfterBatchStep() {
    if (!isBatchMode || batchKey === null || batchQueue === null) {
      navigateTo(returnHref)
      return
    }
    const nextIndex = safeBatchIndex + 1
    if (nextIndex < batchQueue.suggestions.length) {
      navigateTo(
        `/tasks/new?case_id=${encodeURIComponent(batchQueue.case_id)}&batch_key=${encodeURIComponent(
          batchKey,
        )}&batch_index=${nextIndex}`,
      )
      return
    }
    window.sessionStorage.removeItem(batchKey)
    navigateTo(returnHref)
  }

  function handleSkipBatchSuggestion() {
    navigateAfterBatchStep()
  }

  return (
    <main className="app-shell">
      <div className="task-shell">
        <header className="maintenance-header">
          <div>
            <p>{t('app.name')}</p>
            <h1>{t('tasks.create.heading')}</h1>
          </div>
          <TopNav
            ariaLabelKey="tasks.navigation"
            items={[
              { href: '/tasks', labelKey: 'nav.tasks' },
              { href: '/cases', labelKey: 'nav.cases' },
              { href: '/', labelKey: 'top.heading' },
              { href: '/mail', labelKey: 'nav.mail' },
              { href: '/calendar', labelKey: 'nav.calendar' },
            ]}
          />
        </header>

        {error !== null && (
          <div className="mail-feedback">
            <p role="alert">{error}</p>
          </div>
        )}

        <form className="task-new-layout" onSubmit={handleSubmit}>
          <section aria-labelledby="task-new-heading" className="task-detail-panel">
            <div className="task-detail-hero">
              <div>
                <h2 id="task-new-heading">{t('tasks.create.formHeading')}</h2>
                <p>{t('tasks.create.formBody')}</p>
              </div>
            </div>
            <section className="task-detail-section">
              <label className="task-create-field">
                <span>{t('tasks.create.title')}</span>
                <input
                  onChange={(event) => setTitle(event.target.value)}
                  placeholder={t('tasks.create.titlePlaceholder')}
                  type="text"
                  value={title}
                />
              </label>
            </section>
            <section className="task-detail-section">
              <label className="task-create-field">
                <span>{t('tasks.detail.summary')}</span>
                <textarea
                  onChange={(event) => setDescription(event.target.value)}
                  placeholder={t('tasks.create.summaryPlaceholder')}
                  rows={5}
                  value={description}
                />
              </label>
            </section>
            <section className="task-detail-section">
              <label className="task-create-field">
                <span>{t('tasks.detail.doneWhen')}</span>
                <textarea
                  onChange={(event) => setDoneWhenText(event.target.value)}
                  placeholder={t('tasks.create.doneWhenPlaceholder')}
                  rows={4}
                  value={doneWhenText}
                />
              </label>
            </section>
            <section className="task-detail-section">
              <h3>{t('tasks.detail.progressMemo')}</h3>
              <p>{t('tasks.create.progressMemoAfterCreate')}</p>
            </section>
          </section>

          <aside aria-label={t('tasks.gadgets.heading')} className="task-gadget-column">
            <section className="task-gadget-card">
              <h2>{t('tasks.detail.meta')}</h2>
              <label className="task-create-gadget-field">
                <span>{t('tasks.create.case')}</span>
                <SuggestInput
                  ariaLabel={t('tasks.create.case')}
                  autoComplete="off"
                  disabled={isLoading || cases.length === 0}
                  maxItems={1}
                  onChange={setCaseText}
                  options={cases.map((item) => ({
                    key: item.id,
                    value: item.name,
                    label: item.name,
                    badgeLabel: item.name,
                  }))}
                  placeholder={t('tasks.create.casePlaceholder')}
                  value={caseText}
                />
              </label>
              {cases.length === 0 && (
                <p className="task-gadget-empty">{t('tasks.create.noCase')}</p>
              )}
              <label className="task-create-gadget-field">
                <span>{t('tasks.create.priority')}</span>
                <select
                  onChange={(event) => setPriority(event.target.value)}
                  value={priority}
                >
                  <option value="high">{t('tasks.importance.high')}</option>
                  <option value="middle">{t('tasks.importance.middle')}</option>
                  <option value="low">{t('tasks.importance.low')}</option>
                </select>
              </label>
              <label className="task-create-gadget-field">
                <span>{t('tasks.create.start')}</span>
                <input
                  onChange={(event) => setStartAt(event.target.value)}
                  type="date"
                  value={startAt}
                />
              </label>
              <label className="task-create-gadget-field">
                <span>{t('tasks.create.due')}</span>
                <input
                  onChange={(event) => setDueAt(event.target.value)}
                  type="date"
                  value={dueAt}
                />
              </label>
              <label className="task-create-gadget-field">
                <span>{t('tasks.create.estimate')}</span>
                <input
                  min="0"
                  onChange={(event) => setEstimateMinutes(event.target.value)}
                  placeholder="30"
                  type="number"
                  value={estimateMinutes}
                />
              </label>
              <label className="task-create-gadget-field">
                <span>{t('tasks.recurrence.heading')}</span>
                <select
                  onChange={(event) => setRecurrenceRuleType(event.target.value)}
                  value={recurrenceRuleType}
                >
                  <option value="">{t('tasks.recurrence.none')}</option>
                  <option value="monthly">{t('tasks.recurrence.monthly')}</option>
                  <option value="yearly">{t('tasks.recurrence.yearly')}</option>
                  <option value="weekly">{t('tasks.recurrence.weekly')}</option>
                  <option value="biweekly">{t('tasks.recurrence.biweekly')}</option>
                </select>
              </label>
              {recurrenceRuleType === 'yearly' && (
                <label className="task-create-gadget-field">
                  <span>{t('tasks.recurrence.yearMonth')}</span>
                  <input
                    max="12"
                    min="1"
                    onChange={(event) => setRecurrenceYearMonth(event.target.value)}
                    type="number"
                    value={recurrenceYearMonth}
                  />
                </label>
              )}
              {(recurrenceRuleType === 'monthly' || recurrenceRuleType === 'yearly') && (
                <>
                  <label className="task-create-gadget-field">
                    <span>{t('tasks.recurrence.monthPattern')}</span>
                    <select
                      onChange={(event) =>
                        setRecurrenceMonthPattern(event.target.value as 'day' | 'weekday')
                      }
                      value={recurrenceMonthPattern}
                    >
                      <option value="day">{t('tasks.recurrence.patternDay')}</option>
                      <option value="weekday">{t('tasks.recurrence.patternWeekday')}</option>
                    </select>
                  </label>
                  {recurrenceMonthPattern === 'day' ? (
                    <label className="task-create-gadget-field">
                      <span>{t('tasks.recurrence.monthDay')}</span>
                      <input
                        onChange={(event) => setRecurrenceMonthDay(event.target.value)}
                        type="number"
                        value={recurrenceMonthDay}
                      />
                    </label>
                  ) : (
                    <>
                      <label className="task-create-gadget-field">
                        <span>{t('tasks.recurrence.monthWeek')}</span>
                        <select
                          onChange={(event) => setRecurrenceMonthWeek(event.target.value)}
                          value={recurrenceMonthWeek}
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
                          onChange={(event) => setRecurrenceMonthWeekday(event.target.value)}
                          value={recurrenceMonthWeekday}
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
              {(recurrenceRuleType === 'weekly' || recurrenceRuleType === 'biweekly') && (
                <div className="task-create-gadget-field">
                  <span>{t('tasks.recurrence.weekdays')}</span>
                  <div className="task-recurrence-weekdays">
                    {recurrenceWeekdays.map((weekday) => (
                      <label key={weekday.value}>
                        <input
                          checked={recurrenceWeekdayValues.includes(weekday.value)}
                          onChange={(event) => {
                            setRecurrenceWeekdayValues((current) =>
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
              {recurrenceRuleType !== '' && (
                <label className="task-create-gadget-field">
                  <span>{t('tasks.recurrence.startBeforeDays')}</span>
                  <input
                    min="0"
                    onChange={(event) => setRecurrenceStartBeforeDays(event.target.value)}
                    type="number"
                    value={recurrenceStartBeforeDays}
                  />
                </label>
              )}
            </section>
            <section className="task-gadget-card">
              <h2>{t('tasks.create.llmHeading')}</h2>
              <label className="task-create-gadget-field">
                <span>{t('tasks.create.llmPrompt')}</span>
                <textarea
                  onChange={(event) => setLlmPrompt(event.target.value)}
                  placeholder={t('tasks.create.llmPlaceholder')}
                  rows={5}
                  value={llmPrompt}
                />
              </label>
              {prefillNotice !== null && <p className="task-gadget-empty">{prefillNotice}</p>}
              <button
                className={`task-gadget-action button-loading-dot${isPrefilling ? ' is-loading' : ''}`}
                disabled={isPrefilling || llmPrompt.trim() === ''}
                onClick={() => {
                  void handleLlmPrefill()
                }}
                type="button"
              >
                {isPrefilling ? t('tasks.create.llmGenerating') : t('tasks.create.llmGenerate')}
              </button>
            </section>
            <section className="task-gadget-card">
              <h2>{t('tasks.detail.actions')}</h2>
              <button
                className="task-gadget-action"
                disabled={isCreating || isLoading || cases.length === 0}
                type="submit"
              >
                {isCreating ? t('tasks.create.creating') : t('tasks.create.submit')}
              </button>
              {isBatchMode && (
                <button
                  className="task-gadget-secondary-action"
                  disabled={isCreating}
                  onClick={handleSkipBatchSuggestion}
                  type="button"
                >
                  {t('tasks.create.skipSuggestion')}
                </button>
              )}
              <AppLink className="task-gadget-secondary-action" href={returnHref}>
                {t('tasks.create.cancel')}
              </AppLink>
            </section>
          </aside>
        </form>
      </div>
    </main>
  )
}
