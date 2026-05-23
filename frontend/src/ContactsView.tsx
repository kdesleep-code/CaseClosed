import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import {
  addContactEmailAddress,
  activateContactEmailAddress,
  createContact,
  deleteContactEmailAddress,
  generateContactPrefill,
  listContacts,
  listUnresolvedFromAddresses,
  moveContactEmailAddress,
  setContactPrimaryEmailAddress,
  updateContact,
} from './phase3Api'
import type { Contact, UnresolvedFromAddress } from './phase3Api'
import { t } from './i18n'

type ContactsMode = 'list' | 'pending'
type StatusFilter = 'all' | 'active' | 'skipped' | 'archived'
type CustomContactTab = {
  id: string
  label: string
  expression: string
}

const maxCustomTabs = 6
const maxCustomTabNameLength = 12
const defaultContactAvatarUrl = new URL(
  './assets/default-contact-avatar.svg',
  import.meta.url,
).href

function describeError(error: unknown) {
  return error instanceof Error ? error.message : t('contacts.requestFailed')
}

function primaryEmail(contact: Contact) {
  return (
    contact.email_addresses.find(
      (emailAddress) =>
        emailAddress.is_primary && (emailAddress.status ?? 'active') === 'active',
    ) ??
    contact.email_addresses.find(
      (emailAddress) => (emailAddress.status ?? 'active') === 'active',
    ) ??
    contact.email_addresses[0] ??
    null
  )
}

function normalizeTag(value: string) {
  return value.trim().toLowerCase()
}

function customTabMatches(contact: Contact, expression: string) {
  const terms = expression
    .trim()
    .replace(/^\{|\}$/g, '')
    .split('&')
    .map((term) => term.trim())
    .filter(Boolean)
  const tags = new Set(contact.tags.map(normalizeTag))

  if (terms.length === 0) {
    return true
  }

  return terms.every((term) => {
    if (term.startsWith('!')) {
      return !tags.has(normalizeTag(term.slice(1)))
    }
    return tags.has(normalizeTag(term))
  })
}

function parseTags(value: string) {
  return value
    .split(',')
    .map((tag) => tag.trim())
    .filter(Boolean)
}

function shouldIgnoreContactCardClick(target: EventTarget | null) {
  return (
    target instanceof HTMLElement &&
    target.closest('a, button, input, label, select, textarea, .contact-detail-card') !==
      null
  )
}

function ContactsView({ mode }: { mode: ContactsMode }) {
  const [contacts, setContacts] = useState<Contact[]>([])
  const [unresolvedFromAddresses, setUnresolvedFromAddresses] = useState<
    UnresolvedFromAddress[]
  >([])
  const [pendingDisplayNames, setPendingDisplayNames] = useState<Record<string, string>>(
    {},
  )
  const [pendingExistingContactIds, setPendingExistingContactIds] = useState<
    Record<string, string>
  >({})
  const [displayName, setDisplayName] = useState('')
  const [emailAddress, setEmailAddress] = useState('')
  const [memo, setMemo] = useState('')
  const [status, setStatus] = useState<'active' | 'skipped'>('active')
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedTagFilter, setSelectedTagFilter] = useState<string | null>(null)
  const [sortMode, setSortMode] = useState<'name' | 'updated'>('name')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('active')
  const [customTabs, setCustomTabs] = useState<CustomContactTab[]>([])
  const [activeCustomTabId, setActiveCustomTabId] = useState<string | null>(null)
  const [isCustomTabEditorOpen, setIsCustomTabEditorOpen] = useState(false)
  const [customTabName, setCustomTabName] = useState('')
  const [customTabExpression, setCustomTabExpression] = useState('')
  const [selectedContactId, setSelectedContactId] = useState<string | null>(null)
  const [isContactDetailEditing, setIsContactDetailEditing] = useState(false)
  const [detailDisplayName, setDetailDisplayName] = useState('')
  const [detailMemo, setDetailMemo] = useState('')
  const [detailStatus, setDetailStatus] = useState<
    'active' | 'skipped' | 'archived'
  >('active')
  const [detailTags, setDetailTags] = useState('')
  const [newEmailAddress, setNewEmailAddress] = useState('')
  const [moveTargetContactIds, setMoveTargetContactIds] = useState<Record<string, string>>(
    {},
  )
  const [busyEmailAddress, setBusyEmailAddress] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  useEffect(() => {
    let isMounted = true

    const request = mode === 'pending'
      ? Promise.all([listUnresolvedFromAddresses(), listContacts()])
      : listContacts()

    request
      .then((items) => {
        if (!isMounted) {
          return
        }
        if (mode === 'pending') {
          const [pendingItems, contactItems] = items as [
            UnresolvedFromAddress[],
            Contact[],
          ]
          setUnresolvedFromAddresses(pendingItems)
          setContacts(contactItems)
        } else {
          setContacts(items as Contact[])
        }
      })
      .catch((requestError) => {
        if (isMounted) {
          setError(describeError(requestError))
        }
      })

    return () => {
      isMounted = false
    }
  }, [mode])

  async function handleCreateContact(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setNotice(null)
    setIsSubmitting(true)

    try {
      const createdContact = await createContact({
        display_name: displayName,
        memo,
        status,
        tags: [],
        email_addresses:
          emailAddress.trim() === ''
            ? []
            : [{ email_address: emailAddress, is_primary: true }],
      })
      setContacts((currentContacts) => [...currentContacts, createdContact])
      openContactDetail(createdContact)
      setDisplayName('')
      setEmailAddress('')
      setMemo('')
      setStatus('active')
      setIsCreateOpen(false)
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsSubmitting(false)
    }
  }

  async function handleGeneratePrefill(item: UnresolvedFromAddress) {
    setError(null)
    setNotice(null)
    setBusyEmailAddress(item.email_address)

    try {
      const response = await generateContactPrefill(
        item.email_address,
        item.latest_message_id,
      )
      setNotice(t('contacts.prefill.queued', { jobId: response.job_id }))
      setUnresolvedFromAddresses((currentItems) =>
        currentItems.map((currentItem) =>
          currentItem.email_address_id === item.email_address_id
            ? { ...currentItem, suggestion_status: 'running' }
            : currentItem,
        ),
      )
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setBusyEmailAddress(null)
    }
  }

  function pendingDisplayName(item: UnresolvedFromAddress) {
    return (
      pendingDisplayNames[item.email_address] ??
      item.suggestion?.suggested_display_name ??
      item.email_address.split('@')[0]
    )
  }

  function removePendingEmailAddress(emailAddress: string) {
    setUnresolvedFromAddresses((currentItems) =>
      currentItems.filter((item) => item.email_address !== emailAddress),
    )
    setPendingDisplayNames((currentNames) => {
      const nextNames = { ...currentNames }
      delete nextNames[emailAddress]
      return nextNames
    })
    setPendingExistingContactIds((currentIds) => {
      const nextIds = { ...currentIds }
      delete nextIds[emailAddress]
      return nextIds
    })
  }

  async function handleCreatePendingContact(
    item: UnresolvedFromAddress,
    status: 'active' | 'skipped',
  ) {
    const nextDisplayName = pendingDisplayName(item).trim()
    if (nextDisplayName === '') {
      return
    }

    setError(null)
    setNotice(null)
    setBusyEmailAddress(item.email_address)

    try {
      const createdContact = await createContact({
        display_name: nextDisplayName,
        memo: '',
        status,
        tags: [],
        email_addresses: [
          { email_address: item.email_address, is_primary: true },
        ],
      })
      setContacts((currentContacts) => [...currentContacts, createdContact])
      removePendingEmailAddress(item.email_address)
      setNotice(
        status === 'skipped' ? t('contacts.skippedCreated') : t('contacts.created'),
      )
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setBusyEmailAddress(null)
    }
  }

  async function handleAddPendingToExistingContact(item: UnresolvedFromAddress) {
    const contactId = pendingExistingContactIds[item.email_address]
    if (contactId === undefined || contactId === '') {
      return
    }

    setError(null)
    setNotice(null)
    setBusyEmailAddress(item.email_address)

    try {
      const updatedContact = await addContactEmailAddress(contactId, item.email_address)
      updateContactInState(updatedContact)
      removePendingEmailAddress(item.email_address)
      setNotice(t('contacts.addedToExisting'))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setBusyEmailAddress(null)
    }
  }

  function handleStatusTabClick(nextStatusFilter: StatusFilter) {
    setStatusFilter(nextStatusFilter)
    setActiveCustomTabId(null)
    setIsCustomTabEditorOpen(false)
  }

  function updateContactInState(updatedContact: Contact) {
    setContacts((currentContacts) =>
      currentContacts.map((contact) =>
        contact.id === updatedContact.id ? updatedContact : contact,
      ),
    )
  }

  function openContactDetail(contact: Contact) {
    setSelectedContactId(contact.id)
    setIsContactDetailEditing(false)
    setDetailDisplayName(contact.display_name)
    setDetailMemo(contact.memo ?? '')
    setDetailStatus(contact.status as 'active' | 'skipped' | 'archived')
    setDetailTags(contact.tags.join(', '))
    setNewEmailAddress('')
    setMoveTargetContactIds({})
  }

  function openContactDetailFromUser(contact: Contact) {
    setError(null)
    setNotice(null)
    openContactDetail(contact)
  }

  function beginContactDetailEdit(contact: Contact) {
    setError(null)
    setNotice(null)
    setDetailDisplayName(contact.display_name)
    setDetailMemo(contact.memo ?? '')
    setDetailStatus(contact.status as 'active' | 'skipped' | 'archived')
    setDetailTags(contact.tags.join(', '))
    setIsContactDetailEditing(true)
  }

  function closeContactDetail() {
    setError(null)
    setNotice(null)
    setSelectedContactId(null)
    setIsContactDetailEditing(false)
    setNewEmailAddress('')
  }

  async function handleUpdateContact(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const selectedContact = contacts.find((contact) => contact.id === selectedContactId)
    if (selectedContact === undefined) {
      return
    }

    setError(null)
    setNotice(null)
    setIsSubmitting(true)

    try {
      const updatedContact = await updateContact(selectedContact.id, {
        display_name: detailDisplayName,
        avatar_url: selectedContact.avatar_url,
        memo: detailMemo,
        status: detailStatus,
        tags: parseTags(detailTags),
      })
      updateContactInState(updatedContact)
      openContactDetail(updatedContact)
      setIsContactDetailEditing(false)
      setNotice(t('contacts.detail.updated'))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsSubmitting(false)
    }
  }

  async function handleAddEmailAddress(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const selectedContact = contacts.find((contact) => contact.id === selectedContactId)
    if (selectedContact === undefined || newEmailAddress.trim() === '') {
      return
    }

    setError(null)
    setNotice(null)
    setIsSubmitting(true)

    try {
      const updatedContact = await addContactEmailAddress(
        selectedContact.id,
        newEmailAddress,
      )
      updateContactInState(updatedContact)
      openContactDetail(updatedContact)
      setNotice(t('contacts.email.added'))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsSubmitting(false)
    }
  }

  async function handleSetPrimaryEmailAddress(emailAddressId: string) {
    const selectedContact = contacts.find((contact) => contact.id === selectedContactId)
    if (selectedContact === undefined) {
      return
    }

    setError(null)
    setNotice(null)
    setIsSubmitting(true)

    try {
      const updatedContact = await setContactPrimaryEmailAddress(
        selectedContact.id,
        emailAddressId,
      )
      updateContactInState(updatedContact)
      openContactDetail(updatedContact)
      setNotice(t('contacts.email.primaryUpdated'))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsSubmitting(false)
    }
  }

  async function handleDeleteEmailAddress(emailAddressId: string) {
    const selectedContact = contacts.find((contact) => contact.id === selectedContactId)
    if (selectedContact === undefined) {
      return
    }

    setError(null)
    setNotice(null)
    setIsSubmitting(true)

    try {
      const updatedContact = await deleteContactEmailAddress(
        selectedContact.id,
        emailAddressId,
      )
      updateContactInState(updatedContact)
      openContactDetail(updatedContact)
      const updatedEmailAddress = updatedContact.email_addresses.find(
        (emailAddress) => emailAddress.id === emailAddressId,
      )
      setNotice(
        updatedEmailAddress?.status === 'inactive'
          ? t('contacts.email.deactivated')
          : t('contacts.email.removed'),
      )
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsSubmitting(false)
    }
  }

  async function handleActivateEmailAddress(emailAddressId: string) {
    const selectedContact = contacts.find((contact) => contact.id === selectedContactId)
    if (selectedContact === undefined) {
      return
    }

    setError(null)
    setNotice(null)
    setIsSubmitting(true)

    try {
      const updatedContact = await activateContactEmailAddress(
        selectedContact.id,
        emailAddressId,
      )
      updateContactInState(updatedContact)
      openContactDetail(updatedContact)
      setNotice(t('contacts.email.activated'))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsSubmitting(false)
    }
  }

  async function handleMoveEmailAddress(emailAddressId: string) {
    const selectedContact = contacts.find((contact) => contact.id === selectedContactId)
    const targetContactId = moveTargetContactIds[emailAddressId]
    if (
      selectedContact === undefined ||
      targetContactId === undefined ||
      targetContactId === ''
    ) {
      return
    }

    setError(null)
    setNotice(null)
    setIsSubmitting(true)

    try {
      const response = await moveContactEmailAddress(
        selectedContact.id,
        emailAddressId,
        targetContactId,
      )
      setContacts((currentContacts) =>
        currentContacts.map((contact) => {
          if (contact.id === response.source_contact.id) {
            return response.source_contact
          }
          if (contact.id === response.target_contact.id) {
            return response.target_contact
          }
          return contact
        }),
      )
      openContactDetail(response.source_contact)
      setNotice(t('contacts.email.moved'))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsSubmitting(false)
    }
  }

  function handleAddCustomTab(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const label = (customTabName.trim() || customTabExpression.trim()).slice(
      0,
      maxCustomTabNameLength,
    )
    const expression = customTabExpression.trim()
    if (label === '' || expression === '') {
      return
    }

    const tab = {
      id: `custom_${Date.now()}_${customTabs.length}`,
      label,
      expression,
    }
    setCustomTabs((currentTabs) => [...currentTabs, tab])
    setActiveCustomTabId(tab.id)
    setStatusFilter('all')
    setIsCustomTabEditorOpen(false)
    setCustomTabName('')
    setCustomTabExpression('')
  }

  function handleOpenCustomTabEditor() {
    setActiveCustomTabId(null)
    setStatusFilter('all')
    setIsCustomTabEditorOpen(true)
  }

  function handleDeleteCustomTab(tabId: string) {
    setCustomTabs((currentTabs) => currentTabs.filter((tab) => tab.id !== tabId))
    setActiveCustomTabId(null)
    setStatusFilter('all')
    setIsCustomTabEditorOpen(false)
  }

  const activeCustomTab = customTabs.find((tab) => tab.id === activeCustomTabId)
  const selectedContact = contacts.find((contact) => contact.id === selectedContactId)
  const moveTargetContacts = contacts.filter((contact) => contact.id !== selectedContactId)
  const shouldShowContactDetailFeedback =
    mode === 'list' && selectedContact !== undefined && (error !== null || notice !== null)
  const tagCounts = [...contacts.reduce((counts, contact) => {
    for (const tag of contact.tags) {
      counts.set(tag, (counts.get(tag) ?? 0) + 1)
    }
    return counts
  }, new Map<string, number>())].sort(([firstTag], [secondTag]) =>
    firstTag.localeCompare(secondTag),
  )
  const activeListTabId =
    activeCustomTabId === null
      ? isCustomTabEditorOpen
        ? 'add'
        : statusFilter
      : activeCustomTabId

  const visibleContacts = contacts
    .filter((contact) => {
      if (activeCustomTab !== undefined) {
        return customTabMatches(contact, activeCustomTab.expression)
      }
      if (statusFilter !== 'all' && contact.status !== statusFilter) {
        return false
      }
      return true
    })
    .filter((contact) => {
      if (
        selectedTagFilter !== null &&
        !contact.tags.some((tag) => tag === selectedTagFilter)
      ) {
        return false
      }
      const queryTerms = searchQuery
        .trim()
        .toLowerCase()
        .split(/\s+/)
        .filter(Boolean)
      if (queryTerms.length === 0) {
        return true
      }

      const searchableText = [
        contact.display_name,
        contact.memo ?? '',
        contact.status,
        contact.tags.join(' '),
        ...contact.email_addresses.map((address) => address.email_address),
      ]
        .join(' ')
        .toLowerCase()

      return queryTerms.every((term) => searchableText.includes(term))
    })
    .toSorted((first, second) => {
      if (sortMode === 'updated') {
        return second.updated_at.localeCompare(first.updated_at)
      }
      return first.display_name.localeCompare(second.display_name)
    })

  return (
    <main className="app-shell">
      <div className="contacts-shell">
        <header className="contacts-header">
          <div>
            <p>{t('app.name')}</p>
            <h1>
              {mode === 'pending' ? t('contacts.pendingHeading') : t('contacts.heading')}
            </h1>
          </div>
          <nav aria-label={t('contacts.navLabel')}>
            <a href="/contacts">{t('contacts.heading')}</a>
            <a href="/contacts/pending">{t('contacts.pending.short')}</a>
            <a href="/">{t('top.heading')}</a>
          </nav>
        </header>

        {!shouldShowContactDetailFeedback && error !== null && (
          <p className="contact-error" role="alert">{error}</p>
        )}
        {!shouldShowContactDetailFeedback && notice !== null && (
          <p className="contact-notice">{notice}</p>
        )}

        {mode === 'pending' ? (
          <section aria-labelledby="pending-contacts-heading" className="contact-panel">
            <div className="section-heading">
              <h2 id="pending-contacts-heading">{t('contacts.unresolvedFrom.heading')}</h2>
            </div>
            <div className="contact-list">
              {unresolvedFromAddresses.map((item) => (
                <article className="contact-row" key={item.email_address_id}>
                  <div>
                    <h3>{item.email_address}</h3>
                    <p>
                      {item.latest_subject ?? 'メール本文の情報はまだありません。'}
                    </p>
                  </div>
                  <div className="pending-contact-actions">
                    <span>{item.suggestion_status}</span>
                    <button
                      disabled={busyEmailAddress === item.email_address}
                      onClick={() => handleGeneratePrefill(item)}
                      type="button"
                    >
                      {t('contacts.prefill.generate')}
                    </button>
                    <label>
                      <span>{t('contacts.displayName')}</span>
                      <input
                        aria-label={t('contacts.displayNameFor', {
                          email: item.email_address,
                        })}
                        onChange={(event) =>
                          setPendingDisplayNames((currentNames) => ({
                            ...currentNames,
                            [item.email_address]: event.target.value,
                          }))
                        }
                        placeholder={pendingDisplayName(item)}
                        value={pendingDisplayNames[item.email_address] ?? ''}
                      />
                    </label>
                    <div className="pending-contact-buttons">
                      <button
                        aria-label={t('contacts.createFor', {
                          email: item.email_address,
                        })}
                        disabled={busyEmailAddress === item.email_address}
                        onClick={() => handleCreatePendingContact(item, 'active')}
                        type="button"
                      >
                        {t('contacts.create')}
                      </button>
                      <button
                        aria-label={t('contacts.createSkippedFor', {
                          email: item.email_address,
                        })}
                        disabled={busyEmailAddress === item.email_address}
                        onClick={() => handleCreatePendingContact(item, 'skipped')}
                        type="button"
                      >
                        {t('contacts.createSkipped')}
                      </button>
                    </div>
                    <label>
                      <span>{t('contacts.existingContact')}</span>
                      <select
                        aria-label={t('contacts.existingContactFor', {
                          email: item.email_address,
                        })}
                        onChange={(event) =>
                          setPendingExistingContactIds((currentIds) => ({
                            ...currentIds,
                            [item.email_address]: event.target.value,
                          }))
                        }
                        value={pendingExistingContactIds[item.email_address] ?? ''}
                      >
                        <option value="">{t('contacts.selectContact')}</option>
                        {contacts.map((contact) => (
                          <option key={contact.id} value={contact.id}>
                            {contact.display_name}
                          </option>
                        ))}
                      </select>
                    </label>
                    <button
                      aria-label={t('contacts.addToExistingFor', {
                        email: item.email_address,
                      })}
                      disabled={
                        busyEmailAddress === item.email_address ||
                        (pendingExistingContactIds[item.email_address] ?? '') === ''
                      }
                      onClick={() => handleAddPendingToExistingContact(item)}
                      type="button"
                    >
                      {t('contacts.addToExisting')}
                    </button>
                  </div>
                </article>
              ))}
              {unresolvedFromAddresses.length === 0 && (
                <p className="empty-state">{t('contacts.noPending')}</p>
              )}
            </div>
          </section>
        ) : (
          <>
            <section aria-labelledby="contact-tools-heading" className="contact-panel contact-tools-panel">
              <div className="section-heading">
                <h2 id="contact-tools-heading">{t('contacts.tools.heading')}</h2>
              </div>
              <div className="contact-tools">
                <div aria-label={t('contacts.search.region')} role="search">
                  <label>
                    <span>{t('contacts.search.label')}</span>
                    <input
                      aria-label={t('contacts.search.label')}
                      onChange={(event) => setSearchQuery(event.target.value)}
                      placeholder={t('contacts.search.label')}
                      type="search"
                      value={searchQuery}
                    />
                  </label>
                  {tagCounts.length > 0 && (
                    <div
                      aria-label={t('contacts.tagFilters.label')}
                      className="contact-tag-filters"
                    >
                      {tagCounts.map(([tag, count]) => (
                        <button
                          aria-label={`${tag} ${count}`}
                          aria-pressed={selectedTagFilter === tag}
                          key={tag}
                          onClick={() =>
                            setSelectedTagFilter((currentTag) =>
                              currentTag === tag ? null : tag,
                            )
                          }
                          type="button"
                        >
                          {tag}
                          <span>{count}</span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                <label className="contact-sort">
                  <span>{t('contacts.sort.label')}</span>
                  <select
                    aria-label={t('contacts.sort.aria')}
                    onChange={(event) =>
                      setSortMode(event.target.value as 'name' | 'updated')
                    }
                    value={sortMode}
                  >
                    <option value="name">{t('contacts.sort.name')}</option>
                    <option value="updated">{t('contacts.sort.updated')}</option>
                  </select>
                </label>
                <div className="contact-tool-actions">
                  <button
                    aria-expanded={isCreateOpen}
                    onClick={() => setIsCreateOpen((isOpen) => !isOpen)}
                    type="button"
                  >
                    {t('contacts.new')}
                  </button>
                  <a href="/contacts/pending">{t('contacts.pending.short')}</a>
                </div>
              </div>
              {isCreateOpen && (
                <form className="contact-form" onSubmit={handleCreateContact}>
                  <div className="section-heading">
                    <h2 id="create-contact-heading">{t('contacts.new')}</h2>
                  </div>
                  <label>
                    <span>{t('contacts.displayName')}</span>
                    <input
                      onChange={(event) => setDisplayName(event.target.value)}
                      required
                      value={displayName}
                    />
                  </label>
                  <label>
                    <span>{t('contacts.emailAddress')}</span>
                    <input
                      onChange={(event) => setEmailAddress(event.target.value)}
                      type="email"
                      value={emailAddress}
                    />
                  </label>
                  <label>
                    <span>{t('common.status')}</span>
                    <select
                      onChange={(event) =>
                        setStatus(event.target.value as 'active' | 'skipped')
                      }
                      value={status}
                    >
                      <option value="active">{t('common.active')}</option>
                      <option value="skipped">{t('common.skipped')}</option>
                    </select>
                  </label>
                  <label>
                    <span>{t('contacts.memo')}</span>
                    <textarea
                      onChange={(event) => setMemo(event.target.value)}
                      value={memo}
                    />
                  </label>
                  <button disabled={isSubmitting} type="submit">
                    {t('contacts.create')}
                  </button>
                </form>
              )}
            </section>

            <section aria-labelledby="contacts-heading" className="contact-list-workspace">
              <div
                aria-label={t('contacts.list.views')}
                className="contact-list-tabs"
                role="tablist"
              >
                <div className="contact-list-tabs-left">
                  {(['all', 'active'] as const).map((filter) => (
                    <button
                      aria-controls="contact-list-panel"
                      aria-selected={
                        !isCustomTabEditorOpen &&
                        activeCustomTabId === null &&
                        statusFilter === filter
                      }
                      id={`contact-list-tab-${filter}`}
                      key={filter}
                      onClick={() => handleStatusTabClick(filter)}
                      role="tab"
                      type="button"
                    >
                      {filter === 'all' ? t('common.all') : t('common.active')}
                    </button>
                  ))}
                  {customTabs.map((tab) => (
                    <button
                      aria-controls="contact-list-panel"
                      aria-selected={!isCustomTabEditorOpen && activeCustomTabId === tab.id}
                      id={`contact-list-tab-${tab.id}`}
                      key={tab.id}
                      onClick={() => {
                        setActiveCustomTabId(tab.id)
                        setStatusFilter('all')
                        setIsCustomTabEditorOpen(false)
                      }}
                      role="tab"
                      type="button"
                    >
                      {tab.label}
                    </button>
                  ))}
                  {customTabs.length < maxCustomTabs && (
                    <button
                      aria-controls="contact-list-panel"
                      aria-selected={isCustomTabEditorOpen}
                      id="contact-list-tab-add"
                      onClick={handleOpenCustomTabEditor}
                      role="tab"
                      type="button"
                    >
                      +
                    </button>
                  )}
                </div>
                <div className="contact-list-tabs-right">
                  {(['archived', 'skipped'] as const).map((filter) => (
                    <button
                      aria-controls="contact-list-panel"
                      aria-selected={
                        !isCustomTabEditorOpen &&
                        activeCustomTabId === null &&
                        statusFilter === filter
                      }
                      id={`contact-list-tab-${filter}`}
                      key={filter}
                      onClick={() => handleStatusTabClick(filter)}
                      role="tab"
                      type="button"
                    >
                      {filter === 'skipped' ? t('contacts.tab.skip') : t('common.archived')}
                    </button>
                  ))}
                </div>
              </div>
              <div className="contact-list-panel-surface">
                <section
                  aria-labelledby={`${
                    activeListTabId === 'add'
                      ? 'contact-list-tab-add'
                      : `contact-list-tab-${activeListTabId}`
                  } contacts-heading`}
                  className="contact-panel contact-list-panel"
                  id="contact-list-panel"
                  role="tabpanel"
                >
                  <div className="section-heading">
                    <h2 id="contacts-heading">{t('contacts.list.heading')}</h2>
                    {activeCustomTab !== undefined && !isCustomTabEditorOpen && (
                      <div className="custom-tab-actions">
                        <p>{activeCustomTab.expression}</p>
                        <button
                          onClick={() => handleDeleteCustomTab(activeCustomTab.id)}
                          type="button"
                        >
                          {t('contacts.customTab.delete')}
                        </button>
                      </div>
                    )}
                  </div>
                  {isCustomTabEditorOpen && (
                    <form className="custom-tab-form custom-tab-form-panel" onSubmit={handleAddCustomTab}>
                      <label>
                        <span>{t('contacts.customTab.name')}</span>
                        <input
                          aria-label={t('contacts.customTab.name')}
                          maxLength={maxCustomTabNameLength}
                          onChange={(event) => setCustomTabName(event.target.value)}
                          placeholder="mailing-list"
                          value={customTabName}
                        />
                      </label>
                      <label>
                        <span>{t('contacts.customTab.expression')}</span>
                        <input
                          aria-label={t('contacts.customTab.expression')}
                          onChange={(event) => setCustomTabExpression(event.target.value)}
                          placeholder={t('contacts.customTab.expressionPlaceholder')}
                          value={customTabExpression}
                        />
                      </label>
                      <button type="submit">{t('common.ok')}</button>
                    </form>
                  )}
                  <div className="contact-list">
                    {visibleContacts.map((contact) => {
                      const email = primaryEmail(contact)
                      const isExpanded = selectedContact?.id === contact.id
                      return (
                        <article
                          className={`contact-row contact-expandable-row${
                            isExpanded ? ' contact-row-expanded' : ''
                          }`}
                          key={contact.id}
                          onClick={(event) => {
                            if (shouldIgnoreContactCardClick(event.target)) {
                              return
                            }
                            if (isExpanded) {
                              closeContactDetail()
                              return
                            }
                            openContactDetailFromUser(contact)
                          }}
                        >
                          <div className="contact-row-main">
                            <div>
                              <div className="contact-identity">
                                <div className="contact-avatar">
                                  <img
                                    alt={t('contacts.avatarAlt', {
                                      name: contact.display_name,
                                    })}
                                    src={contact.avatar_url ?? defaultContactAvatarUrl}
                                  />
                                </div>
                                <div>
                                  <h3>{contact.display_name}</h3>
                                  <p>{email?.email_address ?? t('contacts.noEmailAddress')}</p>
                                </div>
                              </div>
                            </div>
                            <div className="contact-row-side">
                              <div className="contact-tags">
                                <span>{contact.status}</span>
                                {contact.tags.map((tag) => (
                                  <span key={tag}>{tag}</span>
                                ))}
                              </div>
                              <button
                                aria-expanded={isExpanded}
                                aria-label={t(
                                  isExpanded ? 'contacts.collapse' : 'contacts.expand',
                                  { name: contact.display_name },
                                )}
                                className="contact-pull-tab"
                                onClick={() =>
                                  isExpanded
                                    ? closeContactDetail()
                                    : openContactDetailFromUser(contact)
                                }
                                type="button"
                              >
                                <span aria-hidden="true">
                                  {isExpanded ? '\u25b3' : '\u25bd'}
                                </span>
                              </button>
                            </div>
                          </div>
                          {isExpanded && selectedContact !== undefined && (
                            <div className="contact-detail-card">
                              <div className="section-heading contact-detail-heading">
                                <h2 id="contact-detail-heading">{t('contacts.detail.heading')}</h2>
                                <div className="contact-detail-actions">
                                  {!isContactDetailEditing && (
                                    <button
                                      onClick={() => beginContactDetailEdit(selectedContact)}
                                      type="button"
                                    >
                                      {t('contacts.detail.edit')}
                                    </button>
                                  )}
                                </div>
                              </div>
                              {isContactDetailEditing ? (
                                <form className="contact-detail-form" onSubmit={handleUpdateContact}>
                                  <label className="contact-detail-primary">
                                    <span>{t('contacts.displayName')}</span>
                                    <div className="input-with-clear">
                                      <input
                                        aria-label={t('contacts.detail.displayName')}
                                        onChange={(event) =>
                                          setDetailDisplayName(event.target.value)
                                        }
                                        required
                                        value={detailDisplayName}
                                      />
                                      <button
                                        aria-label={t('contacts.detail.clearDisplayName')}
                                        disabled={detailDisplayName === ''}
                                        onClick={() => setDetailDisplayName('')}
                                        type="button"
                                      >
                                        ×
                                      </button>
                                    </div>
                                  </label>
                                  <label className="contact-detail-secondary">
                                    <span>{t('common.status')}</span>
                                    <select
                                      aria-label={t('contacts.detail.status')}
                                      onChange={(event) =>
                                        setDetailStatus(
                                          event.target.value as
                                            | 'active'
                                            | 'skipped'
                                            | 'archived',
                                        )
                                      }
                                      value={detailStatus}
                                    >
                                      <option value="active">{t('common.active')}</option>
                                      <option value="skipped">{t('common.skipped')}</option>
                                      <option value="archived">{t('common.archived')}</option>
                                    </select>
                                  </label>
                                  <div className="contact-detail-primary contact-detail-memo-field">
                                    <label>
                                      <span>{t('contacts.memo')}</span>
                                      <textarea
                                        aria-label={t('contacts.detail.memo')}
                                        onChange={(event) => setDetailMemo(event.target.value)}
                                        value={detailMemo}
                                      />
                                    </label>
                                  </div>
                                  <div className="contact-detail-secondary contact-detail-tags-field">
                                    <label>
                                      <span>{t('contacts.tags')}</span>
                                      <input
                                        aria-label={t('contacts.detail.tags')}
                                        onChange={(event) => setDetailTags(event.target.value)}
                                        value={detailTags}
                                      />
                                    </label>
                                    <button
                                      disabled
                                      title={t('contacts.avatar.unimplemented')}
                                      type="button"
                                    >
                                      {t('contacts.avatar.update')}
                                    </button>
                                    <button disabled={isSubmitting} type="submit">
                                      {t('contacts.detail.save')}
                                    </button>
                                  </div>
                                </form>
                              ) : (
                                <div className="contact-detail-summary contact-detail-primary">
                                  <div>
                                    <span>{t('contacts.memo')}</span>
                                    <p>{selectedContact.memo ?? t('contacts.detail.noMemo')}</p>
                                  </div>
                                </div>
                              )}
                              <div className="contact-detail-emails contact-detail-primary">
                                <h3>{t('contacts.emailAddresses.heading')}</h3>
                                <ul>
                                  {selectedContact.email_addresses.map((emailAddress) => (
                                    <li key={emailAddress.id}>
                                      <span>{emailAddress.email_address}</span>
                                      {emailAddress.is_primary && (
                                        <strong>{t('common.primary')}</strong>
                                      )}
                                      {emailAddress.status === 'inactive' && (
                                        <strong>{t('common.inactive')}</strong>
                                      )}
                                      {isContactDetailEditing &&
                                        !emailAddress.is_primary &&
                                        (emailAddress.status ?? 'active') === 'active' && (
                                          <button
                                            aria-label={t('contacts.email.setPrimaryFor', {
                                              email: emailAddress.email_address,
                                            })}
                                            disabled={isSubmitting}
                                            onClick={() =>
                                              handleSetPrimaryEmailAddress(emailAddress.id)
                                            }
                                            type="button"
                                          >
                                            {t('contacts.email.setPrimary')}
                                          </button>
                                        )}
                                      {isContactDetailEditing &&
                                        emailAddress.status === 'inactive' && (
                                          <button
                                            aria-label={t('contacts.email.activateFor', {
                                              email: emailAddress.email_address,
                                            })}
                                            disabled={isSubmitting}
                                            onClick={() =>
                                              handleActivateEmailAddress(emailAddress.id)
                                            }
                                            title={
                                              isSubmitting
                                                ? t('contacts.updateRunning')
                                                : undefined
                                            }
                                            type="button"
                                          >
                                            {t('contacts.email.activate')}
                                          </button>
                                        )}
                                      {isContactDetailEditing &&
                                        emailAddress.status !== 'inactive' && (
                                        <button
                                          aria-label={t(
                                            emailAddress.has_inbound_message_history
                                              ? 'contacts.email.deactivateFor'
                                              : 'contacts.email.removeFor',
                                            { email: emailAddress.email_address },
                                          )}
                                          disabled={isSubmitting}
                                          onClick={() =>
                                            handleDeleteEmailAddress(emailAddress.id)
                                          }
                                          title={
                                            isSubmitting
                                              ? t('contacts.updateRunning')
                                              : emailAddress.has_inbound_message_history
                                                ? t('contacts.email.deactivateReason')
                                                : t('contacts.email.removeReason')
                                          }
                                          type="button"
                                        >
                                          {emailAddress.has_inbound_message_history
                                            ? t('contacts.email.deactivate')
                                            : t('contacts.email.remove')}
                                        </button>
                                        )}
                                      {isContactDetailEditing &&
                                        moveTargetContacts.length > 0 && (
                                          <div className="contact-email-move">
                                            <select
                                              aria-label={t('contacts.email.moveSelect', {
                                                email: emailAddress.email_address,
                                              })}
                                              onChange={(event) =>
                                                setMoveTargetContactIds((currentIds) => ({
                                                  ...currentIds,
                                                  [emailAddress.id]: event.target.value,
                                                }))
                                              }
                                              value={moveTargetContactIds[emailAddress.id] ?? ''}
                                            >
                                              <option value="">{t('contacts.email.moveTo')}</option>
                                              {moveTargetContacts.map((contact) => (
                                                <option key={contact.id} value={contact.id}>
                                                  {contact.display_name}
                                                </option>
                                              ))}
                                            </select>
                                            <button
                                              disabled={
                                                isSubmitting ||
                                                (moveTargetContactIds[emailAddress.id] ?? '') ===
                                                  ''
                                              }
                                              onClick={() =>
                                                handleMoveEmailAddress(emailAddress.id)
                                              }
                                              title={
                                                isSubmitting
                                                  ? t('contacts.updateRunning')
                                                  : (moveTargetContactIds[emailAddress.id] ??
                                                        '') === ''
                                                    ? t('contacts.email.chooseDestination')
                                                    : undefined
                                              }
                                              type="button"
                                            >
                                              {t('contacts.email.move')}
                                            </button>
                                          </div>
                                        )}
                                    </li>
                                  ))}
                                </ul>
                                {isContactDetailEditing && (
                                  <form
                                    className="contact-email-form"
                                    onSubmit={handleAddEmailAddress}
                                  >
                                    <label>
                                      <span>{t('contacts.email.new')}</span>
                                      <div className="input-with-clear">
                                        <input
                                          aria-label={t('contacts.email.new')}
                                          onChange={(event) =>
                                            setNewEmailAddress(event.target.value)
                                          }
                                          type="email"
                                          value={newEmailAddress}
                                        />
                                        <button
                                          aria-label={t('contacts.email.clearNew')}
                                          disabled={newEmailAddress === ''}
                                          onClick={() => setNewEmailAddress('')}
                                          type="button"
                                        >
                                          ×
                                        </button>
                                      </div>
                                    </label>
                                    <button disabled={isSubmitting} type="submit">
                                      {t('contacts.email.add')}
                                    </button>
                                  </form>
                                )}
                              </div>
                              <div className="contact-related-cases contact-detail-secondary">
                                <h3>{t('contacts.relatedCases.heading')}</h3>
                                <p>{t('contacts.relatedCases.empty')}</p>
                              </div>
                              {shouldShowContactDetailFeedback && (
                                <div className="contact-detail-feedback">
                                  {error !== null && (
                                    <p className="contact-error" role="alert">{error}</p>
                                  )}
                                  {notice !== null && (
                                    <p className="contact-notice">{notice}</p>
                                  )}
                                </div>
                              )}
                            </div>
                          )}
                        </article>
                      )
                    })}
                    {visibleContacts.length === 0 && (
                      <p className="empty-state">{t('contacts.empty')}</p>
                    )}
                  </div>
                </section>
              </div>
            </section>
          </>
        )}
      </div>
    </main>
  )
}

export default ContactsView
