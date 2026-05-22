from __future__ import annotations


def test_case_delete_api_is_not_registered(app) -> None:
    case_delete_routes = [
        route
        for route in app.routes
        if "DELETE" in getattr(route, "methods", set())
        and getattr(route, "path", "") == "/api/v1/cases/{case_id}"
    ]

    assert case_delete_routes == []

