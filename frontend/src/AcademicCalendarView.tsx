import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import {
  createAcademicPeriod,
  createAcademicYear,
  createAcademicSemester,
  deleteAcademicCalendarDay,
  deleteAcademicPeriod,
  deleteAcademicSemester,
  importNationalHolidayCsv,
  listAcademicCalendarDays,
  listAcademicPeriods,
  listAcademicSemesters,
  listAcademicYears,
  updateAcademicPeriod,
  updateAcademicSemester,
  upsertAcademicCalendarDay,
  type AcademicCalendarDay,
  type AcademicCalendarDayType,
  type AcademicPeriod,
  type AcademicSemester,
  type AcademicYear,
} from './academicCalendarApi'
import { t } from './i18n'
import { TopNav } from './navigation'

const weekdayLabels = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

type MonthCell = { key: string; day?: number }

const dayTypes: Array<{ value: AcademicCalendarDayType; label: string }> = [
  { value: 'normal', label: 'Normal' },
  { value: 'holiday', label: 'Holiday' },
  { value: 'no_class_day', label: 'No class' },
  { value: 'substitute_teaching_day', label: 'Substitute' },
  { value: 'makeup_day', label: 'Makeup' },
  { value: 'exam_period', label: 'Exam' },
  { value: 'university_event', label: 'Event' },
]

type DayForm = {
  day_type: AcademicCalendarDayType
  label: string
  is_teaching_day: boolean
  effective_weekday: string
  note: string
}

type SemesterForm = {
  label: string
  starts_on: string
  ends_on: string
  sort_order: string
  note: string
}

type PeriodForm = {
  period_no: string
  label: string
  starts_at: string
  ends_at: string
  sort_order: string
  note: string
}

function pad2(value: number) {
  return String(value).padStart(2, '0')
}

function currentAcademicYearDefault() {
  const now = new Date()
  const month = now.getMonth() + 1
  const startYear = month >= 4 ? now.getFullYear() : now.getFullYear() - 1
  return {
    year_label: `${startYear}`,
    starts_on: `${startYear}-04-01`,
    ends_on: `${startYear + 1}-03-31`,
    note: '',
  }
}

function monthStart(dateText: string) {
  const [year, month] = dateText.split('-').map(Number)
  return new Date(year, month - 1, 1)
}

function addMonths(date: Date, count: number) {
  return new Date(date.getFullYear(), date.getMonth() + count, 1)
}

function dateKey(year: number, monthIndex: number, day: number) {
  return `${year}-${pad2(monthIndex + 1)}-${pad2(day)}`
}

function weekdayForDate(date: string) {
  return new Date(`${date}T00:00:00`).getDay()
}

function isWeekendDate(date: string) {
  const weekday = weekdayForDate(date)
  return weekday === 0 || weekday === 6
}

function monthsForYear(year: AcademicYear) {
  const start = monthStart(year.starts_on)
  const end = monthStart(year.ends_on)
  const months: Date[] = []
  for (let cursor = start; cursor <= end; cursor = addMonths(cursor, 1)) {
    months.push(cursor)
  }
  return months
}

function emptyDayForm(date: string): DayForm {
  const weekday = weekdayForDate(date)
  const isWeekend = weekday === 0 || weekday === 6
  return {
    day_type: isWeekend ? 'holiday' : 'normal',
    label: isWeekend ? 'Weekend' : 'Normal',
    is_teaching_day: !isWeekend,
    effective_weekday: isWeekend ? '' : String(weekday),
    note: '',
  }
}

function semesterFormFromYear(year: AcademicYear | null): SemesterForm {
  return {
    label: '',
    starts_on: year?.starts_on ?? '',
    ends_on: year?.ends_on ?? '',
    sort_order: '0',
    note: '',
  }
}

function semesterFormFromSemester(semester: AcademicSemester): SemesterForm {
  return {
    label: semester.label,
    starts_on: semester.starts_on,
    ends_on: semester.ends_on,
    sort_order: String(semester.sort_order),
    note: semester.note ?? '',
  }
}

function defaultPeriodForm(nextPeriodNo = 1): PeriodForm {
  return {
    period_no: String(nextPeriodNo),
    label: `${nextPeriodNo}`,
    starts_at: '08:40',
    ends_at: '09:55',
    sort_order: String(nextPeriodNo * 10),
    note: '',
  }
}

function periodFormFromPeriod(period: AcademicPeriod): PeriodForm {
  return {
    period_no: String(period.period_no),
    label: period.label,
    starts_at: period.starts_at,
    ends_at: period.ends_at,
    sort_order: String(period.sort_order),
    note: period.note ?? '',
  }
}

function formFromDay(date: string, day: AcademicCalendarDay | undefined): DayForm {
  if (day === undefined) {
    return emptyDayForm(date)
  }
  return {
    day_type: day.day_type,
    label: day.label,
    is_teaching_day: day.is_teaching_day,
    effective_weekday: day.effective_weekday === null ? '' : String(day.effective_weekday),
    note: day.note ?? '',
  }
}

function classNameForDay(day: AcademicCalendarDay | undefined) {
  if (day === undefined) return ''
  return ` has-academic-override is-${day.day_type.replaceAll('_', '-')}`
}

function dateIsInSemester(date: string, semester: AcademicSemester | undefined) {
  return semester !== undefined && date >= semester.starts_on && date <= semester.ends_on
}

function canHighlightSemesterDay(date: string, day: AcademicCalendarDay | undefined) {
  if (day === undefined) {
    return !isWeekendDate(date)
  }
  return day.day_type !== 'holiday' && day.day_type !== 'no_class_day'
}

function AcademicCalendarView() {
  const [years, setYears] = useState<AcademicYear[]>([])
  const [selectedYearId, setSelectedYearId] = useState('')
  const [days, setDays] = useState<AcademicCalendarDay[]>([])
  const [semesters, setSemesters] = useState<AcademicSemester[]>([])
  const [periods, setPeriods] = useState<AcademicPeriod[]>([])
  const [selectedSemesterId, setSelectedSemesterId] = useState('')
  const [semesterForm, setSemesterForm] = useState<SemesterForm>(() => semesterFormFromYear(null))
  const [selectedPeriodId, setSelectedPeriodId] = useState('')
  const [periodForm, setPeriodForm] = useState<PeriodForm>(() => defaultPeriodForm())
  const [selectedDate, setSelectedDate] = useState<string | null>(null)
  const [dayForm, setDayForm] = useState<DayForm | null>(null)
  const [yearForm, setYearForm] = useState(currentAcademicYearDefault)
  const [holidayCsvFile, setHolidayCsvFile] = useState<File | null>(null)
  const [isHolidaySettingOpen, setIsHolidaySettingOpen] = useState(true)
  const [isSemesterSettingOpen, setIsSemesterSettingOpen] = useState(true)
  const [isDaySettingOpen, setIsDaySettingOpen] = useState(true)
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const selectedYear = years.find((year) => year.id === selectedYearId) ?? null
  const selectedSemester =
    semesters.find((semester) => semester.id === selectedSemesterId) ?? undefined
  const selectedPeriod = periods.find((period) => period.id === selectedPeriodId) ?? undefined
  const dayMap = useMemo(
    () => new Map(days.map((day) => [day.date, day])),
    [days],
  )
  const selectedDay = selectedDate === null ? undefined : dayMap.get(selectedDate)

  useEffect(() => {
    let isMounted = true
    listAcademicYears()
      .then((items) => {
        if (!isMounted) return
        setYears(items)
        setSelectedYearId(items[0]?.id ?? '')
      })
      .catch((requestError) => {
        if (isMounted) {
          setError(requestError instanceof Error ? requestError.message : t('app.requestFailed'))
        }
      })
      .finally(() => {
        if (isMounted) setIsLoading(false)
      })
    return () => {
      isMounted = false
    }
  }, [])

  useEffect(() => {
    if (selectedYearId === '') {
      setDays([])
      setSemesters([])
      setPeriods([])
      setSelectedSemesterId('')
      setSemesterForm(semesterFormFromYear(null))
      setSelectedPeriodId('')
      setPeriodForm(defaultPeriodForm())
      setSelectedDate(null)
      setDayForm(null)
      return undefined
    }
    let isMounted = true
    Promise.all([
      listAcademicCalendarDays(selectedYearId),
      listAcademicSemesters(selectedYearId),
      listAcademicPeriods(),
    ])
      .then(([dayItems, semesterItems, periodItems]) => {
        if (!isMounted) return
        setDays(dayItems)
        setSemesters(semesterItems)
        setPeriods(periodItems)
        setSelectedSemesterId('')
        setSemesterForm(semesterFormFromYear(years.find((year) => year.id === selectedYearId) ?? null))
        setSelectedPeriodId('')
        setPeriodForm(defaultPeriodForm((periodItems.at(-1)?.period_no ?? 0) + 1))
        setSelectedDate(null)
        setDayForm(null)
      })
      .catch((requestError) => {
        if (isMounted) {
          setError(requestError instanceof Error ? requestError.message : t('app.requestFailed'))
        }
      })
    return () => {
      isMounted = false
    }
  }, [selectedYearId, years])

  function selectDate(date: string) {
    setSelectedDate(date)
    setDayForm(formFromDay(date, dayMap.get(date)))
    setError(null)
    setNotice(null)
  }

  async function handleCreateYear(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setIsSaving(true)
    setError(null)
    setNotice(null)
    try {
      const year = await createAcademicYear({
        ...yearForm,
        note: yearForm.note.trim() === '' ? null : yearForm.note,
      })
      setYears((current) => [year, ...current])
      setSelectedYearId(year.id)
      setNotice('Academic year created.')
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('app.requestFailed'))
    } finally {
      setIsSaving(false)
    }
  }

  async function handleSaveSemester(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (selectedYear === null) return
    setIsSaving(true)
    setError(null)
    setNotice(null)
    const payload = {
      label: semesterForm.label.trim(),
      starts_on: semesterForm.starts_on,
      ends_on: semesterForm.ends_on,
      sort_order: Number(semesterForm.sort_order || '0'),
      note: semesterForm.note.trim() === '' ? null : semesterForm.note,
    }
    try {
      const saved =
        selectedSemester === undefined
          ? await createAcademicSemester(selectedYear.id, payload)
          : await updateAcademicSemester(selectedSemester.id, payload)
      setSemesters((current) => {
        const withoutSaved = current.filter((semester) => semester.id !== saved.id)
        return [...withoutSaved, saved].sort((left, right) => {
          const orderDifference = left.sort_order - right.sort_order
          return orderDifference !== 0
            ? orderDifference
            : left.starts_on.localeCompare(right.starts_on)
        })
      })
      setSelectedSemesterId(saved.id)
      setSemesterForm(semesterFormFromSemester(saved))
      setNotice('Semester saved.')
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('app.requestFailed'))
    } finally {
      setIsSaving(false)
    }
  }

  async function handleImportHolidays(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (selectedYear === null || holidayCsvFile === null) return
    setIsSaving(true)
    setError(null)
    setNotice(null)
    try {
      const result = await importNationalHolidayCsv(selectedYear.id, holidayCsvFile)
      setDays((current) => {
        const importedDates = new Set(result.items.map((day) => day.date))
        const withoutImported = current.filter((day) => !importedDates.has(day.date))
        return [...withoutImported, ...result.items].sort((left, right) => (
          left.date.localeCompare(right.date)
        ))
      })
      setHolidayCsvFile(null)
      setNotice(
        `Holidays imported: ${result.imported_count} new / ${result.updated_count} updated / ${result.skipped_existing} skipped.`,
      )
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('app.requestFailed'))
    } finally {
      setIsSaving(false)
    }
  }

  async function handleSavePeriod(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (selectedYear === null) return
    setIsSaving(true)
    setError(null)
    setNotice(null)
    const payload = {
      period_no: Number(periodForm.period_no),
      label: periodForm.label.trim(),
      starts_at: periodForm.starts_at,
      ends_at: periodForm.ends_at,
      sort_order: Number(periodForm.sort_order || periodForm.period_no || '0'),
      note: periodForm.note.trim() === '' ? null : periodForm.note,
    }
    try {
      const saved =
        selectedPeriod === undefined
          ? await createAcademicPeriod(payload)
          : await updateAcademicPeriod(selectedPeriod.id, payload)
      setPeriods((current) => {
        const withoutSaved = current.filter((period) => period.id !== saved.id)
        return [...withoutSaved, saved].sort((left, right) => {
          const orderDifference = left.sort_order - right.sort_order
          return orderDifference !== 0
            ? orderDifference
            : left.period_no - right.period_no
        })
      })
      setSelectedPeriodId(saved.id)
      setPeriodForm(periodFormFromPeriod(saved))
      setNotice('Period saved.')
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('app.requestFailed'))
    } finally {
      setIsSaving(false)
    }
  }

  async function handleDeletePeriod() {
    if (selectedPeriod === undefined) return
    setIsSaving(true)
    setError(null)
    setNotice(null)
    try {
      await deleteAcademicPeriod(selectedPeriod.id)
      setPeriods((current) => current.filter((period) => period.id !== selectedPeriod.id))
      setSelectedPeriodId('')
      setPeriodForm(defaultPeriodForm((periods.at(-1)?.period_no ?? 0) + 1))
      setNotice('Period deleted.')
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('app.requestFailed'))
    } finally {
      setIsSaving(false)
    }
  }

  async function handleDeleteSemester() {
    if (selectedSemester === undefined) return
    setIsSaving(true)
    setError(null)
    setNotice(null)
    try {
      await deleteAcademicSemester(selectedSemester.id)
      setSemesters((current) => current.filter((semester) => semester.id !== selectedSemester.id))
      setSelectedSemesterId('')
      setSemesterForm(semesterFormFromYear(selectedYear))
      setNotice('Semester deleted.')
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('app.requestFailed'))
    } finally {
      setIsSaving(false)
    }
  }

  async function handleSaveDay(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (selectedYear === null || selectedDate === null || dayForm === null) return
    setIsSaving(true)
    setError(null)
    setNotice(null)
    try {
      const saved = await upsertAcademicCalendarDay(selectedYear.id, selectedDate, {
        date: selectedDate,
        day_type: dayForm.day_type,
        label: dayForm.label.trim() || dayTypes.find((item) => item.value === dayForm.day_type)?.label || 'Day',
        is_teaching_day: dayForm.is_teaching_day,
        effective_weekday:
          dayForm.effective_weekday === '' ? null : Number(dayForm.effective_weekday),
        note: dayForm.note.trim() === '' ? null : dayForm.note,
      })
      setDays((current) => {
        const withoutSaved = current.filter((day) => day.date !== saved.date)
        return [...withoutSaved, saved].sort((left, right) => left.date.localeCompare(right.date))
      })
      setNotice('Academic day saved.')
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('app.requestFailed'))
    } finally {
      setIsSaving(false)
    }
  }

  async function handleDeleteDay() {
    if (selectedYear === null || selectedDate === null || selectedDay === undefined) return
    setIsSaving(true)
    setError(null)
    setNotice(null)
    try {
      await deleteAcademicCalendarDay(selectedYear.id, selectedDate)
      setDays((current) => current.filter((day) => day.date !== selectedDate))
      setDayForm(emptyDayForm(selectedDate))
      setNotice('Academic day reset.')
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('app.requestFailed'))
    } finally {
      setIsSaving(false)
    }
  }

  function renderMonth(monthDate: Date) {
    const year = monthDate.getFullYear()
    const monthIndex = monthDate.getMonth()
    const daysInMonth = new Date(year, monthIndex + 1, 0).getDate()
    const firstWeekday = new Date(year, monthIndex, 1).getDay()
    const cells: MonthCell[] = [
      ...Array.from({ length: firstWeekday }, (_, index) => ({ key: `blank-${index}` })),
      ...Array.from({ length: daysInMonth }, (_, index) => ({
        key: dateKey(year, monthIndex, index + 1),
        day: index + 1,
      })),
    ]

    return (
      <section className="academic-month-card" key={`${year}-${monthIndex}`}>
        <header>
          <strong>{monthDate.toLocaleString('en-US', { month: 'long' })}</strong>
          <span>{year}</span>
        </header>
        <div className="academic-month-weekdays">
          {weekdayLabels.map((weekday) => (
            <span key={weekday}>{weekday}</span>
          ))}
        </div>
        <div className="academic-month-days">
          {cells.map((cell) => {
            if (cell.day === undefined) {
              return <span aria-hidden="true" className="academic-empty-day" key={cell.key} />
            }
            const date = cell.key
            const day = dayMap.get(date)
            const isSelected = selectedDate === date
            const inSelectedSemester =
              dateIsInSemester(date, selectedSemester) && canHighlightSemesterDay(date, day)
            const isDefaultWeekendHoliday = day === undefined && isWeekendDate(date)
            return (
              <button
                aria-pressed={isSelected}
                className={`academic-day${classNameForDay(day)}${
                  inSelectedSemester ? ' is-in-selected-semester' : ''
                }${isDefaultWeekendHoliday ? ' is-weekend-default' : ''}`}
                key={date}
                onClick={() => selectDate(date)}
                type="button"
              >
                <span>{cell.day}</span>
                {day !== undefined && (
                  <small>
                    {day.effective_weekday !== null
                      ? `${weekdayLabels[day.effective_weekday]} class`
                      : day.label}
                  </small>
                )}
              </button>
            )
          })}
        </div>
      </section>
    )
  }

  return (
    <main className="app-shell">
      <div className="calendar-shell academic-calendar-shell">
        <header className="maintenance-header">
          <div>
            <p>{t('app.name')}</p>
            <h1>{t('academicCalendar.heading')}</h1>
          </div>
          <TopNav
            ariaLabelKey="academicCalendar.navigation"
            items={[
              { href: '/', labelKey: 'top.heading' },
              { href: '/calendar', labelKey: 'nav.calendar' },
              { href: '/tasks', labelKey: 'nav.tasks' },
              { href: '/cases', labelKey: 'nav.cases' },
              { href: '/settings', labelKey: 'nav.settings' },
            ]}
          />
        </header>

        {error !== null && (
          <div className="mail-feedback">
            <p role="alert">{error}</p>
          </div>
        )}
        {notice !== null && (
          <div className="mail-feedback">
            <p>{notice}</p>
          </div>
        )}

        <div className="academic-calendar-layout">
          <section className="calendar-panel academic-calendar-board">
            <div className="academic-calendar-toolbar">
              <label>
                <span>Year</span>
                <select
                  disabled={years.length === 0}
                  onChange={(event) => setSelectedYearId(event.target.value)}
                  value={selectedYearId}
                >
                  {years.map((year) => (
                    <option key={year.id} value={year.id}>
                      {year.year_label}
                    </option>
                  ))}
                </select>
              </label>
              {selectedYear !== null && (
                <p>
                  {selectedYear.starts_on} - {selectedYear.ends_on}
                </p>
              )}
            </div>

            {isLoading ? (
              <p className="mail-empty">{t('common.loading')}</p>
            ) : selectedYear === null ? (
              <p className="mail-empty">No academic year.</p>
            ) : (
              <>
                <div className="academic-module-strip">
                  {semesters.length === 0 ? (
                    <span className="academic-module-empty">No semesters</span>
                  ) : (
                    semesters.map((semester) => (
                      <button
                        aria-pressed={semester.id === selectedSemesterId}
                        className="academic-module-button"
                        key={semester.id}
                        onClick={() => {
                          const nextSelected =
                            semester.id === selectedSemesterId ? '' : semester.id
                          setSelectedSemesterId(nextSelected)
                          setSemesterForm(
                            nextSelected === ''
                              ? semesterFormFromYear(selectedYear)
                              : semesterFormFromSemester(semester),
                          )
                        }}
                        type="button"
                      >
                        <strong>{semester.label}</strong>
                        {semester.starts_on.slice(5)} - {semester.ends_on.slice(5)}
                      </button>
                    ))
                  )}
                </div>
                <div className="academic-months-grid">
                  {monthsForYear(selectedYear).map(renderMonth)}
                </div>
                <section className="academic-period-panel">
                  <div className="section-heading">
                    <div>
                      <h2>Period setting</h2>
                      <p>{periods.length} period(s)</p>
                    </div>
                  </div>
                  <div className="academic-period-list">
                    {periods.length === 0 ? (
                      <p className="mail-empty">No periods.</p>
                    ) : (
                      periods.map((period) => (
                        <button
                          aria-pressed={period.id === selectedPeriodId}
                          className="academic-period-row"
                          key={period.id}
                          onClick={() => {
                            setSelectedPeriodId(period.id)
                            setPeriodForm(periodFormFromPeriod(period))
                          }}
                          type="button"
                        >
                          <strong>{period.label}</strong>
                          <span>{period.period_no}</span>
                          <span>{period.starts_at} - {period.ends_at}</span>
                        </button>
                      ))
                    )}
                  </div>
                  <form className="academic-period-form" onSubmit={handleSavePeriod}>
                    <label>
                      <span>No.</span>
                      <input
                        disabled={selectedYear === null}
                        min="1"
                        onChange={(event) => setPeriodForm((current) => ({
                          ...current,
                          period_no: event.target.value,
                        }))}
                        type="number"
                        value={periodForm.period_no}
                      />
                    </label>
                    <label>
                      <span>Label</span>
                      <input
                        disabled={selectedYear === null}
                        onChange={(event) => setPeriodForm((current) => ({
                          ...current,
                          label: event.target.value,
                        }))}
                        value={periodForm.label}
                      />
                    </label>
                    <label>
                      <span>Start</span>
                      <input
                        disabled={selectedYear === null}
                        onChange={(event) => setPeriodForm((current) => ({
                          ...current,
                          starts_at: event.target.value,
                        }))}
                        type="time"
                        value={periodForm.starts_at}
                      />
                    </label>
                    <label>
                      <span>End</span>
                      <input
                        disabled={selectedYear === null}
                        onChange={(event) => setPeriodForm((current) => ({
                          ...current,
                          ends_at: event.target.value,
                        }))}
                        type="time"
                        value={periodForm.ends_at}
                      />
                    </label>
                    <label>
                      <span>Order</span>
                      <input
                        disabled={selectedYear === null}
                        onChange={(event) => setPeriodForm((current) => ({
                          ...current,
                          sort_order: event.target.value,
                        }))}
                        type="number"
                        value={periodForm.sort_order}
                      />
                    </label>
                    <label>
                      <span>Note</span>
                      <input
                        disabled={selectedYear === null}
                        onChange={(event) => setPeriodForm((current) => ({
                          ...current,
                          note: event.target.value,
                        }))}
                        value={periodForm.note}
                      />
                    </label>
                    <div className="academic-period-actions">
                      <button
                        disabled={
                          isSaving ||
                          selectedYear === null ||
                          periodForm.period_no.trim() === '' ||
                          periodForm.label.trim() === ''
                        }
                        type="submit"
                      >
                        {selectedPeriod === undefined ? 'Add period' : 'Save period'}
                      </button>
                      <button
                        disabled={isSaving || selectedPeriod === undefined}
                        onClick={() => void handleDeletePeriod()}
                        type="button"
                      >
                        Delete
                      </button>
                      <button
                        disabled={selectedYear === null}
                        onClick={() => {
                          setSelectedPeriodId('')
                          setPeriodForm(defaultPeriodForm((periods.at(-1)?.period_no ?? 0) + 1))
                        }}
                        type="button"
                      >
                        New period
                      </button>
                    </div>
                  </form>
                </section>
              </>
            )}
          </section>

          <aside className="calendar-panel academic-calendar-editor">
            <form onSubmit={handleCreateYear}>
              <div className="section-heading">
                <h2>Academic year</h2>
              </div>
              <label>
                <span>Label</span>
                <input
                  onChange={(event) => setYearForm((current) => ({
                    ...current,
                    year_label: event.target.value,
                  }))}
                  value={yearForm.year_label}
                />
              </label>
              <div className="academic-date-pair">
                <label>
                  <span>Start</span>
                  <input
                    onChange={(event) => setYearForm((current) => ({
                      ...current,
                      starts_on: event.target.value,
                    }))}
                    type="date"
                    value={yearForm.starts_on}
                  />
                </label>
                <label>
                  <span>End</span>
                  <input
                    onChange={(event) => setYearForm((current) => ({
                      ...current,
                      ends_on: event.target.value,
                    }))}
                    type="date"
                    value={yearForm.ends_on}
                  />
                </label>
              </div>
              <button disabled={isSaving} type="submit">
                Create year
              </button>
            </form>

            <form
              className={`academic-collapsible-form${isHolidaySettingOpen ? ' is-open' : ''}`}
              onSubmit={handleImportHolidays}
            >
              <button
                aria-expanded={isHolidaySettingOpen}
                className="academic-collapsible-heading"
                onClick={() => setIsHolidaySettingOpen((current) => !current)}
                type="button"
              >
                <span>National holidays</span>
                <span>{holidayCsvFile?.name ?? '-'}</span>
                <span aria-hidden="true">{isHolidaySettingOpen ? '-' : '+'}</span>
              </button>
              {isHolidaySettingOpen && (
                <div className="academic-collapsible-body">
              <label>
                <span>CSV file</span>
                <input
                  accept=".csv,text/csv"
                  disabled={selectedYear === null}
                  onChange={(event) => setHolidayCsvFile(event.target.files?.[0] ?? null)}
                  type="file"
                />
              </label>
              <button
                disabled={isSaving || selectedYear === null || holidayCsvFile === null}
                type="submit"
              >
                Import holidays
              </button>
                </div>
              )}
            </form>

            <form
              className={`academic-collapsible-form${
                isSemesterSettingOpen ? ' is-open' : ''
              }`}
              onSubmit={handleSaveSemester}
            >
              <button
                aria-expanded={isSemesterSettingOpen}
                className="academic-collapsible-heading"
                onClick={() => setIsSemesterSettingOpen((current) => !current)}
                type="button"
              >
                <span>Semester setting</span>
                <span aria-hidden="true">{isSemesterSettingOpen ? '-' : '+'}</span>
              </button>
              {isSemesterSettingOpen && (
                <div className="academic-collapsible-body">
              <label>
                <span>Label</span>
                <input
                  disabled={selectedYear === null}
                  onChange={(event) => setSemesterForm((current) => ({
                    ...current,
                    label: event.target.value,
                  }))}
                  value={semesterForm.label}
                />
              </label>
              <div className="academic-date-pair">
                <label>
                  <span>Start</span>
                  <input
                    disabled={selectedYear === null}
                    onChange={(event) => setSemesterForm((current) => ({
                      ...current,
                      starts_on: event.target.value,
                    }))}
                    type="date"
                    value={semesterForm.starts_on}
                  />
                </label>
                <label>
                  <span>End</span>
                  <input
                    disabled={selectedYear === null}
                    onChange={(event) => setSemesterForm((current) => ({
                      ...current,
                      ends_on: event.target.value,
                    }))}
                    type="date"
                    value={semesterForm.ends_on}
                  />
                </label>
              </div>
              <label>
                <span>Order</span>
                <input
                  disabled={selectedYear === null}
                  onChange={(event) => setSemesterForm((current) => ({
                    ...current,
                    sort_order: event.target.value,
                  }))}
                  type="number"
                  value={semesterForm.sort_order}
                />
              </label>
              <label>
                <span>Note</span>
                <textarea
                  disabled={selectedYear === null}
                  onChange={(event) => setSemesterForm((current) => ({
                    ...current,
                    note: event.target.value,
                  }))}
                  value={semesterForm.note}
                />
              </label>
              <div className="academic-editor-actions">
                <button
                  disabled={isSaving || selectedYear === null || semesterForm.label.trim() === ''}
                  type="submit"
                >
                  {selectedSemester === undefined ? 'Add semester' : 'Save semester'}
                </button>
                <button
                  disabled={isSaving || selectedSemester === undefined}
                  onClick={() => void handleDeleteSemester()}
                  type="button"
                >
                  Delete
                </button>
              </div>
              <button
                disabled={selectedYear === null}
                onClick={() => {
                  setSelectedSemesterId('')
                  setSemesterForm(semesterFormFromYear(selectedYear))
                }}
                type="button"
              >
                New semester
              </button>
                </div>
              )}
            </form>

            <form
              className={`academic-collapsible-form${isDaySettingOpen ? ' is-open' : ''}`}
              onSubmit={handleSaveDay}
            >
              <button
                aria-expanded={isDaySettingOpen}
                className="academic-collapsible-heading"
                onClick={() => setIsDaySettingOpen((current) => !current)}
                type="button"
              >
                <span>Day setting</span>
                <span>{selectedDate ?? '-'}</span>
                <span aria-hidden="true">{isDaySettingOpen ? '-' : '+'}</span>
              </button>
              {isDaySettingOpen && (
                <div className="academic-collapsible-body">
              <label>
                <span>Type</span>
                <select
                  disabled={dayForm === null}
                  onChange={(event) => {
                    const nextDayType = event.target.value as AcademicCalendarDayType
                    setDayForm((current) => current === null ? null : ({
                      ...current,
                      day_type: nextDayType,
                      is_teaching_day:
                        nextDayType === 'holiday' || nextDayType === 'no_class_day'
                          ? false
                          : current.is_teaching_day,
                      effective_weekday:
                        nextDayType === 'holiday' || nextDayType === 'no_class_day'
                          ? ''
                          : current.effective_weekday,
                      label:
                        current.label === '' || dayTypes.some((item) => item.label === current.label)
                          ? dayTypes.find((item) => item.value === nextDayType)?.label ?? current.label
                          : current.label,
                    }))
                  }}
                  value={dayForm?.day_type ?? 'normal'}
                >
                  {dayTypes.map((dayType) => (
                    <option key={dayType.value} value={dayType.value}>
                      {dayType.label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>Label</span>
                <input
                  disabled={dayForm === null}
                  onChange={(event) => setDayForm((current) => current === null ? null : ({
                    ...current,
                    label: event.target.value,
                  }))}
                  value={dayForm?.label ?? ''}
                />
              </label>
              <label>
                <span>Class weekday</span>
                <select
                  disabled={dayForm === null}
                  onChange={(event) => setDayForm((current) => current === null ? null : ({
                    ...current,
                    effective_weekday: event.target.value,
                  }))}
                  value={dayForm?.effective_weekday ?? ''}
                >
                  <option value="">None</option>
                  {weekdayLabels.map((weekday, index) => (
                    <option key={weekday} value={index}>
                      {weekday}
                    </option>
                  ))}
                </select>
              </label>
              <label className="academic-checkbox">
                <input
                  checked={dayForm?.is_teaching_day ?? false}
                  disabled={dayForm === null}
                  onChange={(event) => setDayForm((current) => current === null ? null : ({
                    ...current,
                    is_teaching_day: event.target.checked,
                  }))}
                  type="checkbox"
                />
                <span>Teaching day</span>
              </label>
              <label>
                <span>Note</span>
                <textarea
                  disabled={dayForm === null}
                  onChange={(event) => setDayForm((current) => current === null ? null : ({
                    ...current,
                    note: event.target.value,
                  }))}
                  value={dayForm?.note ?? ''}
                />
              </label>
              <div className="academic-editor-actions">
                <button disabled={isSaving || dayForm === null} type="submit">
                  Save day
                </button>
                <button
                  disabled={isSaving || selectedDay === undefined}
                  onClick={() => void handleDeleteDay()}
                  type="button"
                >
                  Reset
                </button>
              </div>
                </div>
              )}
            </form>
          </aside>
        </div>
      </div>
    </main>
  )
}

export default AcademicCalendarView
