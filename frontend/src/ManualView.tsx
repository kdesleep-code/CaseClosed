import { t } from './i18n'
import { AppLink, TopNav } from './navigation'

const manualSections = [
  {
    title: 'Today / Tomorrow',
    body: 'その日見るべきCalendar、未処理Mail、Started Taskをまとめて確認するページです。朝は一日全体、日中は現在時刻以降の流れを中心に見ます。',
    links: [
      { href: '/today', label: 'Today' },
      { href: '/tomorrow', label: 'Tomorrow' },
    ],
  },
  {
    title: 'Mail',
    body: '受信メールの確認、返信作成、CaseやTask、Calendar Eventへの変換を行います。Follow Up候補は右ガジェットから確認します。',
    links: [
      { href: '/mail', label: 'Mail' },
      { href: '/follow-ups', label: 'Follow Up' },
    ],
  },
  {
    title: 'Cases',
    body: '進行中の案件を中心に、関連Task、Calendar Event、Storage、External Tools、Extensionsへの入口をまとめます。',
    links: [{ href: '/cases', label: 'Cases' }],
  },
  {
    title: 'Tasks',
    body: 'Start DateとDue Dateを基準に作業を管理します。Search and maskではGenre順のタブで絞り込みできます。',
    links: [{ href: '/tasks', label: 'Tasks' }],
  },
  {
    title: 'Calendar',
    body: 'Google Calendar同期済みイベント、Case/Task連携イベント、Academic Calendar Repeatを扱います。授業系の繰り返しはAcademic Calendar設定を参照します。',
    links: [
      { href: '/calendar', label: 'Calendar' },
      { href: '/academic-calendar', label: 'Academic Calendar' },
    ],
  },
  {
    title: 'Contacts',
    body: 'Person、Mailing List、Serviceを管理します。Serviceにはメールアドレスの部分一致パターンを設定できます。',
    links: [{ href: '/contacts', label: 'Contacts' }],
  },
  {
    title: 'Storage',
    body: 'CaseやTaskに紐づくファイルを管理します。Extensionが生成したファイルもここから確認・リネームできます。',
    links: [{ href: '/files', label: 'Storage' }],
  },
  {
    title: 'Extensions / External Tools',
    body: 'CaseClosed本体から独立した自動化ツールや外部Webリンクを管理します。CaseのToolsから起動用URLを登録できます。',
    links: [
      { href: '/extensions', label: 'Extensions' },
      { href: '/external-tools', label: 'External Tools' },
    ],
  },
  {
    title: 'Logs / Settings / Maintenance',
    body: 'Logsは履歴検索、Settingsは常用設定、Maintenanceは監視と手動確認が必要な項目の処理に使います。',
    links: [
      { href: '/logs', label: 'Logs' },
      { href: '/settings', label: 'Settings' },
      { href: '/maintenance', label: 'Maintenance' },
    ],
  },
]

export default function ManualView() {
  return (
    <main className="maintenance-shell manual-shell">
      <header className="maintenance-hero">
        <div>
          <p>{t('app.name')}</p>
          <h1>{t('manual.heading')}</h1>
        </div>
        <TopNav
          ariaLabelKey="manual.navigation"
          items={[
            { href: '/', labelKey: 'top.heading' },
            { href: '/settings', labelKey: 'nav.settings' },
            { href: '/maintenance', labelKey: 'nav.maintenance' },
          ]}
        />
      </header>

      <section className="maintenance-panel-surface manual-panel">
        <div className="maintenance-panel manual-main">
          <header className="manual-intro">
            <h2>{t('manual.overview')}</h2>
            <p>{t('manual.summary')}</p>
          </header>
          <div className="manual-grid">
            {manualSections.map((section) => (
              <article className="manual-card" key={section.title}>
                <h3>{section.title}</h3>
                <p>{section.body}</p>
                <div>
                  {section.links.map((link) => (
                    <AppLink href={link.href} key={link.href}>
                      {link.label}
                    </AppLink>
                  ))}
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>
    </main>
  )
}
