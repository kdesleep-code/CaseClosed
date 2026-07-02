from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request
from urllib.request import urlopen


API_BASE_URL = os.environ.get("CASECLOSED_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
TOKEN = os.environ.get("CASECLOSED_EXTENSION_TOKEN", "")
PORT = int(os.environ.get("CASECLOSED_EXTENSION_PORT", "8765"))
EXCLUDED_CASE_TAG_SOURCE_TAGS = {"students", "ut", "supervised-student"}


def caseclosed_request(path: str, *, method: str = "GET", payload: dict[str, object] | None = None) -> object:
    data = None
    headers = {"X-CaseClosed-Extension-Token": TOKEN}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(f"{API_BASE_URL}{path}", data=data, headers=headers, method=method)
    with urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8")
    decoded = json.loads(body)
    if not decoded.get("ok"):
        raise RuntimeError(decoded)
    return decoded["data"]


def normalize_name(value: object) -> str:
    return "".join(str(value or "").casefold().split())


def case_tags_for_contact(contact: dict[str, object]) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for value in contact.get("tags") if isinstance(contact.get("tags"), list) else []:
        tag = str(value or "").strip()
        key = tag.casefold()
        if tag and key not in EXCLUDED_CASE_TAG_SOURCE_TAGS and key not in seen:
            tags.append(tag)
            seen.add(key)
    return tags


def comparable_contact_tags(contact: dict[str, object]) -> list[str]:
    return case_tags_for_contact(contact)


def comparable_tags_from_values(values: object) -> list[str]:
    return comparable_contact_tags({"tags": values if isinstance(values, list) else []})


def primary_email(contact: dict[str, object]) -> str:
    emails = contact.get("email_addresses")
    if not isinstance(emails, list) or len(emails) == 0:
        return ""
    primary = next((item for item in emails if isinstance(item, dict) and item.get("is_primary") is True), emails[0])
    if not isinstance(primary, dict):
        return ""
    return str(primary.get("email_address") or "")


def launch_genre() -> tuple[str, str]:
    context_data = caseclosed_request("/api/v1/extension-api/context")
    instance = context_data.get("instance") if isinstance(context_data, dict) else None
    launch_context = instance.get("launch_context") if isinstance(instance, dict) else None
    context = launch_context.get("context") if isinstance(launch_context, dict) else None
    genre_id = str(context.get("genre_id") or "") if isinstance(context, dict) else ""
    genre_title = str(context.get("genre_title") or "Supervise") if isinstance(context, dict) else "Supervise"
    if genre_id:
        return genre_id, genre_title
    genres = caseclosed_request("/api/v1/extension-api/cases/genres")["items"]
    supervise = next((genre for genre in genres if str(genre.get("title") or "").casefold() == "supervise"), None)
    if supervise is None:
        raise RuntimeError("Supervise genre was not found.")
    return str(supervise["id"]), str(supervise["title"])


def supervise_cases(genre_id: str) -> list[dict[str, object]]:
    query = urlencode({"genre_id": genre_id, "status": "all", "limit": "200"})
    return caseclosed_request(f"/api/v1/extension-api/cases?{query}")["items"]


def supervised_contacts() -> list[dict[str, object]]:
    query = urlencode({"tag": "supervised-student", "status": "active", "kind": "person", "limit": "200"})
    return caseclosed_request(f"/api/v1/extension-api/contacts?{query}")["items"]


def case_stakeholders(case_id: str) -> list[dict[str, object]]:
    return caseclosed_request(f"/api/v1/extension-api/cases/{case_id}/stakeholders")["items"]


def page_data() -> dict[str, object]:
    genre_id, genre_title = launch_genre()
    cases = supervise_cases(genre_id)
    contacts = supervised_contacts()
    used_contact_ids: set[str] = set()
    used_names = {normalize_name(case.get("name")) for case in cases}
    enriched_cases: list[dict[str, object]] = []
    for case in cases:
        stakeholders = case_stakeholders(str(case["id"]))
        case = {**case, "stakeholders": stakeholders}
        enriched_cases.append(case)
        for stakeholder in stakeholders:
            used_contact_ids.add(str(stakeholder.get("contact_id") or ""))
    eligible_contacts = [
        contact
        for contact in contacts
        if str(contact.get("id") or "") not in used_contact_ids
        and normalize_name(contact.get("display_name")) not in used_names
    ]
    references: list[dict[str, object]] = []
    for case in enriched_cases:
        description = str(case.get("description") or "").strip()
        if not description:
            continue
        tags: list[str] = []
        seen_tags: set[str] = set()
        stakeholder_names: list[str] = []
        for stakeholder in case.get("stakeholders") if isinstance(case.get("stakeholders"), list) else []:
            if not isinstance(stakeholder, dict):
                continue
            name = str(stakeholder.get("contact_display_name") or "").strip()
            if name:
                stakeholder_names.append(name)
            for tag in comparable_tags_from_values(stakeholder.get("contact_tags")):
                key = tag.casefold()
                if key not in seen_tags:
                    tags.append(tag)
                    seen_tags.add(key)
        references.append(
            {
                "id": case.get("id"),
                "name": case.get("name"),
                "description": description,
                "tags": tags,
                "stakeholder_names": stakeholder_names,
            }
        )
    return {
        "genre_id": genre_id,
        "genre_title": genre_title,
        "contacts": eligible_contacts,
        "references": references,
        "existing_cases": enriched_cases,
    }


def create_case(payload: dict[str, object]) -> dict[str, object]:
    contact_id = str(payload.get("contact_id") or "")
    if not contact_id:
        raise RuntimeError("Select a student Contact.")
    data = page_data()
    contact = next((item for item in data["contacts"] if item.get("id") == contact_id), None)
    if contact is None:
        raise RuntimeError("Selected Contact already has a Supervise Case or is not eligible.")
    display_name = str(contact.get("display_name") or "").strip()
    description = str(payload.get("description") or "").strip()
    if not description:
        description = f"{display_name}さんの指導に関する連絡、面談、進捗確認、必要な手続きやタスクをまとめるためのケース。"
    created = caseclosed_request(
        "/api/v1/extension-api/cases",
        method="POST",
        payload={
            "name": display_name,
            "description": description,
            "genre_id": data["genre_id"],
            "progress_status": "not_started",
            "tags": case_tags_for_contact(contact),
        },
    )["case"]
    stakeholder = caseclosed_request(
        f"/api/v1/extension-api/cases/{created['id']}/stakeholders",
        method="POST",
        payload={"contact_id": contact_id, "role": "student"},
    )["stakeholder"]
    auto_assign_rule = None
    email = primary_email(contact).strip()
    if email:
        auto_assign_rule = caseclosed_request(
            f"/api/v1/extension-api/cases/{created['id']}/auto-assign-rules",
            method="POST",
            payload={"sender_email": email, "label": display_name},
        )["rule"]
    return {"case": created, "stakeholder": stakeholder, "auto_assign_rule": auto_assign_rule}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/":
            self.respond_html()
            return
        if self.path == "/api/data":
            self.respond_json(page_data)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path == "/api/create":
            self.respond_json(lambda: create_case(self.read_json()))
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def read_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length") or "0")
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def respond_json(self, producer) -> None:
        try:
            payload = {"ok": True, "data": producer()}
            status = HTTPStatus.OK
        except HTTPError as error:
            payload = {"ok": False, "error": error.read().decode("utf-8")}
            status = HTTPStatus.BAD_GATEWAY
        except Exception as error:
            payload = {"ok": False, "error": str(error)}
            status = HTTPStatus.INTERNAL_SERVER_ERROR
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def respond_html(self) -> None:
        html = """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Supervise Case Template</title>
  <style>
    body { margin: 0; background: #f2d49f; color: #4d241b; font-family: system-ui, sans-serif; }
    main { max-width: 920px; margin: 0 auto; padding: 28px; display: grid; gap: 16px; }
    header, section { border: 1px solid rgba(117, 88, 70, 0.18); border-radius: 8px; background: rgba(255, 250, 242, 0.72); padding: 16px; }
    h1, h2, p { margin: 0; }
    header { display: flex; justify-content: space-between; gap: 12px; align-items: end; }
    h1 { font-size: 1.8rem; }
    .grid { display: grid; grid-template-columns: minmax(0, 0.85fr) minmax(0, 1.15fr); gap: 14px; align-items: start; }
    .grid > *, .stack > * { min-width: 0; }
    label { display: grid; gap: 6px; font-weight: 750; min-width: 0; }
    select, textarea { box-sizing: border-box; width: 100%; min-width: 0; border: 1px solid rgba(117, 88, 70, 0.22); border-radius: 8px; background: #fffaf2; color: #4d241b; font: inherit; padding: 9px 10px; }
    .reference-card { box-sizing: border-box; width: 100%; min-width: 0; border: 1px solid rgba(117, 88, 70, 0.18); border-radius: 8px; background: rgba(255, 250, 242, 0.62); padding: 10px; display: grid; gap: 4px; }
    .reference-card strong { display: block; min-height: 1.3em; overflow-wrap: anywhere; }
    textarea { min-height: 170px; resize: vertical; }
    button { box-sizing: border-box; width: 100%; min-width: 0; min-height: 40px; border: 1px solid rgba(117, 88, 70, 0.22); border-radius: 8px; background: #fffaf2; color: #4d241b; font: inherit; font-weight: 800; padding: 8px 14px; cursor: pointer; }
    header button { width: auto; }
    button:disabled { opacity: .55; cursor: default; }
    .stack { display: grid; gap: 10px; }
    .muted { color: rgba(80, 48, 35, 0.68); font-weight: 650; }
    .notice { border-color: rgba(56, 120, 74, .26); background: rgba(231, 248, 230, .72); }
    .error { border-color: rgba(180, 66, 45, .3); background: rgba(255, 235, 228, .76); }
    ul { margin: 8px 0 0; padding-left: 1.2rem; }
    @media (max-width: 760px) { main { padding: 16px; } header, .grid { display: grid; grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <main>
    <header>
      <div class=\"stack\">
        <p class=\"muted\">CaseClosed Case Template</p>
        <h1>Supervise Case</h1>
      </div>
      <button id=\"reload\" type=\"button\">Reload</button>
    </header>
    <section id=\"feedback\" class=\"muted\">Loading...</section>
    <section class=\"grid\">
      <div class=\"stack\">
        <label>Student
          <select id=\"student\"></select>
        </label>
        <div class=\"reference-card\">
          <span class=\"muted\">Auto Reference</span>
          <strong id=\"reference\">-</strong>
        </div>
        <button id=\"create\" type=\"button\">Create Supervise Case</button>
      </div>
      <label>Overview
        <textarea id=\"description\"></textarea>
      </label>
    </section>
    <section>
      <h2>Existing Supervise Cases</h2>
      <ul id=\"existing\"></ul>
    </section>
  </main>
  <script>
    let state = null;
    const student = document.getElementById('student');
    const reference = document.getElementById('reference');
    const description = document.getElementById('description');
    const feedback = document.getElementById('feedback');
    const existing = document.getElementById('existing');
    function setFeedback(text, kind = 'muted') {
      feedback.className = kind;
      feedback.textContent = text;
    }
    function currentStudent() {
      return (state?.contacts ?? []).find((item) => item.id === student.value) ?? null;
    }
    function comparableTags(item) {
      const excluded = new Set(['students', 'ut', 'supervised-student']);
      const tags = [];
      const seen = new Set();
      for (const value of item?.tags ?? []) {
        const tag = String(value ?? '').trim();
        const key = tag.toLowerCase();
        if (tag && !excluded.has(key) && !seen.has(key)) {
          tags.push(tag);
          seen.add(key);
        }
      }
      return tags;
    }
    function referenceScore(contact, ref) {
      const contactTags = new Set(comparableTags(contact).map((tag) => tag.toLowerCase()));
      const refTags = new Set((ref.tags ?? []).map((tag) => String(tag ?? '').trim().toLowerCase()).filter(Boolean));
      if (contactTags.size === 0 || refTags.size === 0) return { overlap: 0, union: contactTags.size + refTags.size, score: 0 };
      let overlap = 0;
      for (const tag of contactTags) {
        if (refTags.has(tag)) overlap += 1;
      }
      const union = new Set([...contactTags, ...refTags]).size;
      return { overlap, union, score: union === 0 ? 0 : overlap / union };
    }
    function automaticReferenceFor(contact) {
      if (!contact) return null;
      let best = null;
      for (const ref of state?.references ?? []) {
        const score = referenceScore(contact, ref);
        if (score.overlap === 0) continue;
        if (!best || score.score > best.score.score || (score.score === best.score.score && score.overlap > best.score.overlap)) {
          best = { ref, score };
        }
      }
      return best;
    }
    function overviewFor(contact) {
      if (!contact) return '';
      const best = automaticReferenceFor(contact);
      if (best?.ref?.description) {
        const names = [best.ref.name, ...(best.ref.stakeholder_names ?? [])].filter(Boolean);
        let base = best.ref.description.trim();
        for (const name of names) {
          base = base.replaceAll(name, contact.display_name || '');
        }
        if (base && base !== best.ref.description) return base;
      }
      return `${contact.display_name}さんの指導に関する連絡、面談、進捗確認、必要な手続きやタスクをまとめるためのケース。`;
    }
    function updateOverview() {
      const contact = currentStudent();
      const best = automaticReferenceFor(contact);
      reference.textContent = best ? `${best.ref.name} (${best.score.overlap}/${best.score.union} tags)` : 'No similar Case';
      description.value = overviewFor(contact);
    }
    function render() {
      student.innerHTML = '';
      for (const contact of state.contacts) {
        const option = document.createElement('option');
        option.value = contact.id;
        const email = (contact.email_addresses || []).find((item) => item.is_primary) || (contact.email_addresses || [])[0];
        option.textContent = email ? `${contact.display_name} / ${email.email_address}` : contact.display_name;
        student.appendChild(option);
      }
      existing.innerHTML = '';
      for (const item of state.existing_cases) {
        const li = document.createElement('li');
        const names = (item.stakeholders || []).map((s) => s.contact_display_name).join(', ') || 'No stakeholder';
        li.textContent = `${item.name}: ${names}`;
        existing.appendChild(li);
      }
      updateOverview();
      setFeedback(state.contacts.length === 0 ? 'No eligible supervised-student Contacts remain.' : `${state.contacts.length} eligible student(s).`, state.contacts.length === 0 ? 'error' : 'muted');
      document.getElementById('create').disabled = state.contacts.length === 0;
    }
    async function load() {
      setFeedback('Loading...');
      const response = await fetch('./api/data');
      const payload = await response.json();
      if (!payload.ok) throw new Error(payload.error || 'Load failed');
      state = payload.data;
      render();
    }
    async function create() {
      const contact = currentStudent();
      if (!contact) return;
      setFeedback('Creating...');
      const response = await fetch('./api/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ contact_id: contact.id, description: description.value }),
      });
      const payload = await response.json();
      if (!payload.ok) throw new Error(payload.error || 'Create failed');
      setFeedback(`Created ${payload.data.case.name}.`, 'notice');
      window.location.assign('/cases');
    }
    student.addEventListener('change', updateOverview);
    document.getElementById('reload').addEventListener('click', () => load().catch((error) => setFeedback(error.message, 'error')));
    document.getElementById('create').addEventListener('click', () => create().catch((error) => setFeedback(error.message, 'error')));
    load().catch((error) => setFeedback(error.message, 'error'));
  </script>
</body>
</html>
"""
        data = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    server.serve_forever()
