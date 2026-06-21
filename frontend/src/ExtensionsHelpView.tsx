import { t } from './i18n'
import { TopNav } from './navigation'

const manifestExample = `{
  "slug": "information-literacy-report-1-1",
  "name": "Information Literacy Report 1-1",
  "description": "Grade mail reports for a Case.",
  "command": ["python", "app.py"],
  "url_path": "/",
  "tags": ["grading", "mail"]
}`

export default function ExtensionsHelpView() {
  return (
    <main className="app-shell">
      <div className="maintenance-shell extensions-shell">
        <header className="maintenance-header">
          <div>
            <p>{t('app.name')}</p>
            <h1>{t('extensions.guideHeading')}</h1>
          </div>
          <TopNav
            ariaLabelKey="extensions.navigation"
            items={[
              { href: '/', labelKey: 'top.heading' },
              { href: '/extensions', labelKey: 'extensions.heading' },
              { href: '/external-tools', labelKey: 'nav.externalTools' },
              { href: '/settings', labelKey: 'nav.settings' },
            ]}
          />
        </header>

        <section className="maintenance-panel-surface extensions-panel">
          <div className="maintenance-panel extensions-guide">
            <section className="extension-guide-card">
              <h2>Extensionとは</h2>
              <p>
                CaseClosed本体には入れにくい、自動採点・PDF生成・専用データ変換のようなCase特化処理を、
                独立した小さなWebアプリとして起動する仕組みです。Extensionは別プロセスで動き、
                CaseClosedは登録、起動、停止、Case情報への限定アクセスだけを担当します。
              </p>
            </section>

            <section className="extension-guide-card">
              <h2>作り方</h2>
              <ol>
                <li>任意のフォルダにExtension本体を作成します。</li>
                <li>HTTPで画面を出せる小さなサーバーを用意します。</li>
                <li>起動時に渡される環境変数からポート、Case ID、API URL、Extension tokenを読みます。</li>
                <li>必要に応じてExtension APIを呼び、Case情報やCase内ファイルを取得します。</li>
              </ol>
              <dl className="extension-guide-definition-list">
                <div>
                  <dt>CASECLOSED_EXTENSION_PORT</dt>
                  <dd>Extensionが待ち受けるポートです。</dd>
                </div>
                <div>
                  <dt>CASECLOSED_API_BASE_URL</dt>
                  <dd>CaseClosed backend APIのURLです。</dd>
                </div>
                <div>
                  <dt>CASECLOSED_EXTENSION_TOKEN</dt>
                  <dd>Extension APIへアクセスするためのBearer tokenです。ログや画面に表示しないでください。</dd>
                </div>
                <div>
                  <dt>CASECLOSED_CASE_ID</dt>
                  <dd>起動時に選択されたCase IDです。Caseなし起動では空文字です。</dd>
                </div>
              </dl>
            </section>

            <section className="extension-guide-card">
              <h2>Manifest</h2>
              <p>
                Extensionフォルダにmanifest JSONを置きます。管理ページではmanifest pathを指定して登録します。
              </p>
              <pre><code>{manifestExample}</code></pre>
              <dl className="extension-guide-definition-list">
                <div>
                  <dt>slug</dt>
                  <dd>Extensionの安定IDです。同じslugを再登録すると定義が更新されます。</dd>
                </div>
                <div>
                  <dt>command</dt>
                  <dd>Extensionフォルダをcwdとして実行されるコマンドです。</dd>
                </div>
                <div>
                  <dt>url_path</dt>
                  <dd>起動後にOpenボタンで開くパスです。通常は / で十分です。</dd>
                </div>
              </dl>
            </section>

            <section className="extension-guide-card">
              <h2>登録と利用</h2>
              <ol>
                <li>ExtensionsページでRegisterを押します。</li>
                <li>manifest pathに例: extensions/user-extensions/information-literacy-report-1-1/caseclosed-extension.json を入力します。</li>
                <li>登録後、対象Caseとidle timeoutを選んでStartを押します。</li>
                <li>Extensionの画面が開いたら、必要な処理を実行します。</li>
                <li>作業終了後はStopを押します。操作が長時間なければ自動停止します。</li>
              </ol>
            </section>

            <section className="extension-guide-card">
              <h2>Extension API</h2>
              <p>
                Extension側から呼ぶAPIです。Authorization: Bearer &lt;CASECLOSED_EXTENSION_TOKEN&gt; を付与します。
              </p>
              <div className="extension-guide-api-list">
                <article>
                  <h3>GET /api/v1/extension-api/context</h3>
                  <p>起動コンテキスト、Case ID、instance IDを取得します。この読み取り自体は監査ログ対象外です。</p>
                </article>
                <article>
                  <h3>GET /api/v1/extension-api/case</h3>
                  <p>起動時に選択されたCaseの概要を取得します。利用はaudit logに記録されます。</p>
                </article>
                <article>
                  <h3>GET /api/v1/extension-api/case/files</h3>
                  <p>Caseに紐づくファイル一覧を取得します。利用はaudit logに記録されます。</p>
                </article>
                <article>
                  <h3>POST /api/v1/extension-api/case/files</h3>
                  <p>処理結果ファイルをCaseのStorageに保存します。filename、content_type、data_base64を送ります。</p>
                </article>
                <article>
                  <h3>GET /api/v1/extension-api/mails</h3>
                  <p>Caseに紐づくメールを、q、from_address、subject、received_from、received_to、limitなどで検索します。include_body=trueで本文も取得できます。</p>
                </article>
              </div>
            </section>

            <section className="extension-guide-card">
              <h2>ログと注意点</h2>
              <ul>
                <li>登録、起動、停止、自動停止、Case情報取得、ファイル一覧取得、ファイル保存はaudit logに残ります。</li>
                <li>Extension tokenは秘匿情報です。画面・ファイル・ログへ出力しないでください。</li>
                <li>ExtensionはCaseClosed本体とは別プロセスなので、失敗しても本体を巻き込みにくい設計です。</li>
                <li>現状のOpen URLはローカル起動を前提にしています。別PCからの利用はExtensionの待受ホスト設計を別途詰める必要があります。</li>
              </ul>
            </section>
          </div>
        </section>
      </div>
    </main>
  )
}
