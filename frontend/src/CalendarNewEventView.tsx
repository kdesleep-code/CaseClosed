import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { AppLink, TopNav, navigateTo, returnToOrFallback } from './navigation'
import {
  createCalendarDbEventLink,
  createGoogleCalendarEvent,
  getGoogleGmailStatus,
  listGoogleCalendars,
  toJstIsoDateTime,
} from './phase4Api'
import type { GoogleCalendarListItem } from './phase4Api'
import { isCaseOpenForSuggestion, listCases } from './phase7Api'
import type { CaseItem } from './phase7Api'
import { listTasks } from './phase8Api'
import type { TaskItem } from './phase8Api'
import {
  listAcademicCalendarDays,
  listAcademicPeriods,
  listAcademicSemesters,
  listAcademicYears,
  type AcademicCalendarDay,
  type AcademicPeriod,
  type AcademicSemester,
  type AcademicYear,
} from './academicCalendarApi'
import SuggestInput from './SuggestInput'
import { t } from './i18n'

const recurrenceWeekdays = [
  { value: 'SU', labelKey: 'tasks.recurrence.weekday.sun' },
  { value: 'MO', labelKey: 'tasks.recurrence.weekday.mon' },
  { value: 'TU', labelKey: 'tasks.recurrence.weekday.tue' },
  { value: 'WE', labelKey: 'tasks.recurrence.weekday.wed' },
  { value: 'TH', labelKey: 'tasks.recurrence.weekday.thu' },
  { value: 'FR', labelKey: 'tasks.recurrence.weekday.fri' },
  { value: 'SA', labelKey: 'tasks.recurrence.weekday.sat' },
] as const

const recurrenceMonthWeeks = [
  { value: '1', labelKey: 'tasks.recurrence.week.first' },
  { value: '2', labelKey: 'tasks.recurrence.week.second' },
  { value: '3', labelKey: 'tasks.recurrence.week.third' },
  { value: '4', labelKey: 'tasks.recurrence.week.fourth' },
  { value: '5', labelKey: 'tasks.recurrence.week.fifth' },
  { value: '-1', labelKey: 'tasks.recurrence.week.last' },
] as const

const academicWeekdays = [
  { value: 0, label: 'Sun' },
  { value: 1, label: 'Mon' },
  { value: 2, label: 'Tue' },
  { value: 3, label: 'Wed' },
  { value: 4, label: 'Thu' },
  { value: 5, label: 'Fri' },
  { value: 6, label: 'Sat' },
] as const

const visibleTimeOptions = Array.from({ length: 61 }, (_, index) => {
  const totalMinutes = 6 * 60 + index * 15
  const hour = Math.floor(totalMinutes / 60)
  const minute = totalMinutes % 60
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`
})

function jstDateToday() {
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

function roundedDefaultTime(offsetHours: number) {
  const now = new Date()
  now.setMinutes(now.getMinutes() < 30 ? 30 : 60, 0, 0)
  now.setHours(now.getHours() + offsetHours)
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Tokyo',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  })
    .formatToParts(now)
    .reduce<Record<string, string>>((values, part) => {
      values[part.type] = part.value
      return values
    }, {})
  const value = `${parts.hour}:${parts.minute}`
  if (value < visibleTimeOptions[0]) return visibleTimeOptions[0]
  if (value > visibleTimeOptions[visibleTimeOptions.length - 1]) {
    return visibleTimeOptions[visibleTimeOptions.length - 1]
  }
  return visibleTimeOptions.reduce((closest, option) => {
    const currentDistance = Math.abs(timeMinutes(option) - timeMinutes(value))
    const closestDistance = Math.abs(timeMinutes(closest) - timeMinutes(value))
    return currentDistance < closestDistance ? option : closest
  }, visibleTimeOptions[0])
}

function describeError(error: unknown) {
  return error instanceof Error ? error.message : t('app.requestFailed')
}

function selectedCaseFor(value: string, cases: CaseItem[]) {
  const query = value.trim().toLowerCase()
  if (query === '') return null
  return (
    cases.find((item) => item.id.toLowerCase() === query || item.name.toLowerCase() === query) ??
    null
  )
}

function selectedTaskFor(value: string, tasks: TaskItem[]) {
  const query = value.trim().toLowerCase()
  if (query === '') return null
  const exactMatches = tasks.filter(
    (item) => item.id.toLowerCase() === query || item.title.toLowerCase() === query,
  )
  return exactMatches.length === 1 ? exactMatches[0] : null
}

function weekdayForDate(value: string) {
  const date = new Date(`${value}T00:00:00Z`)
  return recurrenceWeekdays[date.getUTCDay()]?.value ?? 'MO'
}

function numericWeekdayForDate(value: string) {
  return new Date(`${value}T00:00:00Z`).getUTCDay()
}

function addDateDays(value: string, days: number) {
  const [year, month, day] = value.split('-').map(Number)
  const date = new Date(Date.UTC(year, month - 1, day + days))
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, '0')}-${String(
    date.getUTCDate(),
  ).padStart(2, '0')}`
}

function untilPart(value: string) {
  return value.trim() === '' ? '' : `;UNTIL=${value.replaceAll('-', '')}T145959Z`
}

function monthDayToRRuleDay(value: string) {
  const parsed = Number(value)
  if (parsed === 0) return -1
  if (parsed < 0) return parsed - 1
  return parsed
}

function datePart(value: string, fallback: number, index: number) {
  const parts = value.split('-')
  const parsed = Number(parts[index])
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback
}

function isVisibleCalendarTime(value: string) {
  return visibleTimeOptions.includes(value)
}

function timeMinutes(value: string) {
  const [hour = '0', minute = '0'] = value.split(':')
  return Number(hour) * 60 + Number(minute)
}

function visibleTimeFromMinutes(value: number) {
  const minMinutes = timeMinutes(visibleTimeOptions[0])
  const maxMinutes = timeMinutes(visibleTimeOptions[visibleTimeOptions.length - 1])
  const clamped = Math.min(maxMinutes, Math.max(minMinutes, value))
  const rounded = Math.round(clamped / 15) * 15
  const hour = Math.floor(rounded / 60)
  const minute = rounded % 60
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`
}

function isWeekendDate(value: string) {
  const weekday = numericWeekdayForDate(value)
  return weekday === 0 || weekday === 6
}

function dayIsTeachingDate(date: string, day: AcademicCalendarDay | undefined) {
  if (day === undefined) return !isWeekendDate(date)
  if (day.day_type === 'holiday' || day.day_type === 'no_class_day') return false
  return day.is_teaching_day
}

function effectiveAcademicWeekday(date: string, day: AcademicCalendarDay | undefined) {
  return day?.effective_weekday ?? numericWeekdayForDate(date)
}

function academicOccurrenceLabel(day: AcademicCalendarDay | undefined, semester: AcademicSemester) {
  const label = day?.label.trim() ?? ''
  if (label === '' || label === 'Normal' || label === 'Weekend') return semester.label
  return label
}

function newAcademicSeriesId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `academic_series_${crypto.randomUUID().replaceAll('-', '')}`
  }
  return `academic_series_${Date.now().toString(36)}_${Math.random().toString(36).slice(2)}`
}

function displayPeriodTime(value: string) {
  return value.slice(0, 5)
}

export default function CalendarNewEventView() {
  const preselectedCaseId = new URLSearchParams(window.location.search).get('case_id')
  const cancelHref = returnToOrFallback(
    preselectedCaseId === null ? '/calendar' : `/cases/${encodeURIComponent(preselectedCaseId)}`,
  )
  const [calendars, setCalendars] = useState<GoogleCalendarListItem[]>([])
  const [cases, setCases] = useState<CaseItem[]>([])
  const [tasks, setTasks] = useState<TaskItem[]>([])
  const [calendarId, setCalendarId] = useState('primary')
  const [summary, setSummary] = useState('')
  const [startDate, setStartDate] = useState(jstDateToday)
  const [endDate, setEndDate] = useState(jstDateToday)
  const [startTime, setStartTime] = useState(() => roundedDefaultTime(0))
  const [endTime, setEndTime] = useState(() => roundedDefaultTime(1))
  const [hasEditedStartTime, setHasEditedStartTime] = useState(false)
  const [location, setLocation] = useState('')
  const [description, setDescription] = useState('')
  const [recurrenceType, setRecurrenceType] = useState('')
  const [recurrenceMonthDay, setRecurrenceMonthDay] = useState(() =>
    String(datePart(jstDateToday(), 1, 2)),
  )
  const [recurrenceMonthPattern, setRecurrenceMonthPattern] = useState<'day' | 'weekday'>('day')
  const [recurrenceMonthWeek, setRecurrenceMonthWeek] = useState('1')
  const [recurrenceMonthWeekday, setRecurrenceMonthWeekday] = useState<string>(() =>
    weekdayForDate(jstDateToday()),
  )
  const [recurrenceYearMonth, setRecurrenceYearMonth] = useState(() =>
    String(datePart(jstDateToday(), 1, 1)),
  )
  const [recurrenceYearDay, setRecurrenceYearDay] = useState(() =>
    String(datePart(jstDateToday(), 1, 2)),
  )
  const [recurrenceWeekdayValues, setRecurrenceWeekdayValues] = useState<string[]>([])
  const [recurrenceUntil, setRecurrenceUntil] = useState('')
  const [academicYears, setAcademicYears] = useState<AcademicYear[]>([])
  const [academicSemesters, setAcademicSemesters] = useState<AcademicSemester[]>([])
  const [academicDays, setAcademicDays] = useState<AcademicCalendarDay[]>([])
  const [academicPeriods, setAcademicPeriods] = useState<AcademicPeriod[]>([])
  const [selectedAcademicYearId, setSelectedAcademicYearId] = useState('')
  const [selectedAcademicSemesterIds, setSelectedAcademicSemesterIds] = useState<string[]>([])
  const [selectedAcademicWeekday, setSelectedAcademicWeekday] = useState(1)
  const [selectedAcademicPeriodIds, setSelectedAcademicPeriodIds] = useState<string[]>([])
  const [academicMaxOccurrences, setAcademicMaxOccurrences] = useState('5')
  const [isAcademicLoading, setIsAcademicLoading] = useState(false)
  const [caseInput, setCaseInput] = useState('')
  const [taskInput, setTaskInput] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [isCreating, setIsCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const isAcademicRepeat = recurrenceType === 'academic'
  const isStandardRepeat = recurrenceType !== '' && !isAcademicRepeat

  const writableCalendars = useMemo(
    () => calendars.filter((calendar) => calendar.can_write),
    [calendars],
  )

  const academicDayMap = useMemo(() => {
    return new Map(academicDays.map((day) => [day.date, day]))
  }, [academicDays])

  const selectedAcademicSemesters = useMemo(() => {
    const selectedIds = new Set(selectedAcademicSemesterIds)
    return academicSemesters
      .filter((semester) => selectedIds.has(semester.id))
      .sort((left, right) => {
        if (left.starts_on !== right.starts_on) return left.starts_on.localeCompare(right.starts_on)
        return left.sort_order - right.sort_order
      })
  }, [academicSemesters, selectedAcademicSemesterIds])

  const selectedAcademicPeriods = useMemo(() => {
    const selectedIds = new Set(selectedAcademicPeriodIds)
    return academicPeriods
      .filter((period) => selectedIds.has(period.id))
      .sort((left, right) => {
        if (left.starts_at !== right.starts_at) return left.starts_at.localeCompare(right.starts_at)
        return left.sort_order - right.sort_order
      })
  }, [academicPeriods, selectedAcademicPeriodIds])

  const academicRepeatOccurrences = useMemo(() => {
    if (!isAcademicRepeat || selectedAcademicSemesters.length === 0 || selectedAcademicPeriods.length === 0) {
      return []
    }
    const firstPeriod = selectedAcademicPeriods[0]
    const lastPeriod = selectedAcademicPeriods[selectedAcademicPeriods.length - 1]
    const maxOccurrences = Number(academicMaxOccurrences)
    const limit =
      Number.isInteger(maxOccurrences) && maxOccurrences > 0 ? maxOccurrences : Number.POSITIVE_INFINITY
    const occurrences: Array<{ date: string; startTime: string; endTime: string; label: string }> = []
    const includedDates = new Set<string>()
    for (const semester of selectedAcademicSemesters) {
      for (
        let date = semester.starts_on;
        date <= semester.ends_on && occurrences.length < limit;
        date = addDateDays(date, 1)
      ) {
        if (includedDates.has(date)) continue
        const academicDay = academicDayMap.get(date)
        if (
          dayIsTeachingDate(date, academicDay) &&
          effectiveAcademicWeekday(date, academicDay) === selectedAcademicWeekday
        ) {
          includedDates.add(date)
          occurrences.push({
            date,
            startTime: displayPeriodTime(firstPeriod.starts_at),
            endTime: displayPeriodTime(lastPeriod.ends_at),
            label: academicOccurrenceLabel(academicDay, semester),
          })
        }
      }
    }
    return occurrences.sort((left, right) => left.date.localeCompare(right.date)).slice(0, limit)
  }, [
    academicDayMap,
    academicMaxOccurrences,
    isAcademicRepeat,
    selectedAcademicPeriods,
    selectedAcademicSemesters,
    selectedAcademicWeekday,
  ])

  const recurrenceRule = useMemo(() => {
    if (recurrenceType === '') return null
    if (recurrenceType === 'monthly') {
      if (recurrenceMonthPattern === 'weekday') {
        return `RRULE:FREQ=MONTHLY;BYDAY=${recurrenceMonthWeekday};BYSETPOS=${recurrenceMonthWeek}${untilPart(
          recurrenceUntil,
        )}`
      }
      return `RRULE:FREQ=MONTHLY;BYMONTHDAY=${monthDayToRRuleDay(
        recurrenceMonthDay,
      )}${untilPart(
        recurrenceUntil,
      )}`
    }
    if (recurrenceType === 'yearly') {
      if (recurrenceMonthPattern === 'weekday') {
        return `RRULE:FREQ=YEARLY;BYMONTH=${recurrenceYearMonth};BYDAY=${recurrenceMonthWeekday};BYSETPOS=${recurrenceMonthWeek}${untilPart(
          recurrenceUntil,
        )}`
      }
      return `RRULE:FREQ=YEARLY;BYMONTH=${recurrenceYearMonth};BYMONTHDAY=${recurrenceYearDay}${untilPart(
        recurrenceUntil,
      )}`
    }
    if (recurrenceType === 'weekly' || recurrenceType === 'biweekly') {
      const weekdays =
        recurrenceWeekdayValues.length === 0 ? [weekdayForDate(startDate)] : recurrenceWeekdayValues
      const interval = recurrenceType === 'biweekly' ? ';INTERVAL=2' : ''
      return `RRULE:FREQ=WEEKLY${interval};BYDAY=${weekdays.join(',')}${untilPart(
        recurrenceUntil,
      )}`
    }
    return null
  }, [
    startDate,
    recurrenceMonthDay,
    recurrenceMonthPattern,
    recurrenceMonthWeek,
    recurrenceMonthWeekday,
    recurrenceType,
    recurrenceUntil,
    recurrenceWeekdayValues,
    recurrenceYearDay,
    recurrenceYearMonth,
  ])

  useEffect(() => {
    let isMounted = true
    setIsLoading(true)
    Promise.all([
      getGoogleGmailStatus(),
      listGoogleCalendars(),
      listCases('all'),
      listTasks({ limit: 200 }),
      listAcademicYears(),
      listAcademicPeriods(),
    ])
      .then(([status, calendarItems, caseItems, taskItems, yearItems, periodItems]) => {
        if (!isMounted) return
        if (status.connected !== true || status.calendar_write_enabled !== true) {
          setError(t('calendar.writeDisabled'))
        } else {
          setError(null)
        }
        setCalendars(calendarItems)
        const writableItems = calendarItems.filter((calendar) => calendar.can_write)
        const primaryWritable = writableItems.find((calendar) => calendar.primary)
        setCalendarId(primaryWritable?.id ?? writableItems[0]?.id ?? 'primary')
        const caseMap = new Map<string, CaseItem>()
        caseItems
          .filter((item) => isCaseOpenForSuggestion(item))
          .forEach((item) => caseMap.set(item.id, item))
        if (preselectedCaseId !== null) {
          const preselectedCase = caseItems.find((item) => item.id === preselectedCaseId)
          if (preselectedCase !== undefined) {
            caseMap.set(preselectedCase.id, preselectedCase)
            setCaseInput((current) => current || preselectedCase.name)
          }
        }
        setCases(Array.from(caseMap.values()))
        setTasks(
          taskItems.filter(
            (item) => item.deleted_at === null && item.status !== 'done' && item.status !== 'archived',
          ),
        )
        const sortedYears = [...yearItems].sort((left, right) =>
          right.starts_on.localeCompare(left.starts_on),
        )
        const sortedPeriods = [...periodItems].sort((left, right) => {
          if (left.sort_order !== right.sort_order) return left.sort_order - right.sort_order
          return left.period_no - right.period_no
        })
        const today = jstDateToday()
        const currentYear =
          sortedYears.find((item) => item.starts_on <= today && today <= item.ends_on) ??
          sortedYears[0]
        setAcademicYears(sortedYears)
        setAcademicPeriods(sortedPeriods)
        setSelectedAcademicYearId(currentYear?.id ?? '')
        setSelectedAcademicPeriodIds(sortedPeriods[0] === undefined ? [] : [sortedPeriods[0].id])
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
  }, [preselectedCaseId])

  useEffect(() => {
    if (selectedAcademicYearId === '') {
      setAcademicSemesters([])
      setAcademicDays([])
      setSelectedAcademicSemesterIds([])
      return
    }
    let isMounted = true
    setIsAcademicLoading(true)
    Promise.all([
      listAcademicSemesters(selectedAcademicYearId),
      listAcademicCalendarDays(selectedAcademicYearId),
    ])
      .then(([semesterItems, dayItems]) => {
        if (!isMounted) return
        const sortedSemesters = [...semesterItems].sort((left, right) => {
          if (left.sort_order !== right.sort_order) return left.sort_order - right.sort_order
          return left.starts_on.localeCompare(right.starts_on)
        })
        const today = jstDateToday()
        const defaultSemester =
          sortedSemesters.find((item) => item.starts_on <= today && today <= item.ends_on) ??
          sortedSemesters[0]
        setAcademicSemesters(sortedSemesters)
        setAcademicDays(dayItems)
        setSelectedAcademicSemesterIds((current) =>
          current.some((id) => sortedSemesters.some((item) => item.id === id))
            ? current.filter((id) => sortedSemesters.some((item) => item.id === id))
            : defaultSemester === undefined
              ? []
              : [defaultSemester.id],
        )
      })
      .catch((requestError) => {
        if (isMounted) setError(describeError(requestError))
      })
      .finally(() => {
        if (isMounted) setIsAcademicLoading(false)
      })
    return () => {
      isMounted = false
    }
  }, [selectedAcademicYearId])

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const selectedCase = selectedCaseFor(caseInput, cases)
    const selectedTask = selectedTaskFor(taskInput, tasks)
    if (
      summary.trim() === '' ||
      (!isAcademicRepeat &&
        (startDate.trim() === '' ||
          endDate.trim() === '' ||
          startTime.trim() === '' ||
          endTime.trim() === ''))
    ) {
      setError(t('calendar.create.required'))
      return
    }
    if (!isAcademicRepeat && (!isVisibleCalendarTime(startTime) || !isVisibleCalendarTime(endTime))) {
      setError(t('calendar.create.outOfVisibleRange'))
      return
    }
    if (!isAcademicRepeat && `${endDate}T${endTime}` <= `${startDate}T${startTime}`) {
      setError(t('calendar.create.invalidDateOrder'))
      return
    }
    if (caseInput.trim() !== '' && selectedCase === null) {
      setError(t('calendar.event.linkSelectRequired'))
      return
    }
    if (taskInput.trim() !== '' && selectedTask === null) {
      setError(t('calendar.event.linkSelectRequired'))
      return
    }
    if (
      !isAcademicRepeat &&
      (recurrenceType === 'weekly' || recurrenceType === 'biweekly') &&
      recurrenceWeekdayValues.length === 0
    ) {
      setError(t('tasks.recurrence.weekdayRequired'))
      return
    }
    if (isAcademicRepeat) {
      if (
        selectedAcademicYearId === '' ||
        selectedAcademicSemesters.length === 0 ||
        selectedAcademicPeriods.length === 0
      ) {
        setError('Academic year, semester, and period are required.')
        return
      }
      if (academicRepeatOccurrences.length === 0) {
        setError('No teaching dates match this Academic Calendar repeat setting.')
        return
      }
    }
    const parsedMonthDay = Number(recurrenceMonthDay)
    const parsedMonthWeek = Number(recurrenceMonthWeek)
    const parsedYearMonth = Number(recurrenceYearMonth)
    const parsedYearDay = Number(recurrenceYearDay)
    if (
      recurrenceType === 'monthly' &&
      recurrenceMonthPattern === 'day' &&
      (!Number.isInteger(parsedMonthDay) || parsedMonthDay < -30 || parsedMonthDay > 31)
    ) {
      setError(t('calendar.create.invalidMonthDay'))
      return
    }
    if (
      (recurrenceType === 'monthly' || recurrenceType === 'yearly') &&
      recurrenceMonthPattern === 'weekday' &&
      (!Number.isInteger(parsedMonthWeek) ||
        ![1, 2, 3, 4, 5, -1].includes(parsedMonthWeek))
    ) {
      setError(t('tasks.recurrence.invalidMonthWeek'))
      return
    }
    if (
      recurrenceType === 'yearly' &&
      recurrenceMonthPattern === 'day' &&
      (!Number.isInteger(parsedYearMonth) ||
        parsedYearMonth < 1 ||
        parsedYearMonth > 12 ||
        !Number.isInteger(parsedYearDay) ||
        parsedYearDay < 1 ||
        parsedYearDay > 31)
    ) {
      setError(t('calendar.create.invalidYearlyDate'))
      return
    }
    setIsCreating(true)
    setError(null)
    try {
      if (isAcademicRepeat) {
        const createdEventIds: string[] = []
        const academicSeriesId = newAcademicSeriesId()
        for (const occurrence of academicRepeatOccurrences) {
          const result = await createGoogleCalendarEvent({
            calendar_id: calendarId,
            summary: summary.trim(),
            start: toJstIsoDateTime(`${occurrence.date}T${occurrence.startTime}`),
            end: toJstIsoDateTime(`${occurrence.date}T${occurrence.endTime}`),
            location: location.trim() === '' ? null : location,
            description: description.trim() === '' ? null : description,
            recurrence_rule: null,
            time_zone: 'Asia/Tokyo',
            linked_case_id: selectedCase?.id ?? null,
            academic_series_id: academicSeriesId,
          })
          const eventId = result.db_event?.id ?? null
          if (eventId !== null) {
            createdEventIds.push(eventId)
            if (selectedTask !== null) {
              await createCalendarDbEventLink(eventId, {
                linked_type: 'task',
                linked_id: selectedTask.id,
                role: 'related',
              })
            }
          }
        }
        if (createdEventIds.length === 1) {
          navigateTo(
            `/calendar/events/${encodeURIComponent(createdEventIds[0])}?return_to=${encodeURIComponent(
              cancelHref,
            )}`,
          )
        } else {
          navigateTo(cancelHref)
        }
        return
      }
      const result = await createGoogleCalendarEvent({
        calendar_id: calendarId,
        summary: summary.trim(),
        start: toJstIsoDateTime(`${startDate}T${startTime}`),
        end: toJstIsoDateTime(`${endDate}T${endTime}`),
        location: location.trim() === '' ? null : location,
        description: description.trim() === '' ? null : description,
        recurrence_rule: recurrenceRule,
        time_zone: 'Asia/Tokyo',
        linked_case_id: selectedCase?.id ?? null,
      })
      const eventId = result.db_event?.id ?? null
      if (eventId !== null && selectedTask !== null) {
        await createCalendarDbEventLink(eventId, {
          linked_type: 'task',
          linked_id: selectedTask.id,
          role: 'related',
        })
      }
      if (eventId !== null) {
        navigateTo(
          `/calendar/events/${encodeURIComponent(eventId)}?return_to=${encodeURIComponent(
            cancelHref,
          )}`,
        )
      } else {
        navigateTo(cancelHref)
      }
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsCreating(false)
    }
  }

  function handleStartTimeChange(nextStartTime: string) {
    const previousStartMinutes = timeMinutes(startTime)
    const nextStartMinutes = timeMinutes(nextStartTime)
    const nextEndTime = hasEditedStartTime
      ? visibleTimeFromMinutes(timeMinutes(endTime) + nextStartMinutes - previousStartMinutes)
      : visibleTimeFromMinutes(nextStartMinutes + 60)
    setStartTime(nextStartTime)
    setEndTime(nextEndTime)
    setHasEditedStartTime(true)
  }

  function isEndTimeUnavailable(option: string) {
    return endDate === startDate && timeMinutes(option) <= timeMinutes(startTime)
  }

  return (
    <main className="app-shell">
      <div className="calendar-shell">
        <header className="maintenance-header">
          <div>
            <p>{t('app.name')}</p>
            <h1>{t('calendar.create.heading')}</h1>
          </div>
          <TopNav
            ariaLabelKey="calendar.navigation"
            items={[
              { href: '/calendar', labelKey: 'nav.calendar' },
              { href: '/', labelKey: 'top.heading' },
            ]}
          />
        </header>

        {error !== null && (
          <div className="mail-feedback">
            <p role="alert">{error}</p>
          </div>
        )}

        <div className="calendar-event-detail-layout calendar-create-layout">
          <form
            className="calendar-event-detail-main calendar-create-form"
            id="calendar-new-event-form"
            onSubmit={handleSubmit}
          >
            <section className="case-panel">
              <h2>{t('calendar.create.heading')}</h2>
              <div className="calendar-create-grid">
                <label>
                  <span>{t('calendar.create.summary')}</span>
                  <input
                    disabled={isCreating}
                    onChange={(event) => setSummary(event.target.value)}
                    value={summary}
                  />
                </label>
                {recurrenceType === '' && (
                  <>
                    <div className="calendar-create-date-time-group">
                      <span>{t('calendar.create.start')}</span>
                      <div>
                        <input
                          disabled={isCreating}
                          onChange={(event) => {
                            setStartDate(event.target.value)
                            if (endDate.trim() === '' || endDate < event.target.value) {
                              setEndDate(event.target.value)
                            }
                          }}
                          type="date"
                          value={startDate}
                        />
                        <select
                          disabled={isCreating}
                          onChange={(event) => handleStartTimeChange(event.target.value)}
                          value={startTime}
                        >
                          {visibleTimeOptions.map((option) => (
                            <option key={option} value={option}>
                              {option}
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>
                    <div className="calendar-create-date-time-group">
                      <span>{t('calendar.create.end')}</span>
                      <div>
                        <input
                          disabled={isCreating}
                          onChange={(event) => {
                            const nextEndDate = event.target.value
                            setEndDate(nextEndDate)
                            if (
                              nextEndDate === startDate &&
                              timeMinutes(endTime) <= timeMinutes(startTime)
                            ) {
                              setEndTime(visibleTimeFromMinutes(timeMinutes(startTime) + 15))
                            }
                          }}
                          type="date"
                          value={endDate}
                        />
                        <select
                          disabled={isCreating}
                          onChange={(event) => setEndTime(event.target.value)}
                          value={endTime}
                        >
                          {visibleTimeOptions.map((option) => (
                            <option
                              disabled={isEndTimeUnavailable(option)}
                              key={option}
                              value={option}
                            >
                              {option}
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>
                  </>
                )}
              </div>
              <div className="calendar-create-location-row">
                <label>
                  <span>{t('calendar.create.location')}</span>
                  <input
                    disabled={isCreating}
                    onChange={(event) => setLocation(event.target.value)}
                    value={location}
                  />
                </label>
                <label>
                  <span>{t('calendar.source.heading')}</span>
                  <select
                    disabled={isLoading || isCreating}
                    onChange={(event) => setCalendarId(event.target.value)}
                    value={calendarId}
                  >
                    {writableCalendars.length === 0 ? (
                      <option value="primary">{t('calendar.source.primary')}</option>
                    ) : (
                      writableCalendars.map((calendar) => (
                        <option key={calendar.id} value={calendar.id}>
                          {calendar.summary || calendar.id}
                        </option>
                      ))
                    )}
                  </select>
                </label>
              </div>
              <label>
                <span>{t('calendar.create.description')}</span>
                <textarea
                  disabled={isCreating}
                  onChange={(event) => setDescription(event.target.value)}
                  value={description}
                />
              </label>
              <div className="calendar-create-repeat-row">
                <label>
                  <span>{t('calendar.create.repeat')}</span>
                  <select
                    disabled={isCreating}
                    onChange={(event) => {
                      const nextType = event.target.value
                      setRecurrenceType(nextType)
                      if (nextType !== '' && nextType !== 'academic') {
                        setEndDate(startDate)
                      }
                      if (nextType === 'monthly') {
                        setRecurrenceMonthDay(String(datePart(startDate, 1, 2)))
                        setRecurrenceMonthWeekday(weekdayForDate(startDate))
                      }
                      if (nextType === 'yearly') {
                        setRecurrenceYearMonth(String(datePart(startDate, 1, 1)))
                        setRecurrenceYearDay(String(datePart(startDate, 1, 2)))
                        setRecurrenceMonthWeekday(weekdayForDate(startDate))
                      }
                      if (
                        (nextType === 'weekly' || nextType === 'biweekly') &&
                        recurrenceWeekdayValues.length === 0
                      ) {
                        setRecurrenceWeekdayValues([weekdayForDate(startDate)])
                      }
                      if (nextType === 'academic' && selectedAcademicPeriodIds.length === 0) {
                        setSelectedAcademicPeriodIds(
                          academicPeriods[0] === undefined ? [] : [academicPeriods[0].id],
                        )
                      }
                    }}
                    value={recurrenceType}
                  >
                    <option value="">{t('tasks.recurrence.none')}</option>
                    <option value="weekly">{t('tasks.recurrence.weekly')}</option>
                    <option value="biweekly">{t('tasks.recurrence.biweekly')}</option>
                    <option value="monthly">{t('tasks.recurrence.monthly')}</option>
                    <option value="yearly">{t('tasks.recurrence.yearly')}</option>
                    <option value="academic">Academic Calendar</option>
                  </select>
                </label>
                {(recurrenceType === 'monthly' || recurrenceType === 'yearly') && (
                  <label>
                    <span>{t('tasks.recurrence.monthPattern')}</span>
                    <select
                      disabled={isCreating}
                      onChange={(event) =>
                        setRecurrenceMonthPattern(event.target.value as 'day' | 'weekday')
                      }
                      value={recurrenceMonthPattern}
                    >
                      <option value="day">{t('tasks.recurrence.patternDay')}</option>
                      <option value="weekday">{t('tasks.recurrence.patternWeekday')}</option>
                    </select>
                  </label>
                )}
                {recurrenceType === 'monthly' && recurrenceMonthPattern === 'day' && (
                  <label>
                    <span>{t('calendar.create.monthDay')}</span>
                    <input
                      disabled={isCreating}
                      max="31"
                      min="-30"
                      onChange={(event) => setRecurrenceMonthDay(event.target.value)}
                      type="number"
                      value={recurrenceMonthDay}
                    />
                  </label>
                )}
                {recurrenceType === 'yearly' && (
                  <div className="calendar-create-yearly-fields">
                    <label>
                      <span>{t('calendar.create.yearMonth')}</span>
                      <input
                        disabled={isCreating}
                        max="12"
                        min="1"
                        onChange={(event) => setRecurrenceYearMonth(event.target.value)}
                        type="number"
                        value={recurrenceYearMonth}
                      />
                    </label>
                    {recurrenceMonthPattern === 'day' && (
                      <label>
                        <span>{t('calendar.create.yearDay')}</span>
                        <input
                          disabled={isCreating}
                          max="31"
                          min="1"
                          onChange={(event) => setRecurrenceYearDay(event.target.value)}
                          type="number"
                          value={recurrenceYearDay}
                        />
                      </label>
                    )}
                  </div>
                )}
                {(recurrenceType === 'monthly' || recurrenceType === 'yearly') &&
                  recurrenceMonthPattern === 'weekday' && (
                    <div className="calendar-create-yearly-fields">
                      <label>
                        <span>{t('tasks.recurrence.monthWeek')}</span>
                        <select
                          disabled={isCreating}
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
                      <label>
                        <span>{t('tasks.recurrence.monthWeekday')}</span>
                        <select
                          disabled={isCreating}
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
                    </div>
                  )}
                <div aria-hidden="true" />
              </div>
              {isStandardRepeat && (
                <div className="calendar-create-repeat-time-row">
                  <label>
                    <span>Repeat start</span>
                    <input
                      disabled={isCreating}
                      onChange={(event) => {
                        const nextStartDate = event.target.value
                        setStartDate(nextStartDate)
                        setEndDate(nextStartDate)
                      }}
                      type="date"
                      value={startDate}
                    />
                  </label>
                  <label>
                    <span>{t('calendar.create.start')}</span>
                    <select
                      disabled={isCreating}
                      onChange={(event) => handleStartTimeChange(event.target.value)}
                      value={startTime}
                    >
                      {visibleTimeOptions.map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>{t('calendar.create.end')}</span>
                    <select
                      disabled={isCreating}
                      onChange={(event) => {
                        setEndDate(startDate)
                        setEndTime(event.target.value)
                      }}
                      value={endTime}
                    >
                      {visibleTimeOptions.map((option) => (
                        <option disabled={isEndTimeUnavailable(option)} key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>{t('calendar.create.repeatUntil')}</span>
                    <input
                      disabled={isCreating}
                      onChange={(event) => setRecurrenceUntil(event.target.value)}
                      type="date"
                      value={recurrenceUntil}
                    />
                  </label>
                </div>
              )}
              {(recurrenceType === 'weekly' || recurrenceType === 'biweekly') && (
                <div className="task-recurrence-weekdays calendar-create-weekdays">
                  {recurrenceWeekdays.map((weekday) => (
                    <label key={weekday.value}>
                      <input
                        checked={recurrenceWeekdayValues.includes(weekday.value)}
                        disabled={isCreating}
                        onChange={(event) => {
                          setRecurrenceWeekdayValues((current) =>
                            event.target.checked
                              ? [...current, weekday.value]
                              : current.filter((value) => value !== weekday.value),
                          )
                        }}
                        type="checkbox"
                      />
                      {t(weekday.labelKey)}
                    </label>
                  ))}
                </div>
              )}
              {isAcademicRepeat && (
                <div className="calendar-create-academic-repeat">
                  <div className="calendar-create-academic-controls">
                    <label className="calendar-academic-year-field">
                      <span>Academic year</span>
                      <select
                        disabled={isCreating || isAcademicLoading}
                        onChange={(event) => setSelectedAcademicYearId(event.target.value)}
                        value={selectedAcademicYearId}
                      >
                        {academicYears.length === 0 ? (
                          <option value="">No academic years</option>
                        ) : (
                          academicYears.map((year) => (
                            <option key={year.id} value={year.id}>
                              {year.year_label}
                            </option>
                          ))
                        )}
                      </select>
                    </label>
                    <div className="calendar-academic-option-group">
                      <span>Semesters</span>
                      <div className="calendar-academic-semester-options" aria-label="Academic semesters">
                        {academicSemesters.length === 0 ? (
                          <p>No semesters</p>
                        ) : (
                          academicSemesters.map((semester) => (
                            <label key={semester.id}>
                              <input
                                checked={selectedAcademicSemesterIds.includes(semester.id)}
                                disabled={isCreating || isAcademicLoading}
                                onChange={(event) => {
                                  setSelectedAcademicSemesterIds((current) =>
                                    event.target.checked
                                      ? [...current, semester.id]
                                      : current.filter((id) => id !== semester.id),
                                  )
                                }}
                                type="checkbox"
                              />
                              <span>
                                {semester.label}
                                <small>
                                  {semester.starts_on.slice(5)}-{semester.ends_on.slice(5)}
                                </small>
                              </span>
                            </label>
                          ))
                        )}
                      </div>
                    </div>
                    <div className="calendar-academic-inline-fields">
                      <label>
                        <span>Academic weekday</span>
                        <select
                          disabled={isCreating}
                          onChange={(event) => setSelectedAcademicWeekday(Number(event.target.value))}
                          value={selectedAcademicWeekday}
                        >
                          {academicWeekdays.map((weekday) => (
                            <option key={weekday.value} value={weekday.value}>
                              {weekday.label}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        <span>Max events</span>
                        <input
                          disabled={isCreating}
                          min="1"
                          onChange={(event) => setAcademicMaxOccurrences(event.target.value)}
                          type="number"
                          value={academicMaxOccurrences}
                        />
                      </label>
                    </div>
                    <div className="calendar-academic-option-group">
                      <span>Periods</span>
                      <div className="calendar-academic-period-options" aria-label="Academic periods">
                        {academicPeriods.length === 0 ? (
                          <p>No periods are configured.</p>
                        ) : (
                          academicPeriods.map((period) => (
                            <label key={period.id}>
                              <input
                                checked={selectedAcademicPeriodIds.includes(period.id)}
                                disabled={isCreating}
                                onChange={(event) => {
                                  setSelectedAcademicPeriodIds((current) =>
                                    event.target.checked
                                      ? [...current, period.id]
                                      : current.filter((id) => id !== period.id),
                                  )
                                }}
                                type="checkbox"
                              />
                              <span>
                                {period.label || `${period.period_no}`}
                                <small>
                                  {displayPeriodTime(period.starts_at)}-
                                  {displayPeriodTime(period.ends_at)}
                                </small>
                              </span>
                            </label>
                          ))
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="calendar-academic-preview">
                    <strong>
                      {academicRepeatOccurrences.length} event
                      {academicRepeatOccurrences.length === 1 ? '' : 's'}
                    </strong>
                    {selectedAcademicSemesters.length > 0 && (
                      <span>
                        {selectedAcademicSemesters.map((semester) => semester.label).join(', ')}
                      </span>
                    )}
                    <ol>
                      {academicRepeatOccurrences.map((occurrence) => (
                        <li key={occurrence.date}>
                          <span>{occurrence.date}</span>
                          <span>
                            {occurrence.startTime}-{occurrence.endTime}
                          </span>
                          <span>{occurrence.label}</span>
                        </li>
                      ))}
                    </ol>
                  </div>
                </div>
              )}
              <div className="calendar-create-link-row">
                <label>
                  <span>{t('calendar.event.caseLabel')}</span>
                  <SuggestInput
                    ariaLabel={t('calendar.event.caseLabel')}
                    disabled={isCreating}
                    maxItems={1}
                    onChange={setCaseInput}
                    options={cases.map((item) => ({
                      key: item.id,
                      value: item.name,
                      label: item.name,
                      badgeLabel: item.name,
                    }))}
                    placeholder={t('calendar.event.casePlaceholder')}
                    value={caseInput}
                  />
                </label>
                <label>
                  <span>{t('calendar.event.taskLabel')}</span>
                  <SuggestInput
                    ariaLabel={t('calendar.event.taskLabel')}
                    disabled={isCreating}
                    maxItems={1}
                    onChange={setTaskInput}
                    options={tasks.map((item) => ({
                      key: item.id,
                      value: item.title,
                      label: item.case_name ?? item.title,
                      badgeLabel: item.title,
                    }))}
                    placeholder={t('calendar.event.taskPlaceholder')}
                    value={taskInput}
                  />
                </label>
              </div>
              <div className="calendar-create-actions">
                <button
                  className={`button-loading-dot${isCreating ? ' is-loading' : ''}`}
                  disabled={isLoading || isCreating || writableCalendars.length === 0}
                  type="submit"
                >
                  {t('calendar.create.submit')}
                </button>
                <AppLink className="calendar-create-cancel" href={cancelHref}>
                  {t('common.cancel')}
                </AppLink>
              </div>
            </section>
          </form>
        </div>
      </div>
    </main>
  )
}
