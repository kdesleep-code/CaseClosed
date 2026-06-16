# CaseClosed テスト戦略・運用方針

Version: 0.1  
作成日: 2026-05-22  
対象: 個人用案件管理Webアプリ CaseClosed

---

## 0. 本書の位置づけ

本書は、CaseClosed開発におけるテスト作成・保守・レビュー方針を定義する。

CaseClosedでは、設計書を仕様の正本とし、実装前に設計書からテストを作成する。  
これにより、Codex / LLM coding agent による実装が、設計思想から逸脱することを防ぐ。

---

# 1. 基本方針

## 1.1 Design-first / Test-first

開発の基本順序は以下とする。

```text
1. 設計書を読む
2. 設計書からテストケースを作る
3. テストが失敗することを確認する
4. 実装する
5. テストを通す
6. ユーザーが動作・画面を確認する
7. UIや操作感は必要に応じて修正する
```

## 1.2 テストは仕様のガードレール

テストは、単に実装が動くかを確認するものではない。  
CaseClosedの中核仕様を守るためのガードレールである。

特に以下を守る。

- Case削除は通常導線に出さず、誤作成Case向けの例外Deleteだけを許可する
- Task削除は論理削除
- Email Address単独Skipを作らない
- Contact未登録FromはPending
- Pending中は重要度判定・Case判定・自動要約を止める
- LLMはユーザー確定値を上書きしない
- Gmail送信・Calendar作成はexternal_operations経由
- unknown external operationは自動再実行しない
- LLM入力全文をllm_runsに保存しない
- ProcessedとSkipを混同しない
- CaseはClosedとArchiveを分ける

## 1.3 テストは原則削除・弱体化しない

一度作成したテストは、原則として削除しない。  
テストを弱める変更もしない。

ただし、以下の場合は例外的に修正を検討する。

- 設計書の仕様そのものが変更された
- 外部API・ライブラリ・フレームワークの仕様変更により、テスト実装が現実と合わなくなった
- テストが実装詳細に依存しすぎており、仕様を検証していない
- 非決定的で安定しないテストになっている
- セキュリティ上、テストデータやfixtureの扱いに問題がある

その場合でも、Codexが勝手にテストを削除・修正してはならない。  
必ずユーザーに確認する。

## 1.4 テスト修正時のルール

テスト修正が必要な場合、Codexは以下を提示する。

```text
1. どのテストを修正したいか
2. なぜ修正が必要か
3. 設計書のどの仕様に関係するか
4. 修正前のテストが何を保証していたか
5. 修正後も何を保証するか
6. 代替テストが必要か
```

ユーザー承認後に修正する。

---

# 2. テスト種別

## 2.1 Unit Test

対象:

- 状態遷移
- effective_importance計算
- Pending判定
- Case Closed条件
- Task Completed条件
- Task論理削除
- LLM出力schema validation
- input_hash生成
- idempotency_key生成
- user_*保護
- base_version競合

## 2.2 Integration Test

対象:

- Gmail同期 → Pending判定
- Contact解決 → 重要度判定Job発火
- High/Middle → 要約・Case判定Job発火
- Low → 要約・Case判定なし
- メールからTask作成 → processed
- Draft送信 → external_operation作成
- Calendar予定作成 → external_operation作成
- unknown external_operation → System Maintenance Task作成
- stale job → System Maintenance Task作成

## 2.3 API Test

対象:

- 各APIの正常系
- 権限・セッション切れ
- CSRF
- 不正入力
- DELETE禁止
- optimistic_state
- write_request作成
- external_operation作成

## 2.4 Worker Test

対象:

- Job状態遷移
- retry_count
- stale検出
- LLM JSON不正リトライ
- Cost Limit
- Worker heartbeat
- External Operation unknown処理

## 2.5 UI Smoke Test

対象:

- Loginできる
- Topが表示される
- Mail一覧が表示される
- 日別メール一覧が表示される
- 3タブが存在する
- Pending Contact画面が表示される
- Case詳細に関連メール集合が表示される
- Task作成できる
- Draft編集できる

UIの細かいレイアウトは頻繁に変わるため、初期段階ではUIテストを細かくしすぎない。

## 2.6 Golden / Fixture Test

まとめーる風メール一覧やLLM出力schemaについて、固定fixtureを使う。

ただし、LLM本文品質の正解固定はしない。

---

# 3. Phase別テスト方針

## Phase 0

- `/health` が200を返す
- DB接続できる
- migration実行できる
- pytestが動く

## Phase 1

必須テスト:

- ログイン成功
- ログイン失敗カウント
- 5回失敗でロック
- 24時間後にセッション失効
- Inbox Caseが作られる
- システムメンテナンスCaseが作られる
- System Caseを削除できない
- Case削除は通常導線に出さず、誤作成向けの例外Deleteだけを許可する

## Phase 2

必須テスト:

- write_requestがSingle DB Writer経由でappliedになる
- user_*をLLM/Systemが上書きしようとするとdiscardedになる
- Job pending -> running -> succeeded
- runningのまま一定時間経過でstale
- stale jobでSystem Maintenance Task作成
- external_operation unknownで自動再実行されない

## Phase 3

必須テスト:

- Contact未登録FromはPending
- Contact登録でPending解除
- Contact skippedでSkip扱い
- Email Address単独Skip状態が存在しない
- From単独Skipルールを作成できない
- contact_registration_prefillはPending中でも実行可能

## Phase 4

必須テスト:

- Gmail本文をDB保存
- 読み込み日別表示
- 未処理メール一覧
- 受け取ったメール / 対応済み / Skipタブ
- 全メール検索
- initial_is_starredからexternal_importance
- 既読メールのスター解除を再監視しない
- Pending中は重要度判定Jobを発火しない

## Phase 5以降

各Phaseのロードマップに従い、実装前にテストを追加する。

---

# 4. Codexへのテスト作成依頼テンプレート

## 4.1 実装前テスト作成

```text
CaseClosedの設計書群を読み、[対象Phase/機能] のテストを先に作成してください。

まだ実装は変更しないでください。

対象設計書:
- ...

作成するテスト:
- unit test
- integration test
- API test

重要:
- 既存テストは削除・弱体化しない
- 設計書と矛盾するテストが必要に見える場合は、実装せず質問してください
- 外部APIはmockしてください
- LLMはmockしてください

完了条件:
- 新規テストが追加される
- 現状実装では失敗するテストがあってよい
- どの設計仕様を守るテストかコメントまたはテスト名で分かる
```

## 4.2 実装依頼

```text
追加済みテストを通すように、[対象機能] を実装してください。

制約:
- 既存テストを削除・変更しない
- テスト変更が必要な場合は先に理由を説明し、ユーザー確認を取る
- 設計書と矛盾する実装をしない
```

## 4.3 テスト修正相談

```text
以下のテスト修正が必要だと考えています。

対象テスト:
- ...

理由:
- ...

関連設計書:
- ...

現在のテストが保証している仕様:
- ...

修正後も保証する仕様:
- ...

この修正を行ってよいか確認してください。
```

---

# 5. レビュー時のテスト確認ポイント

ユーザーはPR / 差分確認時に以下を見る。

```text
□ 先にテストが追加されているか
□ テスト名から仕様が分かるか
□ 既存テストが削除されていないか
□ 既存テストが弱くなっていないか
□ 外部APIがmockされているか
□ LLMがmockされているか
□ テストがDB実装詳細に寄りすぎていないか
□ 設計書の重要制約を守っているか
```

特に確認する制約:

```text
□ Case削除の通常導線なし / 誤作成向け例外Deleteのみ
□ Task論理削除
□ Email Address単独Skipなし
□ Pending中のLLM停止
□ external_operations経由
□ unknown自動再実行なし
□ LLM入力全文保存なし
□ user_*保護
```

---

# 6. テストを変えてよい条件

以下の場合のみ、テスト変更を検討する。

## 6.1 設計変更

ユーザーが仕様を変更した場合。

例:

```text
Case Closed条件を変える
Pending条件を変える
メール一覧タブを変える
```

この場合、先に設計書を更新し、その後テストを更新する。

## 6.2 環境変化

例:

- ライブラリ更新でAPIが変わった
- DB migration toolを変更した
- FastAPI/SQLAlchemyの仕様変更
- Python version変更
- Google API mock方式変更

この場合も、ユーザー確認後にテストを更新する。

## 6.3 テスト品質問題

例:

- flaky
- 実装詳細に依存しすぎ
- 仕様ではなく偶然の挙動を固定している
- 遅すぎる
- mockが不自然

この場合、同じ仕様をより良く検証するテストへ置き換える。

---

# 7. テスト削除禁止の例外

原則削除禁止だが、以下は例外。

- 同じ仕様をより上位のテストで完全に保証している
- 設計変更により仕様が消えた
- テスト自体が誤仕様を固定していた
- セキュリティ上問題のあるfixtureを含む

ただし、削除前にユーザー確認を必須とする。

---

# 8. Phase4完了までの推奨進行

ユーザー方針:

```text
Phase 1〜2もしっかり実装する。
当面はPhase 4完了を目指す。
```

Phase4完了時点で期待する状態:

- 安全にログインできる
- System Caseが存在する
- Job / Write Request / External Operation基盤がある
- Pending Contact処理ができる
- Gmail同期できる
- Gmail本文をDB保存できる
- まとめーる風メール一覧がある
- 読み込み日別表示がある
- 未処理メール一覧がある
- 3タブ表示がある
- 全メール検索ができる
- Pending中はLLM自動処理が止まる

Phase4完了までは、LLM重要度判定やCase判定は本格化しなくてよい。  
ただし、それらが後から入るためのテーブル・Job・状態遷移の土台は壊さない。

---

# 9. 最重要ルール

```text
1. 設計書を読んでからテストを作る。
2. 実装より先にテストを作る。
3. テストは原則削除・弱体化しない。
4. テスト修正が必要ならユーザーに確認する。
5. 外部APIとLLMはmockする。
6. UI細部より、状態遷移・DB・外部副作用・セキュリティを強くテストする。
7. Phase4完了までは土台とメール入口を重視する。
```
