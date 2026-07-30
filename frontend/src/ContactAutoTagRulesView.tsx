import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { listContactAutoTagRules, saveContactAutoTagRules } from './phase3Api'
import type { ContactAutoTagRule } from './phase3Api'
import { t } from './i18n'
import { TopNav } from './navigation'

export default function ContactAutoTagRulesView() {
  const [rules, setRules] = useState<ContactAutoTagRule[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    listContactAutoTagRules().then(setRules).catch((reason) => setError(reason instanceof Error ? reason.message : t('settings.requestFailed')))
  }, [])

  function updateRule(index: number, patch: Partial<ContactAutoTagRule>) {
    setRules((current) => current?.map((rule, ruleIndex) => ruleIndex === index ? { ...rule, ...patch } : rule) ?? null)
  }

  async function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (rules === null) return
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      setRules(await saveContactAutoTagRules(rules))
      setNotice(t('settings.saved'))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t('settings.requestFailed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="app-shell">
      <div className="maintenance-shell contacts-auto-tag-shell">
        <header className="maintenance-header">
          <div><p>{t('app.name')}</p><h1>{t('settings.contacts.autoTags.heading')}</h1></div>
          <TopNav ariaLabelKey="contacts.navLabel" items={[{ href: '/contacts', labelKey: 'contacts.heading' }, { href: '/', labelKey: 'top.heading' }, { href: '/mail', labelKey: 'nav.mail' }, { href: '/cases', labelKey: 'nav.cases' }]} />
        </header>
        {error && <p className="maintenance-error" role="alert">{error}</p>}
        {notice && <p className="contact-notice" role="status">{notice}</p>}
        <section className="maintenance-panel maintenance-section">
          <div className="section-heading"><div><h2>{t('settings.contacts.autoTags.heading')}</h2><p>{t('settings.contacts.autoTags.description')}</p></div></div>
          {rules === null ? <p>{t('maintenance.debug.loading')}</p> : (
            <form onSubmit={handleSave}>
              <div className="maintenance-table-wrap">
                <table className="contact-auto-tag-rules-table">
                  <thead><tr><th>{t('common.status')}</th><th>{t('settings.contacts.autoTags.label')}</th><th>{t('settings.contacts.autoTags.pattern')}</th><th>{t('settings.contacts.autoTags.template')}</th><th>{t('common.action')}</th></tr></thead>
                  <tbody>
                    {rules.map((rule, index) => (
                      <tr key={rule.id}>
                        <td><label className="checkbox-label"><input checked={rule.enabled} type="checkbox" onChange={(event) => updateRule(index, { enabled: event.target.checked })} /><span>{t('common.enabled')}</span></label></td>
                        <td><input aria-label={`${t('settings.contacts.autoTags.label')} ${index + 1}`} className="ui-control" required value={rule.label} onChange={(event) => updateRule(index, { label: event.target.value })} /></td>
                        <td><input aria-label={`${t('settings.contacts.autoTags.pattern')} ${index + 1}`} className="ui-control contact-auto-tag-pattern-input" required value={rule.email_pattern} onChange={(event) => updateRule(index, { email_pattern: event.target.value })} /></td>
                        <td><input aria-label={`${t('settings.contacts.autoTags.template')} ${index + 1}`} className="ui-control" required value={rule.tag_template} onChange={(event) => updateRule(index, { tag_template: event.target.value })} /></td>
                        <td><button className="ui-button ui-button--compact ui-button--danger" type="button" onClick={() => setRules(rules.filter((_, ruleIndex) => ruleIndex !== index))}>{t('common.delete')}</button></td>
                      </tr>
                    ))}
                    {rules.length === 0 && <tr><td colSpan={5}>{t('settings.contacts.autoTags.empty')}</td></tr>}
                  </tbody>
                </table>
              </div>
              <div className="resolution-actions contact-auto-tag-actions"><button className="ui-button" type="button" onClick={() => setRules([...rules, { id: `rule-${Date.now()}`, label: '', email_pattern: '', tag_template: '', enabled: true }])}>{t('settings.contacts.autoTags.add')}</button><button className={`ui-button ui-button--primary button-loading-dot${busy ? ' is-loading' : ''}`} disabled={busy} type="submit">{t('common.save')}</button></div>
              <p>{t('settings.contacts.autoTags.note')}</p>
            </form>
          )}
        </section>
      </div>
    </main>
  )
}
