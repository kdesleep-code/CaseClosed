# Phase 4 Mail Implementation Notes

Version: 2026-05-25

This document records behavior confirmed during the Phase 4 mail UI/API review.
It is normative for the current implementation and supplements `API_Design.md`
and `Worker_Job_Design.md`.

## Scope

Phase 4 currently focuses on the mail entrance, mock ingestion, Pending Contact
resolution, mail list UI, and thread detail UI. External Gmail sync and real LLM
providers are still outside the current implementation scope.

## Mail Ingestion

`POST /api/v1/mails/mock-ingest` is the current ingestion entry point.

It stores:

- Gmail message identifiers
- Gmail thread identifiers
- RFC Message-ID related headers
- From / Sender / Reply-To / To / Cc / Bcc
- List-Id
- received_at as JST ISO text
- snippet and body text
- Gmail labels
- app-side user state
- app-side auto state

The app primary key is `gmail_messages.id`. Gmail API's message id and RFC
Message-ID are stored separately and must not be treated as the app primary key.

## Inbound Message Route

Inbound messages are Gmail messages without the `SENT` label.

1. Save Gmail primary data into `gmail_messages`.
2. Resolve the From address against Contacts.
3. If From is unresolved, set Pending Contact state and stop downstream mail
   automation.
4. If From resolves to a Mailing List contact with
   `sender_resolution_mode = reply_to`, resolve Reply-To as the real sender
   candidate.
5. If the resolved contact is skipped, set `effective_importance = skip` and do
   not enqueue downstream automation.
6. Apply the resolved Contact's mail importance rule:
   - `llm`: enqueue normal `mail_importance_classification`.
   - `fixed`: set the configured importance directly and skip importance LLM.
     Fixed values may be `pinned`, `high`, `middle`, or `low`.
     `skip` is represented by the Contact status `skipped`, not by a fixed
     importance rule value.
   - `llm_with_instruction`: enqueue `mail_importance_classification` with the
     Contact's additional instruction text.
7. Fixed `high` / `middle` still enqueue `mail_summary` because they need a mail
   summary even though importance classification was skipped. Fixed `pinned`
   does not enqueue `mail_summary`.

Pending Contact blocks importance classification, Case decision, and automatic
summary generation. Contact registration prefill is the only LLM helper allowed
while a sender is pending.

When Pending Contact is later resolved, the same resolved Contact mail
importance rule must be applied:

- `fixed` sets the mail auto importance directly and skips the importance LLM.
- `llm_with_instruction` resumes importance classification with the Contact's
  additional instruction text.
- `skipped` Contact releases the mail to `skip`.

Contact-side fixed importance rule changes also rewrite existing matching mail
auto importance in bulk. User-edited `mail_user_state.user_importance` is not
cleared; API/list/detail effective importance must prefer the user value over
the rewritten auto value.

## Outgoing Message Route

Outgoing messages are Gmail messages with the `SENT` label.

Outgoing messages are conversation history, not inbox work items.

- Save outgoing messages into `gmail_messages`.
- Include outgoing messages in thread detail.
- Do not create or update Pending Contact from the outgoing From address.
- Do not enqueue `mail_importance_classification`.
- Do not run automatic summary generation for outgoing messages.
- Set `mail_auto_state.effective_importance = sent`.
- Set `mail_user_state.processed_status = processed`.
- Set `mail_user_state.read_status = read`.
- Hide importance badges and importance edit menus for outgoing messages in the
  thread UI.

## Send Requests and Scheduled Send

Before real Gmail API integration, outgoing user actions are represented by
`mail_send_requests`. This table is also the planned app-side boundary for
future Gmail send operations.

The current send rule is:

- Pressing `Send` does not send immediately.
- `Send` creates a scheduled send request for `now(JST) + 1 minute`.
- Pressing `Schedule Send` creates a scheduled send request for the user-selected
  `scheduled_at`.
- Both flows use `status = scheduled_mock` until the user explicitly sends now
  or the worker reaches `available_at`.
- The `mail_send_mock` Job uses `available_at = scheduled_at`.

This deliberately gives every normal send a short undo window. While the request
is waiting, the user can:

- send immediately
- change the scheduled time
- cancel the send

### Send request statuses

Current implementation statuses:

```text
scheduled_mock
queued_mock
sending_mock
sent_mock
canceled
```

- `scheduled_mock`: App-side send request is waiting for its scheduled time.
  This is the normal state after both `Send` and `Schedule Send`.
- `queued_mock`: User selected `Send now`, or the request is otherwise ready for
  immediate worker execution.
- `sending_mock`: Mock worker has started local send simulation.
- `sent_mock`: Mock worker has produced a local SENT GmailMessage for review.
  In the real Gmail implementation, the equivalent state should be treated as
  "sent request completed; wait for Gmail sync to provide the authoritative
  sent message."
- `canceled`: User canceled before external send execution.

`queued_mock`, `sending_mock`, and `sent_mock` are mock/external-integration
bridge states. The UI must not treat them as user-facing work items once the
request is no longer cancelable.

### Display rules

Scheduled send requests are visible in the mail UI before execution.

- Reply send requests appear inside the reply target's thread.
- Send-only requests with no reply target receive a provisional thread id derived
  from the send request id.
- Send-only requests appear in the `Done` tab for their scheduled date.
- Clicking a send-only request opens the provisional thread detail view.
- After `Send` or `Schedule Send`, the Compose view navigates to the relevant
  thread detail view:
  - reply send: the reply target thread
  - send-only: the provisional send request thread
- Canceling a send request removes it from normal mail UI. It may remain visible
  in maintenance/debug/log surfaces.

### Gmail sync handoff

`gmail_messages` remains the authoritative table for Gmail-originated primary
data. A pre-send `mail_send_request` is not a Gmail message.

When real Gmail sending is implemented:

- CaseClosed should create/execute a Gmail send operation from
  `mail_send_requests`.
- After external send succeeds, normal mail UI should stop showing the provisional
  send card.
- The sent message shown in thread history should come from subsequent Gmail
  sync, identified by Gmail message/thread ids and RFC Message-ID where
  available.
- If possible, the send request should link to the synced sent message via
  `sent_message_id`.
- This avoids double-display between "internal request" and "Gmail's sent
  message".

If Gmail send result is unknown, do not automatically retry the external send.
Use maintenance/debug/manual-resolution flow, because double sending is more
dangerous than delayed sending.

## Mail List API

`GET /api/v1/mails` returns inbound thread representative rows plus visible
pre-send requests, not raw Gmail message rows.

- Exclude outgoing messages.
- Collapse inbound messages with the same `thread_id`.
- Use the newest inbound message as the representative row.
- `tab=unprocessed` and `tab=processed` are evaluated from the representative
  row's `mail_user_state.processed_status`.
- If a thread contains both `skip` and non-`skip` inbound messages, non-`skip`
  importance wins for list display and filtering.
- The list row importance is the highest inbound importance in the thread, using
  the order `pinned > high > middle > low > unclassified > pending > skip`.
- Search matches raw inbound message fields inside the thread. If any inbound
  message in a thread matches the query, the returned row is still the newest
  inbound representative row for that thread.
- Cursor ordering is based on the representative row: `received_at DESC, id`.
- Send-only scheduled requests are included in the processed/Done view for their
  scheduled date. They use `effective_importance = sent`, `processed_status =
  processed`, and `read_status = read`.

This keeps the list aligned with the user's workflow: choose a thread to handle,
then read the entire thread in the detail view.

## Mail Dates API

`GET /api/v1/mails/dates` counts the same rows as `GET /api/v1/mails` for the
chosen tab, including visible send-only scheduled requests in the Done tab.

The calendar must therefore match the list, not raw Gmail message count.

## Mail Detail API

`GET /api/v1/mails/{message_id}` returns:

- the focused message
- all thread messages
- per-message user state where available
- per-message auto state where available
- recipient contact summaries where available
- mail summaries where available
- empty case/attachment/draft containers until later phases populate them

For a send-only scheduled request, `{message_id}` may be a `mail_send_requests.id`.
In that case the API returns a provisional detail payload:

- `message` is a synthesized outgoing message object
- `thread_messages` is empty
- `scheduled_send_requests` contains the send request
- `user_state` is processed/read
- `auto_state.effective_importance = sent`

The frontend displays the whole thread newest first and scrolls the focused
message into view.

## Thread Detail UI

The thread UI follows these rules:

- Show all messages in the thread.
- Show newest messages first.
- Show date dividers when the displayed message date changes.
- Inbound messages show sender identity beside the message body.
- Outgoing messages use a distinct but quiet background color.
- Inbound messages can show and edit importance.
- Outgoing messages do not show importance.
- The top of the thread page reserves a Thread Summary panel.

## Mail Summary Worker

The current implementation has a mock LLM summary worker for UI/API review.

- Summary jobs use `job_type = mail_summary`.
- LLM runs use `function_type = mail_summary`.
- The mock provider is deterministic and does not call an external LLM service.
- Summaries are stored in `mail_summaries` as message-level summaries.
- Thread detail combines summaries for messages in the thread and displays them
  in the summary area at the top of the page.
- Summaries are based on inbound High/Middle messages. Pinned messages are not
  automatically summarized.
- Summary text must be stored and shown in full in the mail detail screen.
  List cards may still show a shortened preview.
- If a translation-only text is available, the mail detail screen shows it as a
  collapsed section. The original body is also collapsed when a summary exists.
- Low messages are not automatically summarized.
- Outgoing-only content should not trigger automatic summary generation.
- Summary output should be stored separately from raw Gmail message bodies.
- `llm_runs.input_source_json` stores message identifiers, subject, thread id,
  and importance only. Full body text must not be copied into the diagnostic
  LLM audit fields.

## Pending and Unclassified Visibility

`pending` and `unclassified` are not normal steady states for mail that the user
is expected to handle in the main flow.

- Pending mail may be visible in maintenance/debug surfaces.
- If Pending or Unclassified mail appears in normal mail list/detail flow, the UI
  should make it visually clear that this is a bug/maintenance signal.
- Maintenance can provide a "refresh pending mail state" action, but it should
  not silently hide the inconsistency.

## Current Known Non-Goals

The following are intentionally not complete yet:

- real Gmail sync
- Gmail star write-back
- real OpenAI provider integration
- Case decision and `case_mail_links`
- attachment metadata fetching
- draft/reply generation
- Gmail send external operations
