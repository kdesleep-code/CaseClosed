from __future__ import annotations


def test_academic_calendar_year_and_day_api(client) -> None:
    create_year = client.post(
        "/api/v1/academic-calendar/years",
        json={
            "year_label": "2026",
            "starts_on": "2026-04-01",
            "ends_on": "2027-03-31",
            "note": "Test academic year",
        },
    )

    assert create_year.status_code == 200
    year = create_year.json()["data"]
    assert year["year_label"] == "2026"

    upsert_day = client.put(
        f"/api/v1/academic-calendar/years/{year['id']}/days/2026-07-21",
        json={
            "date": "2026-07-21",
            "day_type": "substitute_teaching_day",
            "label": "Monday classes",
            "is_teaching_day": True,
            "effective_weekday": 1,
            "note": "Tuesday runs Monday timetable.",
        },
    )

    assert upsert_day.status_code == 200
    day = upsert_day.json()["data"]
    assert day["date"] == "2026-07-21"
    assert day["day_type"] == "substitute_teaching_day"
    assert day["is_teaching_day"] is True
    assert day["effective_weekday"] == 1

    list_days = client.get(
        f"/api/v1/academic-calendar/years/{year['id']}/days"
        "?start_date=2026-07-01&end_date=2026-07-31"
    )

    assert list_days.status_code == 200
    assert [item["date"] for item in list_days.json()["data"]["items"]] == [
        "2026-07-21"
    ]

    delete_day = client.delete(
        f"/api/v1/academic-calendar/years/{year['id']}/days/2026-07-21"
    )

    assert delete_day.status_code == 200
    assert delete_day.json()["data"]["deleted"] is True


def test_academic_calendar_semester_api(client) -> None:
    create_year = client.post(
        "/api/v1/academic-calendar/years",
        json={
            "year_label": "2026",
            "starts_on": "2026-04-01",
            "ends_on": "2027-03-31",
        },
    )
    year = create_year.json()["data"]

    create_semester = client.post(
        f"/api/v1/academic-calendar/years/{year['id']}/semesters",
        json={
            "label": "Spring A",
            "starts_on": "2026-04-07",
            "ends_on": "2026-05-15",
            "sort_order": 10,
            "note": "First module",
        },
    )

    assert create_semester.status_code == 200
    semester = create_semester.json()["data"]
    assert semester["label"] == "Spring A"
    assert semester["starts_on"] == "2026-04-07"
    assert semester["ends_on"] == "2026-05-15"

    update_semester = client.patch(
        f"/api/v1/academic-calendar/semesters/{semester['id']}",
        json={
            "label": "Spring A1",
            "ends_on": "2026-05-14",
        },
    )

    assert update_semester.status_code == 200
    updated = update_semester.json()["data"]
    assert updated["label"] == "Spring A1"
    assert updated["ends_on"] == "2026-05-14"

    list_semesters = client.get(
        f"/api/v1/academic-calendar/years/{year['id']}/semesters"
    )

    assert list_semesters.status_code == 200
    assert [item["label"] for item in list_semesters.json()["data"]["items"]] == [
        "Spring A1"
    ]

    delete_semester = client.delete(
        f"/api/v1/academic-calendar/semesters/{semester['id']}"
    )

    assert delete_semester.status_code == 200
    assert delete_semester.json()["data"]["deleted"] is True


def test_academic_calendar_period_api(client) -> None:
    create_year = client.post(
        "/api/v1/academic-calendar/years",
        json={
            "year_label": "2026",
            "starts_on": "2026-04-01",
            "ends_on": "2027-03-31",
        },
    )
    year = create_year.json()["data"]

    create_period = client.post(
        "/api/v1/academic-calendar/periods",
        json={
            "period_no": 1,
            "label": "1st",
            "starts_at": "08:40",
            "ends_at": "09:55",
            "sort_order": 10,
            "note": "Morning period",
        },
    )

    assert create_period.status_code == 200
    period = create_period.json()["data"]
    assert period["period_no"] == 1
    assert period["label"] == "1st"
    assert period["starts_at"] == "08:40"
    assert period["ends_at"] == "09:55"

    update_period = client.patch(
        f"/api/v1/academic-calendar/periods/{period['id']}",
        json={
            "label": "Period 1",
            "ends_at": "10:00",
        },
    )

    assert update_period.status_code == 200
    updated = update_period.json()["data"]
    assert updated["label"] == "Period 1"
    assert updated["ends_at"] == "10:00"

    list_periods = client.get("/api/v1/academic-calendar/periods")

    assert list_periods.status_code == 200
    assert [item["label"] for item in list_periods.json()["data"]["items"]] == [
        "Period 1"
    ]

    delete_period = client.delete(
        f"/api/v1/academic-calendar/periods/{period['id']}"
    )

    assert delete_period.status_code == 200
    assert delete_period.json()["data"]["deleted"] is True


def test_academic_calendar_periods_are_global_across_years(client) -> None:
    first_year_response = client.post(
        "/api/v1/academic-calendar/years",
        json={
            "year_label": "2026",
            "starts_on": "2026-04-01",
            "ends_on": "2027-03-31",
        },
    )
    second_year_response = client.post(
        "/api/v1/academic-calendar/years",
        json={
            "year_label": "2027",
            "starts_on": "2027-04-01",
            "ends_on": "2028-03-31",
        },
    )
    assert first_year_response.status_code == 200
    assert second_year_response.status_code == 200

    create_period = client.post(
        "/api/v1/academic-calendar/periods",
        json={
            "period_no": 1,
            "label": "1st",
            "starts_at": "08:40",
            "ends_at": "09:55",
        },
    )

    assert create_period.status_code == 200

    second_year_periods = client.get("/api/v1/academic-calendar/periods")

    assert second_year_periods.status_code == 200
    assert [item["label"] for item in second_year_periods.json()["data"]["items"]] == ["1st"]


def test_academic_calendar_rejects_invalid_period_time_range(client) -> None:
    year_response = client.post(
        "/api/v1/academic-calendar/years",
        json={
            "year_label": "2026",
            "starts_on": "2026-04-01",
            "ends_on": "2027-03-31",
        },
    )
    year = year_response.json()["data"]

    response = client.post(
        "/api/v1/academic-calendar/periods",
        json={
            "period_no": 1,
            "label": "Broken",
            "starts_at": "10:00",
            "ends_at": "09:00",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_PERIOD_TIME_RANGE"


def test_academic_calendar_rejects_semester_outside_year(client) -> None:
    year_response = client.post(
        "/api/v1/academic-calendar/years",
        json={
            "year_label": "2026",
            "starts_on": "2026-04-01",
            "ends_on": "2027-03-31",
        },
    )
    year = year_response.json()["data"]

    response = client.post(
        f"/api/v1/academic-calendar/years/{year['id']}/semesters",
        json={
            "label": "Outside",
            "starts_on": "2026-03-31",
            "ends_on": "2026-04-10",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SEMESTER_OUTSIDE_ACADEMIC_YEAR"


def test_academic_calendar_imports_national_holiday_csv(client) -> None:
    year_response = client.post(
        "/api/v1/academic-calendar/years",
        json={
            "year_label": "2026",
            "starts_on": "2026-04-01",
            "ends_on": "2027-03-31",
        },
    )
    year = year_response.json()["data"]
    client.put(
        f"/api/v1/academic-calendar/years/{year['id']}/days/2026-05-04",
        json={
            "date": "2026-05-04",
            "day_type": "university_event",
            "label": "Manual event",
            "is_teaching_day": True,
        },
    )

    csv_text = (
        "国民の祝日・休日月日,国民の祝日・休日名称\n"
        "2026/03/20,春分の日\n"
        "2026/04/29,昭和の日\n"
        "2026/05/04,みどりの日\n"
        "2027/01/01,元日\n"
    )
    response = client.post(
        f"/api/v1/academic-calendar/years/{year['id']}/national-holidays/import",
        files={
            "file": (
                "syukujitsu.csv",
                csv_text.encode("cp932"),
                "text/csv",
            )
        },
    )

    assert response.status_code == 200
    result = response.json()["data"]
    assert result["imported_count"] == 2
    assert result["updated_count"] == 0
    assert result["skipped_out_of_range"] == 1
    assert result["skipped_existing"] == 1

    list_days = client.get(f"/api/v1/academic-calendar/years/{year['id']}/days")

    items = {item["date"]: item for item in list_days.json()["data"]["items"]}
    assert items["2026-04-29"]["label"] == "昭和の日"
    assert items["2026-04-29"]["day_type"] == "holiday"
    assert items["2026-04-29"]["is_teaching_day"] is False
    assert items["2026-04-29"]["source"] == "national_holiday"
    assert items["2026-05-04"]["label"] == "Manual event"


def test_academic_calendar_rejects_day_outside_year(client) -> None:
    year_response = client.post(
        "/api/v1/academic-calendar/years",
        json={
            "year_label": "2026",
            "starts_on": "2026-04-01",
            "ends_on": "2027-03-31",
        },
    )
    year = year_response.json()["data"]

    response = client.put(
        f"/api/v1/academic-calendar/years/{year['id']}/days/2026-03-31",
        json={
            "date": "2026-03-31",
            "day_type": "holiday",
            "label": "Outside",
            "is_teaching_day": False,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "DATE_OUTSIDE_ACADEMIC_YEAR"
