# Phase 4 Mail Implementation Notes

Version: 2026-05-28
Status: Closed

This document records the behavior accepted at the end of Phase 4. It
supplements `API_Design.md`, `DB_Design.md`, `Screen_Design.md`, and
`Worker_Job_Design.md`.

## Scope Closed In Phase 4

Phase 4 now covers the practical mail entrance:

- Gmail OAuth connection, readonly sync, and Gmail send.
- Manual daily Gmail loading and automatic periodic Gmail loading.
- Gmail draft exclusion. Gmail-side drafts must not be imported.
- App-side mail draft save/load/delete with a 30-day retention window.
- Mail list, calendar/date navigation, Needs Action, Done, Skip, and thread
  detail views.
- Pending Contact resolution and follow-up processing.
- Contact status effects for `active`, `archived`, `skipped`, and `spam`.
- Mailing list sender display with optional Reply-To based sender resolution.
- LLM-backed or deterministic mail importance, summary, translation, contact
  prefill, contact AI memo, and compose draft generation routes.
- Pinned mail exclusion from automatic summary generation.
- HTML mail display with sanitized iframe rendering.
- Send-only mail display in DoneBox and reply/send thread integration.
- Compose support for recipients, CC/BCC, attachments, signatures, app drafts,
  and LLM generation.

## Gmail Loading

The Gmail import path excludes drafts in two ways:

- Gmail list queries include `-in:drafts`.
- Fetched messages with the `DRAFT` label are skipped defensively.

Manual daily loading imports Gmail messages for the selected day and then lets
downstream jobs continue in the background. Automatic loading scans from newest
to older messages and stops when an already-loaded Gmail message is found. If
the maximum import count is reached before a loaded message appears, the
remaining unloaded dates are marked for the mail calendar and daily load button.

The mail screen polls Gmail auto-import status and refreshes the visible list
when a successful auto-import adds mail. It also shows:

- last auto-import run time,
- last auto-import error,
- daily loaded/received/sent counts.

Daily received count excludes sent, skip, spam, and still-classifying mail at
render time.

## Mail Storage And Threading

`gmail_messages` is the authoritative table for Gmail-originated mail. Gmail
message id, Gmail thread id, RFC Message-ID, In-Reply-To, References, Sender,
Reply-To, List-Id, To, Cc, Bcc, text body, HTML body, labels, and Gmail links
are preserved where available.

Outgoing Gmail messages with the `SENT` label are stored as thread history, not
inbox work:

- `effective_importance = sent`
- `processed_status = processed`
- `read_status = read`
- no Pending Contact creation
- no importance classification
- no automatic summary

Send-only messages created by CaseClosed become provisional thread/list items
in DoneBox immediately. When Gmail send succeeds, the sent Gmail message is
stored and linked where possible.

## Contact And Importance Rules

Inbound messages resolve sender identity through Contacts. If the From contact
is a mailing list with `sender_resolution_mode = reply_to`, Reply-To is used as
the display/real sender candidate when resolvable.

Contact status rules:

- `active` and `archived`: mail continues through normal handling.
- `skipped`: mail goes to Skip even when the contact is a mailing list.
- `spam`: mail goes to Skip, displays a SPAM badge, is visually muted, and
  cannot be opened from the list.

LLM-blocked mail is pinned before LLM classification and shows the blocked
badge. Pinned mail means "read directly" and is not summarized automatically.

## Summary, Translation, And HTML Display

High/Middle inbound mail can be summarized. Low, Skip, Sent, and Pinned mail are
not automatically summarized. English mail may show both a summary and a
translation; the translation should be a translation of the original body, not a
second summary.

Plain text bodies linkify URLs and shorten long displayed URLs while preserving
their original href. HTML mail is sanitized and rendered inside an iframe whose
height is measured from the rendered content.

## Compose, Drafts, And Generation

Compose supports:

- To/Cc/Bcc recipient suggestions from Contacts, ordered Active, Archive, Skip;
  SPAM contacts are ignored.
- Attachments through Gmail send.
- Signatures with a non-deletable "none" signature and remembered selection.
- App-side mail drafts stored in a separate drafts database.
- Draft load scoped by reply target. New-mail drafts are scoped separately from
  reply drafts.
- Draft attachment references are preserved, but browser file path limitations
  mean missing attachments ask the user to reattach.
- App-side drafts older than 30 days are automatically deleted.
- LLM generation uses instruction, standard prompt, reply context, recipient
  contacts, placeholder case summaries, and current body. Generated body
  replaces the current body; generated subject fills only an empty subject.

## Navigation And Workflow

Needs Action shows threads containing incomplete High/Middle mail. Pinned and
Low mail are excluded.

When the final action-required inbound message in a thread is completed, the
thread view waits 1.5 seconds. If the user does not interact, it returns to the
screen that opened the detail view.

Mail list importance sorting shows a visual threshold between Middle-or-higher
mail and Low-or-lower mail. When Needs Action is empty, the clear-state mascot
is shown.

## Tests

Phase 4 closure expects the following local checks to pass:

- `python -m pytest backend/tests`
- `npm.cmd run test -- --run`
- `npm.cmd run build`

## Deferred To Later Phases

The following are deliberately left for later phases:

- Case linking and `case_mail_links`.
- Real Case/Task side effects from mail actions.
- Storage-backed attachment persistence and file management.
- Calendar event creation.
- Gmail star write-back.
- Full external operation/manual-resolution treatment for unknown Gmail send
  outcomes.
