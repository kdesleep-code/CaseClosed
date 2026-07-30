import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { t } from './i18n'
import { AppLink, TopNav } from './navigation'
import { listContacts } from './phase3Api'
import type { Contact } from './phase3Api'
import {
  createCaseAutoAssignRule,
  deleteCaseAutoAssignRule,
  listAllCaseAutoAssignRules,
  listCases,
} from './phase7Api'
import type { CaseAutoAssignRule, CaseItem } from './phase7Api'

function describeError(error: unknown) {
  return error instanceof Error ? error.message : t('cases.autoRules.requestFailed')
}

function normalizeEmail(value: string) {
  return value.trim().toLowerCase()
}

export default function CaseAutoAssignRulesView() {
  const [cases, setCases] = useState<CaseItem[]>([])
  const [contacts, setContacts] = useState<Contact[]>([])
  const [rules, setRules] = useState<CaseAutoAssignRule[]>([])
  const [selectedCaseId, setSelectedCaseId] = useState('')
  const [ruleType, setRuleType] = useState<'contact' | 'email'>('contact')
  const [target, setTarget] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    let isMounted = true
    Promise.all([listCases('all'), listContacts(), listAllCaseAutoAssignRules()])
      .then(([nextCases, nextContacts, nextRules]) => {
        if (!isMounted) return
        const sortedCases = nextCases.toSorted((a, b) => a.name.localeCompare(b.name))
        setCases(sortedCases)
        setContacts(nextContacts.toSorted((a, b) => a.display_name.localeCompare(b.display_name)))
        setRules(nextRules)
        setSelectedCaseId(sortedCases[0]?.id ?? '')
      })
      .catch((requestError) => {
        if (isMounted) setError(describeError(requestError))
      })
      .finally(() => {
        if (isMounted) setIsLoading(false)
      })
    return () => { isMounted = false }
  }, [])

  const contactsById = useMemo(
    () => new Map(contacts.map((contact) => [contact.id, contact])),
    [contacts],
  )
  const contactsByEmail = useMemo(() => {
    const index = new Map<string, Contact>()
    contacts.forEach((contact) => contact.email_addresses.forEach((email) => {
      index.set(normalizeEmail(email.email_address), contact)
    }))
    return index
  }, [contacts])
  const emailSuggestions = useMemo(
    () => contacts.flatMap((contact) => contact.email_addresses.map((email) => ({
      email: email.email_address,
      label: `${email.email_address} — ${contact.display_name}`,
    }))),
    [contacts],
  )
  const normalizedQuery = searchQuery.trim().toLowerCase()
  const visibleRules = rules.filter((rule) => {
    if (normalizedQuery === '') return true
    const contact = rule.contact_id !== null
      ? contactsById.get(rule.contact_id)
      : contactsByEmail.get(normalizeEmail(rule.rule_value))
    return [
      rule.case_name,
      rule.display_value,
      contact?.display_name ?? '',
      ...(contact?.email_addresses.map((email) => email.email_address) ?? []),
    ].join(' ').toLowerCase().includes(normalizedQuery)
  })

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const nextTarget = target.trim()
    if (selectedCaseId === '' || nextTarget === '' || isSaving) return
    setIsSaving(true)
    setError(null)
    setNotice(null)
    try {
      const rule = await createCaseAutoAssignRule(
        selectedCaseId,
        ruleType === 'contact' ? { contact_id: nextTarget } : { sender_email: nextTarget },
      )
      setRules((current) => [...current, rule].toSorted((a, b) => (
        a.case_name.localeCompare(b.case_name) || b.created_at.localeCompare(a.created_at)
      )))
      setTarget('')
      setNotice(t('cases.mail.autoRule.created', { target: rule.display_value }))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsSaving(false)
    }
  }

  async function handleDelete(rule: CaseAutoAssignRule) {
    if (isSaving) return
    setIsSaving(true)
    setError(null)
    setNotice(null)
    try {
      await deleteCaseAutoAssignRule(rule.case_id, rule.id)
      setRules((current) => current.filter((item) => item.id !== rule.id))
      setNotice(t('cases.mail.autoRule.deleted', { target: rule.display_value }))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <main className="app-shell">
      <div className="case-shell">
        <header className="maintenance-header">
          <div><p>{t('app.name')}</p><h1>{t('cases.autoRules.heading')}</h1></div>
          <TopNav
            ariaLabelKey="cases.navigation"
            items={[
              { href: '/', labelKey: 'top.heading' },
              { href: '/mail', labelKey: 'nav.mail' },
              { href: '/contacts', labelKey: 'nav.contacts' },
              { href: '/cases', labelKey: 'nav.cases' },
            ]}
          />
        </header>

        {error !== null && <div className="mail-feedback"><p role="alert">{error}</p></div>}
        {notice !== null && <div className="mail-feedback"><p>{notice}</p></div>}

        <section className="case-mail-auto-rule-panel case-auto-rules-create-panel">
          <div className="section-heading"><div>
            <h2>{t('cases.autoRules.createHeading')}</h2>
            <p>{t('cases.mail.autoRule.body')}</p>
          </div></div>
          <form className="case-auto-rules-form" onSubmit={handleCreate}>
            <label>
              <span>{t('cases.autoRules.case')}</span>
              <select className="ui-control" disabled={isSaving} onChange={(event) => setSelectedCaseId(event.target.value)} value={selectedCaseId}>
                {cases.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
              </select>
            </label>
            <label>
              <span>{t('cases.mail.autoRule.ruleType')}</span>
              <select
                className="ui-control"
                disabled={isSaving}
                onChange={(event) => {
                  setRuleType(event.target.value as 'contact' | 'email')
                  setTarget('')
                }}
                value={ruleType}
              >
                <option value="contact">{t('cases.mail.autoRule.typeContact')}</option>
                <option value="email">{t('cases.mail.autoRule.typeEmail')}</option>
              </select>
            </label>
            {ruleType === 'contact' ? (
              <label>
                <span>{t('cases.autoRules.contact')}</span>
                <select className="ui-control" disabled={isSaving} onChange={(event) => setTarget(event.target.value)} value={target}>
                  <option value="">{t('cases.autoRules.selectContact')}</option>
                  {contacts.map((contact) => <option key={contact.id} value={contact.id}>{contact.display_name}</option>)}
                </select>
              </label>
            ) : (
              <label>
                <span>{t('cases.autoRules.email')}</span>
                <input
                  className="ui-control"
                  disabled={isSaving}
                  list="case-auto-rule-email-options"
                  onChange={(event) => setTarget(event.target.value)}
                  placeholder={t('cases.mail.autoRule.emailPlaceholder')}
                  type="email"
                  value={target}
                />
                <datalist id="case-auto-rule-email-options">
                  {emailSuggestions.map((item) => <option key={item.email} value={item.email}>{item.label}</option>)}
                </datalist>
              </label>
            )}
            <button className={`ui-button ui-button--primary button-loading-dot${isSaving ? ' is-loading' : ''}`} disabled={isSaving || selectedCaseId === '' || target.trim() === ''} type="submit">
              {t('cases.mail.autoRule.add')}
            </button>
          </form>
        </section>

        <section className="case-auto-rules-list-panel">
          <div className="section-heading case-auto-rules-list-heading">
            <div><h2>{t('cases.autoRules.listHeading')}</h2><p>{t('cases.autoRules.count', { count: visibleRules.length })}</p></div>
            <input className="ui-control" aria-label={t('cases.autoRules.search')} onChange={(event) => setSearchQuery(event.target.value)} placeholder={t('cases.autoRules.search')} type="search" value={searchQuery} />
          </div>
          {isLoading ? (
            <p className="case-mail-auto-rule-empty">{t('common.loading')}</p>
          ) : visibleRules.length === 0 ? (
            <p className="case-mail-auto-rule-empty">{t('cases.mail.autoRule.empty')}</p>
          ) : (
            <div className="case-auto-rules-table">
              <div className="case-auto-rules-table-header" aria-hidden="true">
                <span>{t('cases.autoRules.case')}</span>
                <span>{t('cases.mail.autoRule.ruleType')}</span>
                <span>{t('cases.autoRules.email')}</span>
                <span>{t('cases.autoRules.contact')}</span>
                <span />
              </div>
              {visibleRules.map((rule) => {
                const contact = rule.contact_id !== null
                  ? contactsById.get(rule.contact_id)
                  : contactsByEmail.get(normalizeEmail(rule.rule_value))
                const contactEmails = contact?.email_addresses
                  .filter((email) => email.status !== 'deleted')
                  .map((email) => email.email_address) ?? []
                return (
                  <div className="case-auto-rules-row" key={rule.id}>
                    <AppLink href={`/cases/${encodeURIComponent(rule.case_id)}`}>{rule.case_name}</AppLink>
                    <span className="case-auto-rule-type">{rule.rule_type === 'sender_contact' ? t('cases.mail.autoRule.typeContact') : t('cases.mail.autoRule.typeEmail')}</span>
                    <div>{rule.rule_type === 'sender_email' ? <AppLink href={`/mail?q=${encodeURIComponent(rule.rule_value)}`}>{rule.rule_value}</AppLink> : <span>{contactEmails.join(', ') || t('common.none')}</span>}</div>
                    <div>{contact !== undefined ? <AppLink href={`/contacts?contact_id=${encodeURIComponent(contact.id)}`}>{contact.display_name}</AppLink> : <span>{t('common.none')}</span>}</div>
                    <button className="ui-button ui-button--compact ui-button--danger" disabled={isSaving} onClick={() => void handleDelete(rule)} type="button">{t('cases.mail.autoRule.delete')}</button>
                  </div>
                )
              })}
            </div>
          )}
        </section>
      </div>
    </main>
  )
}
