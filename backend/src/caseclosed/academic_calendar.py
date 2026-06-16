from __future__ import annotations

import csv
from datetime import datetime
from io import StringIO
from uuid import uuid4

from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import Form
from fastapi import UploadFile
from pydantic import BaseModel
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from caseclosed.auth import json_error
from caseclosed.db.models import AcademicCalendarDay
from caseclosed.db.models import AcademicPeriod
from caseclosed.db.models import AcademicSemester
from caseclosed.db.models import AcademicYear
from caseclosed.db.runtime import get_session
from caseclosed.db.runtime import jst_iso

router = APIRouter(prefix="/api/v1/academic-calendar", tags=["academic-calendar"])

ACADEMIC_DAY_TYPES = {
    "normal",
    "holiday",
    "no_class_day",
    "substitute_teaching_day",
    "makeup_day",
    "exam_period",
    "university_event",
}


class AcademicYearCreate(BaseModel):
    year_label: str = Field(min_length=1)
    starts_on: str = Field(min_length=10, max_length=10)
    ends_on: str = Field(min_length=10, max_length=10)
    note: str | None = None


class AcademicYearPatch(BaseModel):
    year_label: str | None = Field(default=None, min_length=1)
    starts_on: str | None = Field(default=None, min_length=10, max_length=10)
    ends_on: str | None = Field(default=None, min_length=10, max_length=10)
    note: str | None = None


class AcademicSemesterCreate(BaseModel):
    label: str = Field(min_length=1)
    starts_on: str = Field(min_length=10, max_length=10)
    ends_on: str = Field(min_length=10, max_length=10)
    sort_order: int = 0
    note: str | None = None


class AcademicSemesterPatch(BaseModel):
    label: str | None = Field(default=None, min_length=1)
    starts_on: str | None = Field(default=None, min_length=10, max_length=10)
    ends_on: str | None = Field(default=None, min_length=10, max_length=10)
    sort_order: int | None = None
    note: str | None = None


class AcademicPeriodCreate(BaseModel):
    period_no: int = Field(ge=1)
    label: str = Field(min_length=1)
    starts_at: str = Field(min_length=5, max_length=5)
    ends_at: str = Field(min_length=5, max_length=5)
    sort_order: int = 0
    note: str | None = None


class AcademicPeriodPatch(BaseModel):
    period_no: int | None = Field(default=None, ge=1)
    label: str | None = Field(default=None, min_length=1)
    starts_at: str | None = Field(default=None, min_length=5, max_length=5)
    ends_at: str | None = Field(default=None, min_length=5, max_length=5)
    sort_order: int | None = None
    note: str | None = None


class AcademicCalendarDayUpsert(BaseModel):
    date: str = Field(min_length=10, max_length=10)
    day_type: str = "normal"
    label: str = Field(min_length=1)
    is_teaching_day: bool = True
    effective_weekday: int | None = Field(default=None, ge=0, le=6)
    source: str = "manual"
    note: str | None = None


class NationalHolidayCsvRow(BaseModel):
    date: str
    label: str


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def normalized_date(value: str) -> str:
    stripped = value.strip()
    try:
        datetime.strptime(stripped, "%Y-%m-%d")
    except ValueError as error:
        raise json_error(422, "INVALID_DATE", "Date must be YYYY-MM-DD.") from error
    return stripped


def normalized_csv_date(value: str) -> str:
    stripped = value.strip()
    for format_text in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(stripped, format_text).strftime("%Y-%m-%d")
        except ValueError:
            pass
    raise json_error(422, "INVALID_HOLIDAY_CSV_DATE", "Holiday CSV date is invalid.")


def normalized_time(value: str) -> str:
    stripped = value.strip()
    try:
        datetime.strptime(stripped, "%H:%M")
    except ValueError as error:
        raise json_error(422, "INVALID_TIME", "Time must be HH:MM.") from error
    return stripped


def normalized_time_range(starts_at: str, ends_at: str) -> tuple[str, str]:
    start = normalized_time(starts_at)
    end = normalized_time(ends_at)
    if end <= start:
        raise json_error(422, "INVALID_PERIOD_TIME_RANGE", "Period end must be after start.")
    return start, end


def normalized_year_range(starts_on: str, ends_on: str) -> tuple[str, str]:
    start = normalized_date(starts_on)
    end = normalized_date(ends_on)
    if end < start:
        raise json_error(422, "INVALID_ACADEMIC_YEAR_RANGE", "Academic year end must be after start.")
    return start, end


def normalized_child_range(
    starts_on: str,
    ends_on: str,
    year: AcademicYear,
    error_code: str,
) -> tuple[str, str]:
    start, end = normalized_year_range(starts_on, ends_on)
    if start < year.starts_on or end > year.ends_on:
        raise json_error(422, error_code, "Date range is outside the academic year.")
    return start, end


def normalized_day_type(value: str) -> str:
    day_type = value.strip()
    if day_type not in ACADEMIC_DAY_TYPES:
        raise json_error(422, "INVALID_ACADEMIC_DAY_TYPE", "Invalid academic calendar day type.")
    return day_type


def academic_year_data(year: AcademicYear) -> dict[str, object]:
    return {
        "id": year.id,
        "year_label": year.year_label,
        "starts_on": year.starts_on,
        "ends_on": year.ends_on,
        "note": year.note,
        "created_at": year.created_at,
        "updated_at": year.updated_at,
        "version": year.version,
    }


def academic_semester_data(semester: AcademicSemester) -> dict[str, object]:
    return {
        "id": semester.id,
        "academic_year_id": semester.academic_year_id,
        "label": semester.label,
        "starts_on": semester.starts_on,
        "ends_on": semester.ends_on,
        "sort_order": semester.sort_order,
        "note": semester.note,
        "created_at": semester.created_at,
        "updated_at": semester.updated_at,
        "version": semester.version,
    }


def academic_period_data(period: AcademicPeriod) -> dict[str, object]:
    return {
        "id": period.id,
        "period_no": period.period_no,
        "label": period.label,
        "starts_at": period.starts_at,
        "ends_at": period.ends_at,
        "sort_order": period.sort_order,
        "note": period.note,
        "created_at": period.created_at,
        "updated_at": period.updated_at,
        "version": period.version,
    }


def academic_day_data(day: AcademicCalendarDay) -> dict[str, object]:
    return {
        "id": day.id,
        "academic_year_id": day.academic_year_id,
        "date": day.date,
        "day_type": day.day_type,
        "label": day.label,
        "is_teaching_day": bool(day.is_teaching_day),
        "effective_weekday": day.effective_weekday,
        "source": day.source,
        "note": day.note,
        "created_at": day.created_at,
        "updated_at": day.updated_at,
        "version": day.version,
    }


def decode_holiday_csv(content: bytes) -> str:
    for encoding in ("utf-8-sig", "cp932", "shift_jis"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            pass
    raise json_error(422, "INVALID_HOLIDAY_CSV_ENCODING", "Holiday CSV must be UTF-8 or Shift_JIS.")


def parse_national_holiday_csv(content: bytes) -> list[NationalHolidayCsvRow]:
    text = decode_holiday_csv(content)
    reader = csv.DictReader(StringIO(text))
    if reader.fieldnames is None:
        raise json_error(422, "INVALID_HOLIDAY_CSV", "Holiday CSV is empty.")
    normalized_fields = {field.strip(): field for field in reader.fieldnames if field is not None}
    date_field = (
        normalized_fields.get("国民の祝日・休日月日")
        or normalized_fields.get("月日")
        or normalized_fields.get("date")
        or normalized_fields.get("Date")
    )
    label_field = (
        normalized_fields.get("国民の祝日・休日名称")
        or normalized_fields.get("名称")
        or normalized_fields.get("name")
        or normalized_fields.get("Name")
    )
    if date_field is None or label_field is None:
        raise json_error(422, "INVALID_HOLIDAY_CSV_HEADER", "Holiday CSV headers are invalid.")
    rows: list[NationalHolidayCsvRow] = []
    for row in reader:
        raw_date = (row.get(date_field) or "").strip()
        label = (row.get(label_field) or "").strip()
        if raw_date == "" and label == "":
            continue
        if raw_date == "" or label == "":
            raise json_error(422, "INVALID_HOLIDAY_CSV_ROW", "Holiday CSV has an invalid row.")
        rows.append(NationalHolidayCsvRow(date=normalized_csv_date(raw_date), label=label))
    return rows


@router.get("/years")
def list_academic_years(
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    years = session.scalars(
        select(AcademicYear).order_by(AcademicYear.starts_on.desc(), AcademicYear.year_label.desc())
    ).all()
    return {"ok": True, "data": {"items": [academic_year_data(year) for year in years]}}


@router.post("/years")
def create_academic_year(
    payload: AcademicYearCreate,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    year_label = payload.year_label.strip()
    starts_on, ends_on = normalized_year_range(payload.starts_on, payload.ends_on)
    existing = session.scalar(select(AcademicYear).where(AcademicYear.year_label == year_label))
    if existing is not None:
        raise json_error(409, "ACADEMIC_YEAR_EXISTS", "Academic year already exists.")
    now = jst_iso()
    year = AcademicYear(
        id=new_id("academic_year"),
        year_label=year_label,
        starts_on=starts_on,
        ends_on=ends_on,
        note=optional_text(payload.note),
        created_at=now,
        updated_at=now,
        version=1,
    )
    session.add(year)
    session.commit()
    return {"ok": True, "data": academic_year_data(year)}


@router.patch("/years/{academic_year_id}")
def update_academic_year(
    academic_year_id: str,
    payload: AcademicYearPatch,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    year = session.get(AcademicYear, academic_year_id)
    if year is None:
        raise json_error(404, "ACADEMIC_YEAR_NOT_FOUND", "Academic year was not found.")
    if payload.year_label is not None:
        year_label = payload.year_label.strip()
        existing = session.scalar(
            select(AcademicYear).where(
                AcademicYear.year_label == year_label,
                AcademicYear.id != year.id,
            )
        )
        if existing is not None:
            raise json_error(409, "ACADEMIC_YEAR_EXISTS", "Academic year already exists.")
        year.year_label = year_label
    starts_on = payload.starts_on if payload.starts_on is not None else year.starts_on
    ends_on = payload.ends_on if payload.ends_on is not None else year.ends_on
    year.starts_on, year.ends_on = normalized_year_range(starts_on, ends_on)
    if payload.note is not None:
        year.note = optional_text(payload.note)
    year.updated_at = jst_iso()
    year.version += 1
    session.commit()
    return {"ok": True, "data": academic_year_data(year)}


@router.get("/years/{academic_year_id}/semesters")
def list_academic_semesters(
    academic_year_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    year = session.get(AcademicYear, academic_year_id)
    if year is None:
        raise json_error(404, "ACADEMIC_YEAR_NOT_FOUND", "Academic year was not found.")
    semesters = session.scalars(
        select(AcademicSemester)
        .where(AcademicSemester.academic_year_id == academic_year_id)
        .order_by(
            AcademicSemester.sort_order.asc(),
            AcademicSemester.starts_on.asc(),
            AcademicSemester.label.asc(),
        )
    ).all()
    return {
        "ok": True,
        "data": {
            "academic_year": academic_year_data(year),
            "items": [academic_semester_data(semester) for semester in semesters],
        },
    }


@router.post("/years/{academic_year_id}/semesters")
def create_academic_semester(
    academic_year_id: str,
    payload: AcademicSemesterCreate,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    year = session.get(AcademicYear, academic_year_id)
    if year is None:
        raise json_error(404, "ACADEMIC_YEAR_NOT_FOUND", "Academic year was not found.")
    label = payload.label.strip()
    starts_on, ends_on = normalized_child_range(
        payload.starts_on,
        payload.ends_on,
        year,
        "SEMESTER_OUTSIDE_ACADEMIC_YEAR",
    )
    existing = session.scalar(
        select(AcademicSemester).where(
            AcademicSemester.academic_year_id == academic_year_id,
            AcademicSemester.label == label,
        )
    )
    if existing is not None:
        raise json_error(409, "ACADEMIC_SEMESTER_EXISTS", "Academic semester already exists.")
    now = jst_iso()
    semester = AcademicSemester(
        id=new_id("academic_semester"),
        academic_year_id=academic_year_id,
        label=label,
        starts_on=starts_on,
        ends_on=ends_on,
        sort_order=payload.sort_order,
        note=optional_text(payload.note),
        created_at=now,
        updated_at=now,
        version=1,
    )
    session.add(semester)
    session.commit()
    return {"ok": True, "data": academic_semester_data(semester)}


@router.patch("/semesters/{semester_id}")
def update_academic_semester(
    semester_id: str,
    payload: AcademicSemesterPatch,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    semester = session.get(AcademicSemester, semester_id)
    if semester is None:
        raise json_error(404, "ACADEMIC_SEMESTER_NOT_FOUND", "Academic semester was not found.")
    year = session.get(AcademicYear, semester.academic_year_id)
    if year is None:
        raise json_error(404, "ACADEMIC_YEAR_NOT_FOUND", "Academic year was not found.")
    if payload.label is not None:
        label = payload.label.strip()
        existing = session.scalar(
            select(AcademicSemester).where(
                AcademicSemester.academic_year_id == semester.academic_year_id,
                AcademicSemester.label == label,
                AcademicSemester.id != semester.id,
            )
        )
        if existing is not None:
            raise json_error(409, "ACADEMIC_SEMESTER_EXISTS", "Academic semester already exists.")
        semester.label = label
    starts_on = payload.starts_on if payload.starts_on is not None else semester.starts_on
    ends_on = payload.ends_on if payload.ends_on is not None else semester.ends_on
    semester.starts_on, semester.ends_on = normalized_child_range(
        starts_on,
        ends_on,
        year,
        "SEMESTER_OUTSIDE_ACADEMIC_YEAR",
    )
    if payload.sort_order is not None:
        semester.sort_order = payload.sort_order
    if payload.note is not None:
        semester.note = optional_text(payload.note)
    semester.updated_at = jst_iso()
    semester.version += 1
    session.commit()
    return {"ok": True, "data": academic_semester_data(semester)}


@router.delete("/semesters/{semester_id}")
def delete_academic_semester(
    semester_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    semester = session.get(AcademicSemester, semester_id)
    if semester is None:
        raise json_error(404, "ACADEMIC_SEMESTER_NOT_FOUND", "Academic semester was not found.")
    session.delete(semester)
    session.commit()
    return {"ok": True, "data": {"deleted": True}}


@router.get("/periods")
def list_academic_periods(
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    periods = session.scalars(
        select(AcademicPeriod)
        .order_by(
            AcademicPeriod.sort_order.asc(),
            AcademicPeriod.period_no.asc(),
            AcademicPeriod.starts_at.asc(),
        )
    ).all()
    return {
        "ok": True,
        "data": {
            "academic_year": None,
            "items": [academic_period_data(period) for period in periods],
        },
    }


@router.post("/periods")
def create_academic_period(
    payload: AcademicPeriodCreate,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    starts_at, ends_at = normalized_time_range(payload.starts_at, payload.ends_at)
    label = payload.label.strip()
    existing = session.scalar(
        select(AcademicPeriod).where(
            AcademicPeriod.period_no == payload.period_no,
        )
    )
    if existing is not None:
        raise json_error(409, "ACADEMIC_PERIOD_EXISTS", "Academic period already exists.")
    now = jst_iso()
    period = AcademicPeriod(
        id=new_id("academic_period"),
        period_no=payload.period_no,
        label=label,
        starts_at=starts_at,
        ends_at=ends_at,
        sort_order=payload.sort_order,
        note=optional_text(payload.note),
        created_at=now,
        updated_at=now,
        version=1,
    )
    session.add(period)
    session.commit()
    return {"ok": True, "data": academic_period_data(period)}


@router.patch("/periods/{period_id}")
def update_academic_period(
    period_id: str,
    payload: AcademicPeriodPatch,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    period = session.get(AcademicPeriod, period_id)
    if period is None:
        raise json_error(404, "ACADEMIC_PERIOD_NOT_FOUND", "Academic period was not found.")
    if payload.period_no is not None:
        existing = session.scalar(
            select(AcademicPeriod).where(
                AcademicPeriod.period_no == payload.period_no,
                AcademicPeriod.id != period.id,
            )
        )
        if existing is not None:
            raise json_error(409, "ACADEMIC_PERIOD_EXISTS", "Academic period already exists.")
        period.period_no = payload.period_no
    starts_at = payload.starts_at if payload.starts_at is not None else period.starts_at
    ends_at = payload.ends_at if payload.ends_at is not None else period.ends_at
    period.starts_at, period.ends_at = normalized_time_range(starts_at, ends_at)
    if payload.label is not None:
        period.label = payload.label.strip()
    if payload.sort_order is not None:
        period.sort_order = payload.sort_order
    if payload.note is not None:
        period.note = optional_text(payload.note)
    period.updated_at = jst_iso()
    period.version += 1
    session.commit()
    return {"ok": True, "data": academic_period_data(period)}


@router.delete("/periods/{period_id}")
def delete_academic_period(
    period_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    period = session.get(AcademicPeriod, period_id)
    if period is None:
        raise json_error(404, "ACADEMIC_PERIOD_NOT_FOUND", "Academic period was not found.")
    session.delete(period)
    session.commit()
    return {"ok": True, "data": {"deleted": True}}


@router.post("/years/{academic_year_id}/national-holidays/import")
async def import_national_holidays(
    academic_year_id: str,
    file: UploadFile = File(...),
    overwrite: bool = Form(False),
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    year = session.get(AcademicYear, academic_year_id)
    if year is None:
        raise json_error(404, "ACADEMIC_YEAR_NOT_FOUND", "Academic year was not found.")
    rows = parse_national_holiday_csv(await file.read())
    now = jst_iso()
    imported_count = 0
    updated_count = 0
    skipped_out_of_range = 0
    skipped_existing = 0
    items: list[dict[str, object]] = []
    for row in rows:
        if row.date < year.starts_on or row.date > year.ends_on:
            skipped_out_of_range += 1
            continue
        existing = session.scalar(
            select(AcademicCalendarDay).where(
                AcademicCalendarDay.academic_year_id == academic_year_id,
                AcademicCalendarDay.date == row.date,
            )
        )
        if existing is not None and existing.source != "national_holiday" and not overwrite:
            skipped_existing += 1
            continue
        if existing is None:
            day = AcademicCalendarDay(
                id=new_id("academic_calendar_day"),
                academic_year_id=academic_year_id,
                date=row.date,
                day_type="holiday",
                label=row.label,
                is_teaching_day=0,
                effective_weekday=None,
                source="national_holiday",
                note=None,
                created_at=now,
                updated_at=now,
                version=1,
            )
            session.add(day)
            imported_count += 1
        else:
            day = existing
            day.day_type = "holiday"
            day.label = row.label
            day.is_teaching_day = 0
            day.effective_weekday = None
            day.source = "national_holiday"
            day.updated_at = now
            day.version += 1
            updated_count += 1
        items.append(academic_day_data(day))
    session.commit()
    return {
        "ok": True,
        "data": {
            "imported_count": imported_count,
            "updated_count": updated_count,
            "skipped_out_of_range": skipped_out_of_range,
            "skipped_existing": skipped_existing,
            "items": items,
        },
    }


@router.get("/years/{academic_year_id}/days")
def list_academic_calendar_days(
    academic_year_id: str,
    start_date: str | None = None,
    end_date: str | None = None,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    year = session.get(AcademicYear, academic_year_id)
    if year is None:
        raise json_error(404, "ACADEMIC_YEAR_NOT_FOUND", "Academic year was not found.")
    statement = select(AcademicCalendarDay).where(
        AcademicCalendarDay.academic_year_id == academic_year_id
    )
    if start_date is not None and start_date.strip() != "":
        statement = statement.where(AcademicCalendarDay.date >= normalized_date(start_date))
    if end_date is not None and end_date.strip() != "":
        statement = statement.where(AcademicCalendarDay.date <= normalized_date(end_date))
    days = session.scalars(
        statement.order_by(AcademicCalendarDay.date.asc(), AcademicCalendarDay.id.asc())
    ).all()
    return {
        "ok": True,
        "data": {
            "academic_year": academic_year_data(year),
            "items": [academic_day_data(day) for day in days],
        },
    }


@router.put("/years/{academic_year_id}/days/{target_date}")
def upsert_academic_calendar_day(
    academic_year_id: str,
    target_date: str,
    payload: AcademicCalendarDayUpsert,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    year = session.get(AcademicYear, academic_year_id)
    if year is None:
        raise json_error(404, "ACADEMIC_YEAR_NOT_FOUND", "Academic year was not found.")
    date_text = normalized_date(target_date)
    payload_date = normalized_date(payload.date)
    if payload_date != date_text:
        raise json_error(422, "DATE_MISMATCH", "Payload date must match the URL date.")
    if date_text < year.starts_on or date_text > year.ends_on:
        raise json_error(422, "DATE_OUTSIDE_ACADEMIC_YEAR", "Date is outside the academic year.")
    day_type = normalized_day_type(payload.day_type)
    label = payload.label.strip()
    source = payload.source.strip() or "manual"
    now = jst_iso()
    day = session.scalar(
        select(AcademicCalendarDay).where(
            AcademicCalendarDay.academic_year_id == academic_year_id,
            AcademicCalendarDay.date == date_text,
        )
    )
    if day is None:
        day = AcademicCalendarDay(
            id=new_id("academic_calendar_day"),
            academic_year_id=academic_year_id,
            date=date_text,
            day_type=day_type,
            label=label,
            is_teaching_day=1 if payload.is_teaching_day else 0,
            effective_weekday=payload.effective_weekday,
            source=source,
            note=optional_text(payload.note),
            created_at=now,
            updated_at=now,
            version=1,
        )
        session.add(day)
    else:
        day.day_type = day_type
        day.label = label
        day.is_teaching_day = 1 if payload.is_teaching_day else 0
        day.effective_weekday = payload.effective_weekday
        day.source = source
        day.note = optional_text(payload.note)
        day.updated_at = now
        day.version += 1
    session.commit()
    return {"ok": True, "data": academic_day_data(day)}


@router.delete("/years/{academic_year_id}/days/{target_date}")
def delete_academic_calendar_day(
    academic_year_id: str,
    target_date: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    date_text = normalized_date(target_date)
    day = session.scalar(
        select(AcademicCalendarDay).where(
            AcademicCalendarDay.academic_year_id == academic_year_id,
            AcademicCalendarDay.date == date_text,
        )
    )
    if day is None:
        raise json_error(404, "ACADEMIC_CALENDAR_DAY_NOT_FOUND", "Academic calendar day was not found.")
    session.delete(day)
    session.commit()
    return {"ok": True, "data": {"deleted": True}}
