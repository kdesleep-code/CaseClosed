# CaseClosed LLM / Prompt 設計書

Version: 0.1  
作成日: 2026-05-22  
対象: 個人用案件管理Webアプリ CaseClosed

---

## 0. 本書の位置づけ

本書は、CaseClosed における LLM 支援機能の役割、入力情報、出力形式、保存先、実行タイミング、失敗時挙動を定義する。

本書は以下の設計書を前提とする。

- CaseClosed 概要設計書
- CaseClosed 詳細設計書
- CaseClosed DB設計書
- CaseClosed API設計書
- CaseClosed Worker / Job / External Operation設計書
- CaseClosed 画面仕様書
- CaseClosed 状態遷移設計書

本書では、プロンプト本文の最終文言は固定しない。  
ただし、各LLM機能の入出力、JSON schema、保存先、再実行方針は本書に従う。

---

# 1. LLM利用の基本方針

## 1.1 LLMの位置づけ

LLMは、ユーザーの操作を代替するものではなく、以下を支援する。

- メールの重要度判断
- メール本文の和訳要約
- Case候補選択
- Contact登録補助
- 返信草案作成
- 新規メール草案作成
- Task候補生成
- Calendar予定候補抽出
- Case Context更新
- Contact Context更新
- ファイル要約
- 引継ぎログ生成

## 1.2 ユーザー確定値を上書きしない

LLMは、以下を上書きしてはならない。

- user_importance
- ユーザーが設定したCase関連メール
- ユーザーが作成・編集したTask
- ユーザーが編集したContact情報
- ユーザーが編集したDraft本文
- ユーザーが設定したFile LLM input可否

LLM結果は、原則として以下のいずれかに保存する。

```text
auto_* カラム
suggestion テーブル
versioned context テーブル
mail_drafts
llm_runs
```

## 1.3 LLM入力全文の保存方針

LLM入力全文は `llm_runs` に保存しない。

保存するもの:

- function_type
- model_name
- provider_name
- prompt_version_id
- input_hash
- input_source_json
- input_diagnostic_json
- output_json
- status
- error_type
- error_message
- retry_count
- token数
- 推定コスト

保存しないもの:

- メール本文全文
- ファイル本文全文
- LLMに渡した最終プロンプト全文

ただし、プロンプトエンジニアリングのために、入力の構成を後から理解できる診断情報は保存する。

例:

```json
{
  "mail_count": 1,
  "has_thread_context": true,
  "case_context_version_id": "ccv_...",
  "included_fields": ["subject", "from", "body_text", "attachments_meta"],
  "body_char_count": 12450,
  "truncated": false,
  "instruction_profile": ["student_mail", "concise_reply"]
}
```

## 1.4 input_hash

`input_hash` は、LLMに渡す入力情報を正規化したうえで算出する。

正規化対象:

- system instruction
- developer instruction
- prompt_version
- user追加プロンプト
- input_source_jsonで参照される本文・Context・候補リスト
- モデルに渡したschema

ただし、ハッシュ算出後に入力全文は保存しない。

## 1.5 prompt_version

LLM機能ごとに `prompt_versions` を持つ。

管理対象:

- function_type
- version
- system_prompt_template
- user_prompt_template
- output_schema_json
- retry_prompt_template
- active flag
- created_at
- memo

プロンプト改善時には、新しいversionを作成する。  
既存llm_runsは過去versionを参照する。

### Provider / Model差し替え

LLM機能はOpenAI APIを初期providerとして想定するが、prompt設計・出力schema・保存形式は特定providerに依存させない。

- `prompt_versions` はfunction_typeごとのpromptと出力schemaを管理する。
- `default_provider_name` / `default_model_name` は初期値であり、実行時設定や機能別設定で差し替え可能とする。
- `llm_runs.provider_name` / `model_name` には実際に使ったprovider/modelを保存する。
- テストでは `mock` / deterministic providerを使い、外部LLMの品質や応答揺れに依存しない。
- OpenAI provider、オンプレミスLLM provider、将来の別クラウドproviderは、同じ入出力schemaを満たす限り差し替え可能とする。

## 1.6 LLM失敗の分類

### システム連携失敗

以下は失敗として扱う。

- JSON不正
- 必須フィールド欠落
- enum違反
- schema不一致
- provider API error
- timeout
- rate limit
- cost limit超過

これらはリトライまたはfailed扱い。

### 人間が見て微妙な出力

以下は失敗扱いしない。

- 要約の表現が微妙
- 返信草案が好みに合わない
- Case判定が少し怪しい
- Contact候補が曖昧
- Task候補が粒度不適切

構造的に正しい出力であれば `succeeded` として保存し、ユーザーが手動修正する。

## 1.7 リトライ方針

JSON不正など構造エラーの場合はリトライする。

基本:

```text
max_retry_count = 3
```

リトライ時には、同じプロンプトを単純再送せず、以下を加える。

```text
前回出力はJSON schemaに一致しませんでした。
必ず指定schemaに一致するJSONのみを返してください。
説明文、Markdown、コードブロックを含めないでください。
```

provider API errorやrate limitは、Worker側のbackoff方針に従う。

## 1.8 Cost Limit

Cost Limitを超過しそうな場合、または超過した場合、LLM処理を黙って落とさない。

処理:

1. LLM Runを failed または skipped相当で記録する。
2. System Maintenance CaseにTaskを作成する。
3. Maintenance画面に警告を表示する。
4. 必要に応じて自動LLM Jobを停止する。

Task例:

```text
LLM利用量が上限に近づいているため設定を確認する
LLM Cost Limitに達したため自動処理を再開するか判断する
```

---

# 2. LLM機能一覧

## 2.1 自動実行

```text
mail_importance_classification
contact_registration_prefill
mail_summary_ja
mail_case_selection
mail_thread_summary
case_context_update
contact_context_update
file_security_meta_classification
```

## 2.2 手動実行

```text
reply_draft_generation
new_mail_draft_generation
mail_task_suggestion
subtask_suggestion
calendar_candidate_extraction
preparation_task_suggestion
reminder_mail_generation
file_summary
handover_log_generation
```

## 2.3 Pending中の例外

Contact未登録FromのメールはPendingになる。

Pending中は以下を停止する。

- mail_importance_classification
- mail_summary_ja
- mail_case_selection
- mail_thread_summary
- file fetchのCase連動処理

ただし、以下は実行可能。

```text
contact_registration_prefill
```

---

# 3. 共通出力形式

## 3.1 全LLM出力共通フィールド

各機能のoutput_jsonには、可能な限り以下を含める。

```json
{
  "schema_version": "1.0",
  "confidence": 0.0,
  "reasoning_summary": "",
  "warnings": []
}
```

## 3.2 reasoning_summary

`reasoning_summary` は、LLMの詳細な推論過程ではなく、ユーザー確認用の短い根拠説明である。

例:

```text
締切日時と回答依頼が明記されているためHighと判断。
```

## 3.3 warnings

以下のような注意を入れる。

```json
[
  "本文が長いため一部を省略して判定しました",
  "日付表現が曖昧です",
  "送信者情報から所属を確定できませんでした"
]
```

---

# 4. メール重要度判定

## 4.1 function_type

```text
mail_importance_classification
```

## 4.2 実行タイミング

自動実行。

条件:

```text
From Contactが解決済み
Contact skippedではない
user_importanceが未設定
rule_importanceが未設定またはLLM判定が必要
```

Pending中は実行しない。

## 4.3 入力

- subject
- from
- to
- cc
- received_at
- body_text
- snippet
- attachment metadata
- Gmail initial_is_starred
- Contact tags
- Contact memo
- Case候補の簡易情報
- 適用される追加指示
- 過去の同送信者メール処理傾向

## 4.4 出力JSON

```json
{
  "schema_version": "1.0",
  "importance": "High",
  "confidence": 0.82,
  "reasoning_summary": "返信または日程調整が必要な業務メールであるためHigh。",
  "requires_reply": true,
  "requires_task": true,
  "requires_calendar": false,
  "deadline_candidates": [
    {
      "date_text": "5月27日（水）まで",
      "normalized_date": "2026-05-27",
      "confidence": 0.78
    }
  ],
  "suggested_next_action": "日程調整フォームに回答する。",
  "warnings": []
}
```

## 4.5 importance enum

LLMが出力可能な値:

```text
High
Middle
Low
```

LLMは以下を出力不可。

```text
Pinned
Skip
Pending
```

## 4.6 保存先

- `mail_auto_state.llm_importance`
- `mail_auto_state.llm_importance_confidence`
- `mail_auto_state.requires_reply`
- `mail_auto_state.requires_task`
- `mail_auto_state.requires_calendar`
- `mail_auto_state.deadline_candidates_json`
- `llm_runs.output_json`

## 4.7 副作用

Highになった場合:

- Gmailスター付与 external_operation を作成する。
- mail_summary_ja Jobを作成する。
- mail_case_selection Jobを作成する。

Middleになった場合:

- mail_summary_ja Jobを作成する。
- mail_case_selection Jobを作成する。

Lowになった場合:

- 自動要約なし。
- 自動Case判定なし。

---

# 5. Pending Contact登録自動Fill

## 5.1 function_type

```text
contact_registration_prefill
```

## 5.2 実行タイミング

自動または手動。

主にPending Contact処理画面で実行する。

Pending中でも実行可能な唯一のLLM処理である。

## 5.3 入力

- from email address
- from display name
- subject
- body_text
- snippet
- signatureらしき部分
- To/Cc
- メールヘッダの範囲内メタ情報
- 同一Fromからの過去メール件名・snippet
- 既存Contact候補

## 5.4 出力JSON

```json
{
  "schema_version": "1.0",
  "suggested_display_name": "小川 華奈",
  "suggested_organization": "筑波大学 グローバル教育院事務室",
  "suggested_role": "事務担当",
  "suggested_tags": ["筑波大", "事務", "Humanics"],
  "suggested_memo": "HXP広報WGの日程調整連絡を担当している可能性がある。",
  "suggested_skip": false,
  "suggested_skip_reason": "",
  "confidence": 0.76,
  "reasoning_summary": "署名と本文から大学事務担当者と推定。",
  "warnings": []
}
```

## 5.5 保存先

- `contact_registration_suggestions`
- `llm_runs`

正式Contactには直接反映しない。  
ユーザーが採用・編集・破棄する。

## 5.6 suggested_skip

広告、no-reply、ML等の場合、`suggested_skip = true` を返してよい。

ただし、自動でContact skippedにはしない。  
ユーザー承認が必要。

---

# 6. High/Middleメール和訳要約

## 6.1 function_type

```text
mail_summary_ja
```

## 6.2 実行タイミング

自動実行。

条件:

```text
effective_importance ∈ {High, Middle}
Pendingではない
```

Lowは自動要約しない。

## 6.3 入力

- subject
- from
- to
- cc
- body_text
- thread context
- attachment metadata
- Contact情報
- Case Contextがあれば含める
- 追加指示

## 6.4 出力JSON

```json
{
  "schema_version": "1.0",
  "summary": "HXP広報WGの日程調整について、再度6月第2週で都合を回答してほしいという依頼。",
  "needs_action": true,
  "deadline": {
    "date_text": "5月27日（水）まで",
    "normalized_date": "2026-05-27",
    "confidence": 0.8
  },
  "next_action": "日程調整フォームに回答する。",
  "key_points": [
    "前回の日程調整では全員の都合が合わなかった。",
    "6月第2週で再調整する。",
    "回答期限は5月27日。"
  ],
  "reply_needed": false,
  "task_suggestion_title": "HXP広報WGの日程調整フォームに回答する",
  "calendar_candidate_exists": false,
  "confidence": 0.84,
  "reasoning_summary": "日程調整依頼と回答期限が明記されている。",
  "warnings": []
}
```

## 6.5 保存先

- `mail_summaries`
- `llm_runs`

## 6.6 画面表示

Mail一覧・Mail詳細で表示する。

---

# 7. Case判定

## 7.1 function_type

```text
mail_case_selection
```

## 7.2 実行タイミング

自動実行。

条件:

```text
effective_importance ∈ {High, Middle}
Pendingではない
Case候補抽出結果が存在する
```

## 7.3 入力

- mail subject
- from/to/cc
- body_text または summary
- Contact tags
- Contact関連Case
- Case候補リスト
- Case Context
- 過去の同一Thread/同一ContactのCase割当
- 除外キーワード

## 7.4 出力JSON

```json
{
  "schema_version": "1.0",
  "decision": "existing_case",
  "selected_case_id": "case_123",
  "confidence": 0.79,
  "reasoning_summary": "HXP広報WGに関する既存Caseと送信者・件名が一致するため。",
  "new_case_candidate": null,
  "warnings": []
}
```

## 7.5 decision enum

```text
existing_case
inbox_required
no_case_needed
new_case_candidate
uncertain
```

### existing_case

既存Caseの関連メール集合にprimaryとして追加する。

### inbox_required

Inbox Caseにprimaryとして追加する。

### no_case_needed

Case関連メール集合には追加しない。  
広告、汎用通知など。

### new_case_candidate

新規Case候補として提示する。  
自動作成はしない。

### uncertain

判断不能。  
Inboxまたはユーザー確認待ちにする。

## 7.6 保存先

- `case_mail_links`
- `mail_auto_state.case_decision_json`
- `case_suggestions` 相当が必要な場合は追加
- `llm_runs`

## 7.7 ユーザー値保護

ユーザーが設定したprimary CaseをLLMが上書きしてはならない。

---

# 8. スレッド全体要約

## 8.1 function_type

```text
mail_thread_summary
```

## 8.2 実行タイミング

自動または手動。

条件:

- Caseに入ったThread
- 複数メールを含むThread
- 重要なやり取りが続いているThread

## 8.3 入力

- Thread内メール一覧
- 各メールの送受信者
- 各メールの日時
- 各メールの要約
- 必要なら本文抜粋
- 関連Case Context

## 8.4 出力JSON

```json
{
  "schema_version": "1.0",
  "thread_summary": "IIIS Steering Committeeの開催連絡と資料提出依頼に関するスレッド。",
  "current_status": "資料提出期限が近づいている。",
  "latest_required_action": "資料が必要な場合は5月22日午前中までに送付する。",
  "timeline": [
    {
      "datetime": "2026-05-21T19:29:00+09:00",
      "event": "資料提出期限のリマインドが送信された。"
    }
  ],
  "open_questions": [],
  "confidence": 0.81,
  "warnings": []
}
```

## 8.5 保存先

- `mail_thread_summaries`
- `llm_runs`

---

# 9. 返信草案生成

## 9.1 function_type

```text
reply_draft_generation
```

## 9.2 実行タイミング

手動実行のみ。

## 9.3 入力

- 元メール
- Thread context
- mail_summary
- Case Context
- Contact Context
- 関連Task
- ユーザー追加プロンプト
- 既存草案があれば既存草案
- 返信方針

## 9.4 出力JSON

```json
{
  "schema_version": "1.0",
  "subject": "Re: HXP広報WG日程調整のお伺い",
  "body": "小川様\n\nお世話になっております。堀江です。\n日程調整の件、承知いたしました。指定のフォームより回答いたします。\n\nどうぞよろしくお願いいたします。\n\n堀江",
  "tone": "polite_concise",
  "assumptions": [
    "フォーム回答を行う前提で返信文を作成した。"
  ],
  "needs_user_review": true,
  "confidence": 0.76,
  "warnings": []
}
```

## 9.5 保存先

- `mail_drafts`
- `llm_runs`

```text
draft_type = reply
```

## 9.6 再生成

追加プロンプト付き再生成では、既存草案を入力に含める。

UI上の既存結果は上書きしてよい。  
llm_runsには履歴を残す。

---

# 10. 新規メール草案生成

## 10.1 function_type

```text
new_mail_draft_generation
```

## 10.2 実行タイミング

手動実行のみ。

## 10.3 入力

- ユーザーの作成指示
- 宛先Contact情報
- 関連Case Context
- 関連Task
- 過去の関連メール
- 追加プロンプト

## 10.4 出力JSON

```json
{
  "schema_version": "1.0",
  "subject": "研究打ち合わせの日程について",
  "body": "○○様\n\nお世話になっております。堀江です。\n研究打ち合わせの日程についてご相談です。\n...",
  "to_suggestions": [
    {
      "contact_id": "contact_123",
      "email": "example@example.com",
      "reason": "指定されたContact"
    }
  ],
  "cc_suggestions": [],
  "needs_user_review": true,
  "confidence": 0.72,
  "warnings": []
}
```

## 10.5 保存先

- `mail_drafts`
- `llm_runs`

```text
draft_type = new_mail
```

---

# 11. メールからTask候補生成

## 11.1 function_type

```text
mail_task_suggestion
```

## 11.2 実行タイミング

手動実行。

将来的にHighメールで候補だけ自動生成してもよいが、正式Task作成はユーザー承認必須。

## 11.3 入力

- メール本文
- mail_summary
- Case Context
- Contact情報
- 既存Task
- ユーザー追加プロンプト

## 11.4 出力JSON

```json
{
  "schema_version": "1.0",
  "task_suggestions": [
    {
      "title": "HXP広報WGの日程調整フォームに回答する",
      "description": "6月第2週の都合をフォームに入力する。",
      "due_at": "2026-05-27T23:59:00+09:00",
      "estimate_minutes": 10,
      "priority_hint": "High",
      "reason": "メール本文に回答期限が明記されている。",
      "confidence": 0.86
    }
  ],
  "warnings": []
}
```

## 11.5 保存先

- `task_suggestions`
- `llm_runs`

採用時のみ `tasks` に正式作成する。  
メールからTask作成した場合、原則としてメールはprocessedになる。

---

# 12. サブタスク候補生成

## 12.1 function_type

```text
subtask_suggestion
```

## 12.2 実行タイミング

手動実行。

## 12.3 入力

- 親Task
- Case Context
- 関連メール
- 関連ファイル要約
- ユーザー追加プロンプト

## 12.4 出力JSON

```json
{
  "schema_version": "1.0",
  "subtasks": [
    {
      "title": "必要資料を確認する",
      "description": "会議で必要な資料の有無を確認する。",
      "estimate_minutes": 15,
      "order": 1,
      "confidence": 0.75
    }
  ],
  "warnings": []
}
```

## 12.5 保存先

- `task_suggestions`
- `llm_runs`

---

# 13. Calendar予定候補抽出

## 13.1 function_type

```text
calendar_candidate_extraction
```

## 13.2 実行タイミング

手動実行。

メール詳細画面から実行する。

## 13.3 入力

- メール本文
- mail_summary
- thread context
- Case Context
- 既存Calendar情報
- ユーザー追加プロンプト

## 13.4 出力JSON

```json
{
  "schema_version": "1.0",
  "calendar_candidates": [
    {
      "title": "IIIS Steering Committee Meeting",
      "start_at": "2026-05-29T09:00:00+09:00",
      "end_at": "2026-05-29T10:00:00+09:00",
      "timezone": "Asia/Tokyo",
      "location": "IIIS 1F Meeting Room (L)",
      "description": "元メール件名: ...",
      "confidence": 0.87,
      "source_text": "May 29th, 2026, 9:00-"
    }
  ],
  "warnings": []
}
```

## 13.5 保存先

- calendar candidate一時保存テーブル、または `llm_runs.output_json`
- ユーザー確認後、Google Calendar作成 external_operation
- 成功後 `calendar_event_links`

## 13.6 注意

予定候補抽出だけではGoogle Calendarへ登録しない。  
ユーザー確認・編集後に登録する。

---

# 14. 準備Task候補生成

## 14.1 function_type

```text
preparation_task_suggestion
```

## 14.2 実行タイミング

手動または予定作成後の候補提示。

## 14.3 入力

- Calendar予定情報
- 元メール
- Case Context
- 関連Task
- ユーザー追加プロンプト

## 14.4 出力JSON

```json
{
  "schema_version": "1.0",
  "preparation_tasks": [
    {
      "title": "会議資料を確認する",
      "description": "Steering Committeeの資料が必要か確認する。",
      "due_at": "2026-05-28T18:00:00+09:00",
      "estimate_minutes": 20,
      "confidence": 0.74
    }
  ],
  "warnings": []
}
```

## 14.5 保存先

- `task_suggestions`
- `llm_runs`

---

# 15. リマインドメール生成

## 15.1 function_type

```text
reminder_mail_generation
```

## 15.2 実行タイミング

手動実行。

Follow-up Candidateからユーザーが必要と判断した場合に手動実行する。
初期実装では候補検出にLLMを使わない。

## 15.3 入力

- 元送信メール
- Thread context
- Follow-up Candidate情報
- Case Context
- Contact情報
- ユーザー追加プロンプト

## 15.4 出力JSON

```json
{
  "schema_version": "1.0",
  "subject": "Re: 研究打ち合わせの日程について",
  "body": "○○様\n\nお世話になっております。堀江です。\n先日お送りした件について、念のため再度ご連絡いたします。\n...",
  "tone": "polite_reminder",
  "needs_user_review": true,
  "confidence": 0.78,
  "warnings": []
}
```

## 15.5 保存先

- `mail_drafts`
- `llm_runs`

---

# 16. Case Context更新

## 16.1 function_type

```text
case_context_update
```

## 16.2 実行タイミング

自動または手動。

自動実行候補:

- Caseに重要メールが追加された
- Taskが作成/完了された
- 予定が作成された
- ファイル要約が追加された
- 一定期間更新されていない

## 16.3 入力

- 既存Case Context
- Case概要
- 最近のcase_events
- 関連メール要約
- 関連Task
- 関連予定
- 関連Contact
- 関連ファイル要約
- ユーザー編集済みメモ

## 16.4 出力JSON

```json
{
  "schema_version": "1.0",
  "case_overview": "HXP広報WGに関する連絡・日程調整を管理するCase。",
  "current_status": "6月第2週の日程調整への回答が必要。",
  "key_people": [
    {
      "name": "小川 華奈",
      "role": "グローバル教育院事務室"
    }
  ],
  "open_items": [
    "5月27日までに日程調整フォームへ回答する。"
  ],
  "recent_events": [
    "2026-05-21: 再日程調整依頼を受信。"
  ],
  "reply_policy": "事務連絡には簡潔に、対応予定を明示して返信する。",
  "notes": [
    "Humanics関連の広報WGに関する連絡。"
  ],
  "confidence": 0.78,
  "warnings": []
}
```

## 16.5 保存先

- `case_context_versions`
- `llm_runs`

## 16.6 注意

既存Contextを直接上書きせず、新versionとして保存する。  
UI上のeffective contextは最新採用versionを表示する。

---

# 17. Contact Context更新

## 17.1 function_type

```text
contact_context_update
```

## 17.2 実行タイミング

自動または手動。

候補:

- Contact作成後
- 新しい重要メール受信後
- ContactにCaseが追加された後

## 17.3 入力

- Contact情報
- メール履歴要約
- 関連Case
- タグ
- ユーザーメモ

## 17.4 出力JSON

```json
{
  "schema_version": "1.0",
  "contact_summary": "HXP広報WGの日程調整等を担当する大学事務担当者。",
  "relationship_notes": [
    "日程調整依頼を送ることがある。",
    "返信は簡潔かつ事務的でよい。"
  ],
  "related_cases": [
    "HXP広報WG"
  ],
  "suggested_tags": ["筑波大", "事務", "Humanics"],
  "confidence": 0.73,
  "warnings": []
}
```

## 17.5 保存先

- `contact_context_versions`
- `llm_runs`

---

# 18. ファイル機密度メタ判定

## 18.1 function_type

```text
file_security_meta_classification
```

## 18.2 実行タイミング

自動実行。

ファイル本文はLLMに渡さない。  
ファイル名、メール件名、送信者、Caseタグ、メール本文の一部メタ情報などから判定する。

## 18.3 入力

- filename
- mime_type
- size
- origin
- source mail subject
- source mail from
- Case tags
- Contact tags
- 周辺メタ情報

## 18.4 出力JSON

```json
{
  "schema_version": "1.0",
  "recommended_llm_policy": "confirm_required",
  "security_tags": ["学内限定", "会議資料"],
  "reasoning_summary": "IIIS会議資料に関連する添付のため、本文投入には確認を求めるべき。",
  "confidence": 0.71,
  "warnings": [
    "本文を読まずにメタ情報のみで判定しています。"
  ]
}
```

## 18.5 recommended_llm_policy enum

```text
allowed
confirm_required
forbidden
```

## 18.6 保存先

- `file_security_rules` または files系メタ情報
- `llm_runs`

## 18.7 注意

`forbidden` と判定された場合でも、最終的なPolicy変更はユーザー確認またはシステムルールに従う。  
ユーザーが設定したPolicyをLLMが上書きしてはならない。

---

# 19. ファイルLLM Digest

## 19.1 function_type

```text
file_summary
```

## 19.2 実行タイミング

Storage詳細の `Prepare LLM Digest` から手動実行する。

また、後続機能がファイルをLLM入力に使おうとした時点で対象版のDigestが存在しない場合、先にDigestを生成してStorageへ反映する。

## 19.3 実行条件

```text
llm_input_allowed = true:
  実行可

llm_input_allowed = false:
  実行不可
```

`file_security_meta_classification` はPhase 6では保留する。現時点の制御は `storage_objects.llm_input_allowed` を正とする。

## 19.4 入力

- storage_object_id
- storage_object_version_id
- filename
- content_type
- byte_size
- sha256_hex
- source_kind
- read_scope
- truncated
- limitations
- source_text

本文抽出は拡張子/形式ごとの抽出ブロックを通す。

現状:

- text系: 本文テキスト
- markdown / table系: 本文テキスト
- zip系: 展開せず構造ツリー
- PDF: PyMuPDF -> pypdf/PyPDF2 -> primitive fallback
- DOCX: python-docx利用時に段落テキスト
- 未対応形式: metadata_only とし、制約を `coverage.limitations` に残す

### 増分Digest入力

対象版のDigestがなく、対象版より過去にDigestがある場合は、対象ファイルから見て過去側にある最も新しいDigestをベースにする。

入力:

- base_summary_id
- base_storage_object_version_id
- base_version_number
- base_llm_digest
- base_file_description
- base_summary_points
- base_source_sha256_hex
- diffs

`diffs` は `file_version_diffs` を古い順に並べる。LLMは、削除行を現在存在しない情報、追加行を新しく存在する情報として扱い、差分に矛盾する旧Digestの事実を持ち越さない。

対象版に既にDigestがあり、ユーザーが明示的に再生成する場合は、対象版の本文抽出から全文ベースで再生成する。

## 19.5 出力JSON

```json
{
  "schema_version": "1.0",
  "file_description": "このファイルは会議メモの決定事項をまとめたテキストです。",
  "summary_points": [
    "2026-05-30の会議メモ。",
    "予算と締切の確認を含む。"
  ],
  "llm_digest": "後続LLM入力用の圧縮済み中間表現...",
  "structured_digest": {
    "document_type": "meeting_note",
    "facts": [],
    "entities": [],
    "dates": [],
    "numbers": [],
    "action_items": [],
    "structure_notes": []
  },
  "coverage": {
    "source_kind": "text",
    "read_scope": "text_content",
    "truncated": false,
    "limitations": []
  },
  "token_estimate": 320,
  "reasoning_summary": "Digest生成上の短い説明。",
  "warnings": []
}
```

`file_description` は1文程度、`summary_points` は最大5項目とする。主目的は人間向け要約ではなく、ファイルを後続LLMへ再投入するための情報圧縮である。

## 19.6 保存先

- `file_summaries`
- `llm_runs`

`file_summaries.storage_object_version_id` がNULLの場合は現在版のDigestを表す。ファイル更新で現在版が旧版へ退避された場合、該当Digestは旧版の `storage_object_version_id` に付け替える。

---

# 20. 引継ぎログ生成

## 20.1 function_type

```text
handover_log_generation
```

## 20.2 実行タイミング

手動実行。

候補:

- Case Closed前
- Case Archive前
- 年度末
- 委員会任期末
- ユーザーが明示実行

## 20.3 入力

- Case概要
- Case Context
- Caseメモ
- case_events
- 関連Task履歴
- 関連メール要約
- 関連予定
- 関連ファイル一覧
- 外部リンク
- 未解決事項
- 注意事項
- ユーザー追加プロンプト

高機密ファイル本文は自動では含めない。

## 20.4 出力形式

引継ぎログはMarkdown本文を生成する。

出力JSON:

```json
{
  "schema_version": "1.0",
  "title": "HXP広報WG 引継ぎログ",
  "markdown_body": "# HXP広報WG 引継ぎログ\n\n## 目的\n...",
  "contains_sensitive_information": true,
  "sensitivity_notes": [
    "関係者名と事務連絡内容を含みます。外部共有前に確認してください。"
  ],
  "unresolved_items": [
    "次年度の日程調整手順を確認する。"
  ],
  "confidence": 0.76,
  "warnings": []
}
```

## 20.5 保存先

- Generated fileとして保存
- `files.origin = Generated`
- `llm_runs`

## 20.6 編集

生成結果は確定版ではない。  
ユーザーが編集してから保存する。

---

# 21. LLM追加指示

## 21.1 目的

ユーザーが、送信者、Contactタグ、Caseタグ、件名、本文キーワードなどに応じて、LLMへの追加指示を登録できるようにする。

例:

```text
学生からのメールでは、次に学生が行うべきことと自分が行うべきことを分けて書く。
事務メールでは、締切と提出先を強調する。
返信文面は簡潔にし、今後の対応を中心に書く。
査読依頼では、専門分野との合致度を表示する。
```

## 21.2 適用対象

- mail_importance_classification
- mail_summary_ja
- reply_draft_generation
- new_mail_draft_generation
- mail_task_suggestion
- case_context_update
- contact_context_update

## 21.3 保存先

`llm_instruction_rules` 相当のテーブルを追加してもよい。  
DB設計書に未追加の場合、後続migrationで追加する。

主なカラム案:

```text
instruction_id
name
condition_json
instruction_text
function_types_json
priority_order
is_enabled
created_at
updated_at
```

## 21.4 優先順位

複数の追加指示が一致した場合、priority_order順に適用する。

ただし、衝突する指示がある場合は、より具体的な条件を優先する。

---

# 22. 出力schema管理

## 22.1 schemaはprompt_versionsに保存

各function_typeごとに、出力JSON schemaを `prompt_versions.output_schema_json` に保存する。

## 22.2 schema変更

schema変更時は prompt_version を上げる。

過去のllm_runsは古いschemaに基づくため、UI側でschema_versionを見て表示する。

## 22.3 schema検証

LLM出力は保存前にschema検証する。

不正時:

- retry_countを増やす
- retry promptで再実行
- 上限到達でfailed

---

# 23. LLM処理の実装優先度

本プロジェクトではMVPという用語は使わないが、実装順序上の優先度を定義する。

## Priority A

最初に必要。

- contact_registration_prefill
- mail_importance_classification
- mail_summary_ja
- mail_case_selection
- reply_draft_generation
- new_mail_draft_generation
- mail_task_suggestion

## Priority B

次に必要。

- calendar_candidate_extraction
- preparation_task_suggestion
- case_context_update
- contact_context_update
- mail_thread_summary
- reminder_mail_generation

## Priority C

後続。

- file_security_meta_classification
- file_summary
- subtask_suggestion
- handover_log_generation
- 高度な案件内RAG

---

# 24. テスト方針

## 24.1 LLM本体品質は固定しない

LLM出力の内容品質は完全には固定できない。

テスト対象は以下。

- JSONとしてvalidか
- schemaに合うか
- 必須フィールドがあるか
- enum違反がないか
- 不正時にリトライされるか
- user_*を上書きしないか
- llm_runsに履歴が残るか
- Cost Limit超過時にSystem Maintenance Taskが作られるか

## 24.2 mock LLM

テスト時はLLMレスポンスをmockする。

代表ケース:

- 正常JSON
- JSON不正
- enum違反
- 必須フィールド欠落
- 長文入力
- Pending中
- Cost Limit超過
- provider error
- 微妙だがschema上は正常な出力

## 24.3 回帰テスト

プロンプト変更時には、過去メールのサンプルに対して以下を確認する。

- High/Middle/Lowが極端に変化しないか
- Pending例外処理が壊れていないか
- Contact自動Fillが空欄ばかりにならないか
- 返信草案が指定トーンに従うか
- JSON schema違反が増えていないか

---

# 25. 未確定事項

以下は実装中に調整する。

- 実際のプロンプト本文
- 各function_typeのmodel選定
- temperature等の推論パラメータ
- 長文メールのtruncate方針
- HTMLメール本文の扱い
- 添付ファイル本文抽出の対応範囲
- Case Context更新頻度
- Contact Context更新頻度
- file_summaryの自動実行可否
- 引継ぎログのテンプレート
- llm_instruction_rulesのDB詳細

---

# 26. 最重要ルール

```text
1. LLMはユーザー確定値を上書きしない。
2. Pending中はContact登録自動Fill以外のLLM処理を止める。
3. Lowは自動要約・自動Case判定しない。
4. HighになったらGmailスター付与External Operationを作る。
5. LLMはPinned/Skip/Pendingを重要度として出力しない。
6. 返信草案・新規メール草案は必ずユーザー確認後に送信する。
7. JSON不正はリトライする。
8. 人間が見て微妙な出力は失敗扱いしない。
9. LLM入力全文はllm_runsに保存しない。
10. プロンプト改善に必要な診断情報は保存する。
11. Cost Limit超過時はSystem Maintenance CaseにTaskを作る。
12. 高機密ファイル本文は自動でLLMに渡さない。
```
