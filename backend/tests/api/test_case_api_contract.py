from __future__ import annotations


def test_case_delete_api_is_registered_as_exception_operation(app) -> None:
    case_delete_routes = [
        route
        for route in app.routes
        if "DELETE" in getattr(route, "methods", set())
        and getattr(route, "path", "") == "/api/v1/cases/{case_id}"
    ]

    assert len(case_delete_routes) == 1
    assert case_delete_routes[0].name == "delete_case"
