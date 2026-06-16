type ApiError = {
  code: string
  message: string
}

type SuccessResponse<T> = {
  ok: true
  data: T
}

type ErrorResponse = {
  ok: false
  error: ApiError
}

type ItemsResponse<T> = {
  items: T[]
}

export type AcademicYear = {
  id: string
  year_label: string
  starts_on: string
  ends_on: string
  note: string | null
  created_at: string
  updated_at: string
  version: number
}

export type AcademicCalendarDayType =
  | 'normal'
  | 'holiday'
  | 'no_class_day'
  | 'substitute_teaching_day'
  | 'makeup_day'
  | 'exam_period'
  | 'university_event'

export type AcademicCalendarDay = {
  id: string
  academic_year_id: string
  date: string
  day_type: AcademicCalendarDayType
  label: string
  is_teaching_day: boolean
  effective_weekday: number | null
  source: string
  note: string | null
  created_at: string
  updated_at: string
  version: number
}

export type AcademicSemester = {
  id: string
  academic_year_id: string
  label: string
  starts_on: string
  ends_on: string
  sort_order: number
  note: string | null
  created_at: string
  updated_at: string
  version: number
}

export type AcademicPeriod = {
  id: string
  period_no: number
  label: string
  starts_at: string
  ends_at: string
  sort_order: number
  note: string | null
  created_at: string
  updated_at: string
  version: number
}

export type AcademicCalendarDayPayload = {
  date: string
  day_type: AcademicCalendarDayType
  label: string
  is_teaching_day: boolean
  effective_weekday: number | null
  source?: string
  note?: string | null
}

export type AcademicYearPayload = {
  year_label: string
  starts_on: string
  ends_on: string
  note?: string | null
}

export type AcademicSemesterPayload = {
  label: string
  starts_on: string
  ends_on: string
  sort_order?: number
  note?: string | null
}

export type AcademicPeriodPayload = {
  period_no: number
  label: string
  starts_at: string
  ends_at: string
  sort_order?: number
  note?: string | null
}

export type NationalHolidayImportResult = {
  imported_count: number
  updated_count: number
  skipped_out_of_range: number
  skipped_existing: number
  items: AcademicCalendarDay[]
}

export class AcademicCalendarApiError extends Error {
  code: string
  status: number

  constructor(status: number, error: ApiError) {
    super(error.message)
    this.name = 'AcademicCalendarApiError'
    this.code = error.code
    this.status = status
  }
}

function hasApiError(payload: unknown): payload is ErrorResponse {
  return (
    typeof payload === 'object' &&
    payload !== null &&
    (payload as Partial<ErrorResponse>).ok === false &&
    typeof (payload as Partial<ErrorResponse>).error?.code === 'string' &&
    typeof (payload as Partial<ErrorResponse>).error?.message === 'string'
  )
}

function isSuccessResponse<T>(payload: unknown): payload is SuccessResponse<T> {
  return (
    typeof payload === 'object' &&
    payload !== null &&
    (payload as Partial<SuccessResponse<T>>).ok === true &&
    'data' in payload
  )
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: 'include',
    ...init,
  })
  const responseText = await response.text()
  let payload: unknown
  try {
    payload = responseText === '' ? null : JSON.parse(responseText)
  } catch {
    payload = null
  }

  if (!response.ok || !isSuccessResponse<T>(payload)) {
    const error = hasApiError(payload)
      ? payload.error
      : {
          code: 'ACADEMIC_CALENDAR_REQUEST_FAILED',
          message: responseText === '' ? 'Request failed.' : responseText,
        }
    throw new AcademicCalendarApiError(response.status, error)
  }

  return payload.data
}

export async function listAcademicYears(): Promise<AcademicYear[]> {
  const data = await request<ItemsResponse<AcademicYear>>('/api/v1/academic-calendar/years')
  return data.items
}

export function createAcademicYear(payload: AcademicYearPayload): Promise<AcademicYear> {
  return request('/api/v1/academic-calendar/years', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export async function listAcademicCalendarDays(
  academicYearId: string,
): Promise<AcademicCalendarDay[]> {
  const data = await request<{ academic_year: AcademicYear; items: AcademicCalendarDay[] }>(
    `/api/v1/academic-calendar/years/${encodeURIComponent(academicYearId)}/days`,
  )
  return data.items
}

export async function listAcademicSemesters(
  academicYearId: string,
): Promise<AcademicSemester[]> {
  const data = await request<{ academic_year: AcademicYear; items: AcademicSemester[] }>(
    `/api/v1/academic-calendar/years/${encodeURIComponent(academicYearId)}/semesters`,
  )
  return data.items
}

export async function listAcademicPeriods(): Promise<AcademicPeriod[]> {
  const data = await request<{ academic_year: AcademicYear | null; items: AcademicPeriod[] }>(
    '/api/v1/academic-calendar/periods',
  )
  return data.items
}

export function createAcademicSemester(
  academicYearId: string,
  payload: AcademicSemesterPayload,
): Promise<AcademicSemester> {
  return request(
    `/api/v1/academic-calendar/years/${encodeURIComponent(academicYearId)}/semesters`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export function createAcademicPeriod(
  payload: AcademicPeriodPayload,
): Promise<AcademicPeriod> {
  return request('/api/v1/academic-calendar/periods', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function updateAcademicPeriod(
  periodId: string,
  payload: AcademicPeriodPayload,
): Promise<AcademicPeriod> {
  return request(`/api/v1/academic-calendar/periods/${encodeURIComponent(periodId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function deleteAcademicPeriod(
  periodId: string,
): Promise<{ deleted: boolean }> {
  return request(`/api/v1/academic-calendar/periods/${encodeURIComponent(periodId)}`, {
    method: 'DELETE',
  })
}

export function updateAcademicSemester(
  semesterId: string,
  payload: AcademicSemesterPayload,
): Promise<AcademicSemester> {
  return request(`/api/v1/academic-calendar/semesters/${encodeURIComponent(semesterId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function deleteAcademicSemester(
  semesterId: string,
): Promise<{ deleted: boolean }> {
  return request(`/api/v1/academic-calendar/semesters/${encodeURIComponent(semesterId)}`, {
    method: 'DELETE',
  })
}

export function importNationalHolidayCsv(
  academicYearId: string,
  file: File,
  overwrite = false,
): Promise<NationalHolidayImportResult> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('overwrite', overwrite ? 'true' : 'false')
  return request(
    `/api/v1/academic-calendar/years/${encodeURIComponent(academicYearId)}/national-holidays/import`,
    {
      method: 'POST',
      body: formData,
    },
  )
}

export function upsertAcademicCalendarDay(
  academicYearId: string,
  date: string,
  payload: AcademicCalendarDayPayload,
): Promise<AcademicCalendarDay> {
  return request(
    `/api/v1/academic-calendar/years/${encodeURIComponent(academicYearId)}/days/${date}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source: 'manual', ...payload }),
    },
  )
}

export function deleteAcademicCalendarDay(
  academicYearId: string,
  date: string,
): Promise<{ deleted: boolean }> {
  return request(
    `/api/v1/academic-calendar/years/${encodeURIComponent(academicYearId)}/days/${date}`,
    { method: 'DELETE' },
  )
}
