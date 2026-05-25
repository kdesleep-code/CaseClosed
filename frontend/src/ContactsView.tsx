import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import {
  addContactEmailAddress,
  activateContactEmailAddress,
  createContact,
  deleteContact,
  deleteContactEmailAddress,
  listContacts,
  listUnresolvedFromAddresses,
  mergeContact,
  moveContactEmailAddress,
  setContactPrimaryEmailAddress,
  updateContact,
} from './phase3Api'
import type { Contact, UnresolvedFromAddress } from './phase3Api'
import { t } from './i18n'
import { AppLink, navigateTo } from './navigation'

type ContactsMode = 'list' | 'pending'
type StatusFilter = 'all' | 'active' | 'skipped' | 'archived' | 'mailing_list'
type ContactKind = 'person' | 'mailing_list'
type SenderResolutionMode = 'self' | 'reply_to'
type ContactMailImportanceRuleAction = 'llm' | 'fixed' | 'llm_with_instruction'
type ContactMailImportanceRuleValue = 'pinned' | 'high' | 'middle' | 'low'
type CustomContactTab = {
  id: string
  label: string
  expression: string
}

export type ContactsInitialData =
  | {
      mode: 'list'
      contacts: Contact[]
    }
  | {
      mode: 'pending'
      contacts: Contact[]
      unresolvedFromAddresses: UnresolvedFromAddress[]
    }

const maxCustomTabs = 5
const maxCustomTabNameLength = 12
const defaultContactAvatarUrl = new URL(
  './assets/default-contact-avatar.svg',
  import.meta.url,
).href
const defaultMailingListAvatarUrl = new URL(
  './assets/default-mailing-list-avatar.svg',
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

function isMailingListContact(contact: Contact) {
  return (contact.kind ?? 'person') === 'mailing_list'
}

function defaultAvatarUrlForContact(contact: Contact) {
  return isMailingListContact(contact)
    ? defaultMailingListAvatarUrl
    : defaultContactAvatarUrl
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

function ContactsView({
  mode,
  initialData,
}: {
  mode: ContactsMode
  initialData?: ContactsInitialData
}) {
  const [contacts, setContacts] = useState<Contact[]>(
    initialData?.contacts ?? [],
  )
  const [unresolvedFromAddresses, setUnresolvedFromAddresses] = useState<
    UnresolvedFromAddress[]
  >(
    initialData?.mode === 'pending'
      ? initialData.unresolvedFromAddresses
      : [],
  )
  const [pendingDisplayNames, setPendingDisplayNames] = useState<Record<string, string>>(
    {},
  )
  const [pendingDecisions, setPendingDecisions] = useState<Record<string, 'active' | 'skipped'>>({})
  const [pendingKinds, setPendingKinds] = useState<Record<string, ContactKind>>({})
  const [pendingSenderResolutions, setPendingSenderResolutions] = useState<
    Record<string, SenderResolutionMode>
  >({})
  const [displayName, setDisplayName] = useState('')
  const [emailAddress, setEmailAddress] = useState('')
  const [status, setStatus] = useState<'active' | 'skipped'>('active')
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [isMergeToolOpen, setIsMergeToolOpen] = useState(false)
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
  const [detailKind, setDetailKind] = useState<ContactKind>('person')
  const [detailSenderResolutionMode, setDetailSenderResolutionMode] =
    useState<SenderResolutionMode>('self')
  const [detailMailImportanceRuleAction, setDetailMailImportanceRuleAction] =
    useState<ContactMailImportanceRuleAction>('llm')
  const [detailMailImportanceRuleImportance, setDetailMailImportanceRuleImportance] =
    useState<ContactMailImportanceRuleValue>('high')
  const [detailMailImportanceRuleInstruction, setDetailMailImportanceRuleInstruction] =
    useState('')
  const [
    detailMailingListRecipientExpression,
    setDetailMailingListRecipientExpression,
  ] = useState('')
  const [detailTags, setDetailTags] = useState('')
  const [newEmailAddress, setNewEmailAddress] = useState('')
  const [moveTargetContactIds, setMoveTargetContactIds] = useState<Record<string, string>>(
    {},
  )
  const [mergeSourceQuery, setMergeSourceQuery] = useState('')
  const [mergeDestinationQuery, setMergeDestinationQuery] = useState('')
  const [busyEmailAddress, setBusyEmailAddress] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [hasLoadedPendingContacts, setHasLoadedPendingContacts] = useState(
    initialData?.mode === 'pending',
  )
  const [hasHadPendingContacts, setHasHadPendingContacts] = useState(
    initialData?.mode === 'pending' &&
      initialData.unresolvedFromAddresses.length > 0,
  )
  const handledDeepLinkRef = useRef('')
  const pendingScrollContactIdRef = useRef<string | null>(null)

  useEffect(() => {
    if (initialData !== undefined && initialData.mode === mode) {
      return
    }
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
          setHasLoadedPendingContacts(true)
          if (pendingItems.length > 0) {
            setHasHadPendingContacts(true)
          }
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
  }, [initialData, mode])

  useEffect(() => {
    if (
      mode === 'pending' &&
      hasLoadedPendingContacts &&
      hasHadPendingContacts &&
      unresolvedFromAddresses.length === 0
    ) {
      navigateTo('/', true)
    }
  }, [hasHadPendingContacts, hasLoadedPendingContacts, mode, unresolvedFromAddresses.length])

  useEffect(() => {
    if (mode !== 'list') {
      return
    }

    const deepLinkKey = window.location.search
    if (deepLinkKey === '' || handledDeepLinkRef.current === deepLinkKey) {
      return
    }

    const params = new URLSearchParams(deepLinkKey)
    const contactId = params.get('contact_id')
    const newEmail = params.get('new_email')

    if (contactId !== null) {
      const linkedContact = contacts.find((contact) => contact.id === contactId)
      if (linkedContact === undefined) {
        return
      }
      handledDeepLinkRef.current = deepLinkKey
      setSearchQuery('')
      setSelectedTagFilter(null)
      setStatusFilter(
        isMailingListContact(linkedContact)
          ? 'mailing_list'
          : linkedContact.status === 'active'
            ? 'active'
            : 'all',
      )
      setActiveCustomTabId(null)
      setIsCustomTabEditorOpen(false)
      pendingScrollContactIdRef.current = linkedContact.id
      openContactDetail(linkedContact)
      return
    }

    if (newEmail !== null && newEmail.trim() !== '') {
      handledDeepLinkRef.current = deepLinkKey
      setSearchQuery('')
      setSelectedTagFilter(null)
      setStatusFilter('all')
      setActiveCustomTabId(null)
      setIsCustomTabEditorOpen(false)
      setIsCreateOpen(true)
      setDisplayName(params.get('display_name') ?? newEmail.split('@')[0])
      setEmailAddress(newEmail)
      setStatus('active')
    }
  }, [contacts, mode])

  useEffect(() => {
    if (pendingScrollContactIdRef.current === null) {
      return
    }

    const contactId = pendingScrollContactIdRef.current
    window.setTimeout(() => {
      const element = document.getElementById(`contact-row-${contactId}`)
      if (element !== null) {
        element.scrollIntoView({ block: 'center' })
        pendingScrollContactIdRef.current = null
      }
    }, 0)
  }, [selectedContactId, statusFilter, activeCustomTabId, isCustomTabEditorOpen])

  async function handleCreateContact(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setNotice(null)
    setIsSubmitting(true)

    try {
      const createdContact = await createContact({
        display_name: displayName,
        user_memo: '',
        status,
        kind: 'person',
        sender_resolution_mode: 'self',
        mailing_list_recipient_expression: null,
        mail_importance_rule_action: 'llm',
        mail_importance_rule_importance: null,
        mail_importance_rule_instruction: null,
        tags: [],
        email_addresses:
          emailAddress.trim() === ''
            ? []
            : [{ email_address: emailAddress, is_primary: true }],
      })
      setContacts((currentContacts) => [...currentContacts, createdContact])
      setSearchQuery('')
      setSelectedTagFilter(null)
      setStatusFilter('all')
      setActiveCustomTabId(null)
      setIsCustomTabEditorOpen(false)
      openContactDetail(createdContact)
      setIsContactDetailEditing(true)
      setDisplayName('')
      setEmailAddress('')
      setStatus('active')
      setIsCreateOpen(false)
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsSubmitting(false)
    }
  }

  function pendingDisplayName(item: UnresolvedFromAddress) {
    return (
      pendingDisplayNames[item.email_address] ??
      item.suggestion?.suggested_display_name ??
      item.inferred_display_name ??
      item.email_address.split('@')[0]
    )
  }

  function pendingDecision(item: UnresolvedFromAddress) {
    return pendingDecisions[item.email_address] ?? 'active'
  }

  function pendingKind(item: UnresolvedFromAddress): ContactKind {
    return pendingKinds[item.email_address] ?? item.inferred_kind ?? 'person'
  }

  function pendingSenderResolution(item: UnresolvedFromAddress): SenderResolutionMode {
    return (
      pendingSenderResolutions[item.email_address] ??
      item.inferred_sender_resolution ??
      'self'
    )
  }

  function handlePendingDecision(
    item: UnresolvedFromAddress,
    decision: 'active' | 'skipped',
  ) {
    setPendingDecisions((currentDecisions) => ({
      ...currentDecisions,
      [item.email_address]: decision,
    }))
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
    setPendingDecisions((currentDecisions) => {
      const nextDecisions = { ...currentDecisions }
      delete nextDecisions[emailAddress]
      return nextDecisions
    })
    setPendingKinds((currentKinds) => {
      const nextKinds = { ...currentKinds }
      delete nextKinds[emailAddress]
      return nextKinds
    })
    setPendingSenderResolutions((currentResolutions) => {
      const nextResolutions = { ...currentResolutions }
      delete nextResolutions[emailAddress]
      return nextResolutions
    })
  }

  async function handleCreatePendingContact(
    item: UnresolvedFromAddress,
    status: 'active' | 'skipped',
    kind: ContactKind = 'person',
    senderResolution: SenderResolutionMode = 'self',
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
        user_memo: '',
        status,
        kind,
        sender_resolution_mode: kind === 'person' ? 'self' : senderResolution,
        mailing_list_recipient_expression: null,
        mail_importance_rule_action: 'llm',
        mail_importance_rule_importance: null,
        mail_importance_rule_instruction: null,
        tags: [],
        email_addresses: [
          { email_address: item.email_address, is_primary: true },
        ],
        source_suggestion_id: item.suggestion?.id ?? null,
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
    setDetailMemo(contact.user_memo ?? '')
    setDetailStatus(contact.status as 'active' | 'skipped' | 'archived')
    setDetailKind(contact.kind ?? 'person')
    setDetailSenderResolutionMode(contact.sender_resolution_mode ?? 'self')
    setDetailMailImportanceRuleAction(contact.mail_importance_rule_action ?? 'llm')
    setDetailMailImportanceRuleImportance(
      contact.mail_importance_rule_importance ?? 'high',
    )
    setDetailMailImportanceRuleInstruction(
      contact.mail_importance_rule_instruction ?? '',
    )
    setDetailMailingListRecipientExpression(
      contact.mailing_list_recipient_expression ?? '',
    )
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
    setDetailMemo(contact.user_memo ?? '')
    setDetailStatus(contact.status as 'active' | 'skipped' | 'archived')
    setDetailKind(contact.kind ?? 'person')
    setDetailSenderResolutionMode(contact.sender_resolution_mode ?? 'self')
    setDetailMailImportanceRuleAction(contact.mail_importance_rule_action ?? 'llm')
    setDetailMailImportanceRuleImportance(
      contact.mail_importance_rule_importance ?? 'high',
    )
    setDetailMailImportanceRuleInstruction(
      contact.mail_importance_rule_instruction ?? '',
    )
    setDetailMailingListRecipientExpression(
      contact.mailing_list_recipient_expression ?? '',
    )
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
        user_memo: detailMemo,
        status: detailStatus,
        kind: detailKind,
        sender_resolution_mode:
          detailKind === 'person' ? 'self' : detailSenderResolutionMode,
        mailing_list_recipient_expression:
          detailKind === 'mailing_list'
            ? detailMailingListRecipientExpression
            : null,
        mail_importance_rule_action: detailMailImportanceRuleAction,
        mail_importance_rule_importance:
          detailMailImportanceRuleAction === 'fixed'
            ? detailMailImportanceRuleImportance
            : null,
        mail_importance_rule_instruction:
          detailMailImportanceRuleAction === 'llm_with_instruction'
            ? detailMailImportanceRuleInstruction
            : null,
        tags: detailKind === 'mailing_list' ? [] : parseTags(detailTags),
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

  async function handleDeleteContact() {
    const selectedContact = contacts.find((contact) => contact.id === selectedContactId)
    if (selectedContact === undefined) {
      return
    }

    setError(null)
    setNotice(null)
    setIsSubmitting(true)

    try {
      await deleteContact(selectedContact.id)
      setContacts((currentContacts) =>
        currentContacts.filter((contact) => contact.id !== selectedContact.id),
      )
      closeContactDetail()
      setNotice(t('contacts.detail.deleted'))
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

  async function handleMergeContactsTool(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const sourceContact = contacts.find(
      (contact) =>
        !isMailingListContact(contact) && contact.display_name === mergeSourceQuery,
    )
    const destinationContact = contacts.find(
      (contact) =>
        !isMailingListContact(contact) &&
        contact.display_name === mergeDestinationQuery,
    )
    if (
      sourceContact === undefined ||
      destinationContact === undefined ||
      sourceContact.id === destinationContact.id
    ) {
      return
    }

    setError(null)
    setNotice(null)
    setIsSubmitting(true)

    try {
      const response = await mergeContact(
        sourceContact.id,
        destinationContact.id,
      )
      setContacts((currentContacts) =>
        currentContacts
          .filter((contact) => contact.id !== response.deleted_contact_id)
          .map((contact) =>
            contact.id === response.target_contact.id ? response.target_contact : contact,
          ),
      )
      openContactDetail(response.target_contact)
      setIsContactDetailEditing(false)
      setMergeSourceQuery('')
      setMergeDestinationQuery('')
      setIsMergeToolOpen(false)
      setNotice(t('contacts.detail.merged'))
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
    setSearchQuery('')
    setSelectedTagFilter(null)
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
  const selectedIsMailingList =
    selectedContact !== undefined && isMailingListContact(selectedContact)
  const moveTargetContacts = contacts.filter(
    (contact) =>
      contact.id !== selectedContactId &&
      isMailingListContact(contact) === selectedIsMailingList,
  )
  const mergeToolContacts = contacts.filter(
    (contact) => !isMailingListContact(contact) && contact.status === 'active',
  )
  const mergeDestinationContacts = mergeToolContacts.filter(
    (contact) => contact.display_name !== mergeSourceQuery,
  )
  const mergeSourceContact = mergeToolContacts.find(
    (contact) => contact.display_name === mergeSourceQuery,
  )
  const mergeDestinationContact = mergeToolContacts.find(
    (contact) => contact.display_name === mergeDestinationQuery,
  )
  const shouldShowContactDetailFeedback =
    mode === 'list' && selectedContact !== undefined && (error !== null || notice !== null)
  const canDeleteSelectedContact =
    selectedContact !== undefined &&
    selectedContact.email_addresses.every(
      (emailAddress) => emailAddress.has_inbound_message_history !== true,
    )
  const baseVisibleKindContacts = contacts.filter((contact) =>
    statusFilter === 'mailing_list'
      ? isMailingListContact(contact)
      : !isMailingListContact(contact),
  )
  const tagCounts = [...baseVisibleKindContacts.reduce((counts, contact) => {
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
  const customTabPreviewExpression = isCustomTabEditorOpen
    ? customTabExpression.trim()
    : null
  const visibleContacts = contacts
    .filter((contact) => {
      if (customTabPreviewExpression !== null) {
        if (isMailingListContact(contact)) {
          return false
        }
        return customTabMatches(contact, customTabPreviewExpression)
      }
      if (activeCustomTab !== undefined) {
        if (isMailingListContact(contact)) {
          return false
        }
        return customTabMatches(contact, activeCustomTab.expression)
      }
      if (statusFilter === 'mailing_list') {
        return isMailingListContact(contact)
      }
      if (isMailingListContact(contact)) {
        return false
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
        contact.user_memo ?? '',
        contact.status,
        contact.kind ?? 'person',
        contact.sender_resolution_mode ?? 'self',
        isMailingListContact(contact) ? '' : contact.tags.join(' '),
        contact.mailing_list_recipient_expression ?? '',
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
            {mode === 'pending' ? (
              <AppLink href="/contacts">{t('contacts.heading')}</AppLink>
            ) : null}
            <AppLink href="/">{t('top.heading')}</AppLink>
          </nav>
        </header>

        {!shouldShowContactDetailFeedback && error !== null && (
          <p className="contact-error" role="alert">{error}</p>
        )}
        {!shouldShowContactDetailFeedback && notice !== null && (
          <p className="contact-notice">{notice}</p>
        )}

        {mode === 'pending' ? (
          <section aria-labelledby="pending-contacts-heading" className="contact-panel pending-workbench">
            <div className="section-heading">
              <h2 id="pending-contacts-heading">{t('contacts.unresolvedFrom.heading')}</h2>
              <span>{t('contacts.pending.count', { count: unresolvedFromAddresses.length })}</span>
            </div>
            <div className="contact-list">
              {unresolvedFromAddresses.map((item) => (
                <article className="pending-resolution-card" key={item.email_address_id}>
                  <div className="pending-info-panel">
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
                        placeholder={item.inferred_display_name}
                        value={
                          pendingDisplayNames[item.email_address] ??
                          item.inferred_display_name
                        }
                      />
                    </label>
                    <div>
                      <span>{t('contacts.emailAddress')}</span>
                      <p>{item.email_address}</p>
                    </div>
                    <div>
                      <span>{t('contacts.pending.snippet')}</span>
                      <p>
                        {item.latest_body_preview ??
                          item.latest_subject ??
                          t('contacts.noMessageBody')}
                      </p>
                    </div>
                    <p>
                      {item.latest_subject ?? 'メール本文の情報はまだありません。'}
                    </p>
                  </div>
                  <div className="pending-contact-actions">
                    <div className="pending-mail-meta">
                      <span>{item.latest_from_name ?? t('common.none')}</span>
                      <span>{item.latest_reply_to_address ?? t('contacts.pending.noReplyTo')}</span>
                    </div>
                    <div className="pending-toggle-field">
                      <span>{t('contacts.pending.decision')}</span>
                    <div className="pending-contact-buttons">
                      <button
                        aria-pressed={pendingDecision(item) === 'active'}
                        disabled={busyEmailAddress === item.email_address}
                        onClick={() => handlePendingDecision(item, 'active')}
                        type="button"
                      >
                        {t('common.active')}
                      </button>
                      <button
                        aria-pressed={pendingDecision(item) === 'skipped'}
                        disabled={busyEmailAddress === item.email_address}
                        onClick={() => handlePendingDecision(item, 'skipped')}
                        type="button"
                      >
                        {t('common.skipped')}
                      </button>
                    </div>
                    </div>
                    <div className="pending-toggle-field">
                      <span>{t('contacts.kind.label')}</span>
                    <div className="pending-contact-buttons">
                      <button
                        aria-pressed={pendingKind(item) === 'person'}
                        onClick={() =>
                          setPendingKinds((currentKinds) => ({
                            ...currentKinds,
                            [item.email_address]: 'person',
                          }))
                        }
                        type="button"
                      >
                        {t('contacts.kind.person')}
                      </button>
                      <button
                        aria-pressed={pendingKind(item) === 'mailing_list'}
                        onClick={() =>
                          setPendingKinds((currentKinds) => ({
                            ...currentKinds,
                            [item.email_address]: 'mailing_list',
                          }))
                        }
                        type="button"
                      >
                        {t('contacts.kind.mailingList')}
                      </button>
                    </div>
                    </div>
                    <div
                      className={`pending-toggle-field${
                        pendingKind(item) !== 'mailing_list'
                          ? ' pending-toggle-field-disabled'
                          : ''
                      }`}
                    >
                      <span>{t('contacts.pending.replyTarget')}</span>
                    <div className="pending-contact-buttons">
                      <button
                        aria-pressed={
                          pendingKind(item) === 'mailing_list' &&
                          pendingSenderResolution(item) === 'self'
                        }
                        disabled={pendingKind(item) !== 'mailing_list'}
                        onClick={() =>
                          setPendingSenderResolutions((currentResolutions) => ({
                            ...currentResolutions,
                            [item.email_address]: 'self',
                          }))
                        }
                        type="button"
                      >
                        {t('contacts.pending.sender.self')}
                      </button>
                      <button
                        aria-pressed={
                          pendingKind(item) === 'mailing_list' &&
                          pendingSenderResolution(item) === 'reply_to'
                        }
                        disabled={pendingKind(item) !== 'mailing_list'}
                        onClick={() =>
                          setPendingSenderResolutions((currentResolutions) => ({
                            ...currentResolutions,
                            [item.email_address]: 'reply_to',
                          }))
                        }
                        type="button"
                      >
                        {t('contacts.pending.sender.replyTo')}
                      </button>
                    </div>
                    </div>
                    <button
                      aria-label={t('contacts.createFor', {
                        email: item.email_address,
                      })}
                      className="pending-create-button"
                      disabled={busyEmailAddress === item.email_address}
                      onClick={() =>
                        handleCreatePendingContact(
                          item,
                          pendingDecision(item),
                          pendingKind(item),
                          pendingSenderResolution(item),
                        )
                      }
                      type="button"
                    >
                      {t('contacts.create')}
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
                    onClick={() => {
                      setIsCreateOpen((isOpen) => !isOpen)
                      setIsMergeToolOpen(false)
                    }}
                    type="button"
                  >
                    {t('contacts.new')}
                  </button>
                  <button
                    aria-expanded={isMergeToolOpen}
                    onClick={() => {
                      setIsMergeToolOpen((isOpen) => !isOpen)
                      setIsCreateOpen(false)
                    }}
                    type="button"
                  >
                    {t('contacts.merge.tool')}
                  </button>
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
                  <button disabled={isSubmitting} type="submit">
                    {t('contacts.create')}
                  </button>
                </form>
              )}
              {isMergeToolOpen && (
                <form className="contact-merge-tool-form" onSubmit={handleMergeContactsTool}>
                  <div className="section-heading">
                    <h2 id="merge-contact-heading">{t('contacts.merge.tool')}</h2>
                  </div>
                  <label>
                    <span>{t('contacts.merge.source')}</span>
                    <input
                      aria-label={t('contacts.merge.source')}
                      list="merge-source-suggestions"
                      onChange={(event) => setMergeSourceQuery(event.target.value)}
                      placeholder={t('contacts.merge.select')}
                      value={mergeSourceQuery}
                    />
                    <datalist id="merge-source-suggestions">
                      {mergeToolContacts.map((contact) => (
                        <option key={contact.id} value={contact.display_name} />
                      ))}
                    </datalist>
                  </label>
                  <label>
                    <span>{t('contacts.merge.target')}</span>
                    <input
                      aria-label={t('contacts.merge.target')}
                      list="merge-target-suggestions"
                      onChange={(event) =>
                        setMergeDestinationQuery(event.target.value)
                      }
                      placeholder={t('contacts.merge.select')}
                      value={mergeDestinationQuery}
                    />
                    <datalist id="merge-target-suggestions">
                      {mergeDestinationContacts.map((contact) => (
                        <option key={contact.id} value={contact.display_name} />
                      ))}
                    </datalist>
                  </label>
                  <button
                    disabled={
                      isSubmitting ||
                      mergeSourceContact === undefined ||
                      mergeDestinationContact === undefined ||
                      mergeSourceContact.id === mergeDestinationContact.id
                    }
                    type="submit"
                  >
                    {t('contacts.merge.execute')}
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
                  <button
                    aria-controls="contact-list-panel"
                    aria-selected={
                      !isCustomTabEditorOpen &&
                      activeCustomTabId === null &&
                      statusFilter === 'mailing_list'
                    }
                    id="contact-list-tab-mailing_list"
                    onClick={() => handleStatusTabClick('mailing_list')}
                    role="tab"
                    type="button"
                  >
                    {t('contacts.kind.mailingList')}
                  </button>
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
                          placeholder="TsukubaLab"
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
                      const fixedImportance = contact.mail_importance_rule_importance
                      return (
                        <article
                          className={`contact-row contact-expandable-row${
                            isExpanded ? ' contact-row-expanded' : ''
                          }${
                            contact.mail_importance_rule_action === 'fixed' &&
                            fixedImportance != null
                              ? ` contact-fixed-importance mail-priority-${fixedImportance}`
                              : ''
                          }`}
                          id={`contact-row-${contact.id}`}
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
                                    src={contact.avatar_url ?? defaultAvatarUrlForContact(contact)}
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
                                {isMailingListContact(contact) ? (
                                  <>
                                    <span>{contact.status}</span>
                                    <span>
                                      {contact.mailing_list_recipient_expression ??
                                        t('common.none')}
                                    </span>
                                    <span>
                                      {t(
                                        (contact.sender_resolution_mode ?? 'self') ===
                                          'reply_to'
                                          ? 'contacts.senderResolution.short.replyTo'
                                          : 'contacts.senderResolution.short.self',
                                      )}
                                    </span>
                                  </>
                                ) : (
                                  <>
                                    <span>{contact.status}</span>
                                    {contact.tags.map((tag) => (
                                      <span key={tag}>{tag}</span>
                                    ))}
                                  </>
                                )}
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
                            <div
                              className={`contact-detail-card${
                                selectedIsMailingList ? ' mailing-list-detail-card' : ''
                              }`}
                            >
                              <div className="section-heading contact-detail-heading">
                                <h2 id="contact-detail-heading">
                                  {selectedIsMailingList
                                    ? t('contacts.mailingList.detail.heading')
                                    : t('contacts.detail.heading')}
                                </h2>
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
                                <form
                                  className={`contact-detail-form${
                                    selectedIsMailingList
                                      ? ' mailing-list-detail-form'
                                      : ''
                                  }`}
                                  id="contact-detail-edit-form"
                                  onSubmit={handleUpdateContact}
                                >
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
                                  {detailKind === 'mailing_list' && (
                                    <label className="contact-detail-secondary">
                                      <span>{t('contacts.senderResolution.label')}</span>
                                      <select
                                        aria-label={t(
                                          'contacts.senderResolution.label',
                                        )}
                                        onChange={(event) =>
                                          setDetailSenderResolutionMode(
                                            event.target.value as SenderResolutionMode,
                                          )
                                        }
                                        value={detailSenderResolutionMode}
                                      >
                                        <option value="self">
                                          {t('contacts.senderResolution.self')}
                                        </option>
                                        <option value="reply_to">
                                          {t('contacts.senderResolution.replyTo')}
                                        </option>
                                      </select>
                                    </label>
                                  )}
                                  <div className="contact-detail-primary contact-detail-memo-field">
                                    <label>
                                      <span>{t('contacts.userMemo')}</span>
                                      <textarea
                                        aria-label={t('contacts.detail.userMemo')}
                                        onChange={(event) => setDetailMemo(event.target.value)}
                                        value={detailMemo}
                                      />
                                    </label>
                                  </div>
                                  <div className="contact-detail-secondary contact-detail-tags-field">
                                    {selectedIsMailingList ? (
                                      <label>
                                        <span>{t('contacts.mailingList.recipientExpression')}</span>
                                        <input
                                          aria-label={t(
                                            'contacts.mailingList.recipientExpression',
                                          )}
                                          onChange={(event) =>
                                            setDetailMailingListRecipientExpression(
                                              event.target.value,
                                            )
                                          }
                                          value={detailMailingListRecipientExpression}
                                        />
                                      </label>
                                    ) : (
                                      <label>
                                        <span>{t('contacts.tags')}</span>
                                        <input
                                          aria-label={t('contacts.detail.tags')}
                                          onChange={(event) => setDetailTags(event.target.value)}
                                          value={detailTags}
                                        />
                                      </label>
                                    )}
                                    <label>
                                      <span>{t('contacts.importanceRule.label')}</span>
                                      <select
                                        aria-label={t('contacts.importanceRule.label')}
                                        onChange={(event) =>
                                          setDetailMailImportanceRuleAction(
                                            event.target
                                              .value as ContactMailImportanceRuleAction,
                                          )
                                        }
                                        value={detailMailImportanceRuleAction}
                                      >
                                        <option value="llm">
                                          {t('contacts.importanceRule.llm')}
                                        </option>
                                        <option value="fixed">
                                          {t('contacts.importanceRule.fixed')}
                                        </option>
                                        <option value="llm_with_instruction">
                                          {t('contacts.importanceRule.llmWithInstruction')}
                                        </option>
                                      </select>
                                    </label>
                                    {detailMailImportanceRuleAction === 'fixed' && (
                                      <label>
                                        <span>{t('contacts.importanceRule.value')}</span>
                                        <select
                                          aria-label={t('contacts.importanceRule.value')}
                                          onChange={(event) =>
                                            setDetailMailImportanceRuleImportance(
                                              event.target
                                                .value as ContactMailImportanceRuleValue,
                                            )
                                          }
                                          value={detailMailImportanceRuleImportance}
                                        >
                                          {(['pinned', 'high', 'middle', 'low'] as const).map(
                                            (importance) => (
                                              <option key={importance} value={importance}>
                                                {importance}
                                              </option>
                                            ),
                                          )}
                                        </select>
                                      </label>
                                    )}
                                    {detailMailImportanceRuleAction ===
                                      'llm_with_instruction' && (
                                      <label>
                                        <span>{t('contacts.importanceRule.instruction')}</span>
                                        <textarea
                                          aria-label={t(
                                            'contacts.importanceRule.instruction',
                                          )}
                                          onChange={(event) =>
                                            setDetailMailImportanceRuleInstruction(
                                              event.target.value,
                                            )
                                          }
                                          value={detailMailImportanceRuleInstruction}
                                        />
                                      </label>
                                    )}
                                    <div className="contact-related-cases contact-related-cases-compact">
                                      <h3>{t('contacts.relatedCases.heading')}</h3>
                                      <p>{t('contacts.relatedCases.empty')}</p>
                                    </div>
                                    {!selectedIsMailingList && (
                                      <div className="contact-ai-memo-readonly">
                                        <span>{t('contacts.aiMemo')}</span>
                                        <p>
                                          {selectedContact.ai_memo ??
                                            t('contacts.detail.noAiMemo')}
                                        </p>
                                      </div>
                                    )}
                                  </div>
                                </form>
                              ) : (
                                <div className="contact-detail-summary contact-detail-primary">
                                  {selectedIsMailingList && (
                                    <div className="mailing-list-memo-summary">
                                      <span>{t('contacts.userMemo')}</span>
                                      <p>{selectedContact.user_memo ?? t('contacts.detail.noMemo')}</p>
                                    </div>
                                  )}
                                  {selectedIsMailingList && (
                                    <div>
                                      <span>{t('contacts.senderResolution.label')}</span>
                                      <p>
                                        {t(
                                          (selectedContact.sender_resolution_mode ??
                                            'self') === 'reply_to'
                                            ? 'contacts.senderResolution.replyTo'
                                            : 'contacts.senderResolution.self',
                                        )}
                                      </p>
                                    </div>
                                  )}
                                  {!selectedIsMailingList && (
                                  <div>
                                    <span>{t('contacts.userMemo')}</span>
                                    <p>{selectedContact.user_memo ?? t('contacts.detail.noMemo')}</p>
                                  </div>
                                  )}
                                  {!selectedIsMailingList && (
                                    <div>
                                      <span>{t('contacts.aiMemo')}</span>
                                      <p>
                                        {selectedContact.ai_memo ??
                                          t('contacts.detail.noAiMemo')}
                                      </p>
                                    </div>
                                  )}
                                  {selectedIsMailingList && (
                                    <div>
                                      <span>{t('contacts.mailingList.recipientExpression')}</span>
                                      <p>
                                        {selectedContact.mailing_list_recipient_expression ??
                                          t('common.none')}
                                      </p>
                                    </div>
                                  )}
                                  {selectedIsMailingList && (
                                    <div className="mailing-list-related-summary">
                                      <span>{t('contacts.relatedCases.heading')}</span>
                                      <p>{t('contacts.relatedCases.empty')}</p>
                                    </div>
                                  )}
                                </div>
                              )}
                              {!isContactDetailEditing && !selectedIsMailingList && (
                                <div className="contact-detail-summary contact-detail-secondary">
                                  <div className="contact-importance-rule-summary">
                                    <span>{t('contacts.importanceRule.label')}</span>
                                    <p>
                                      {(selectedContact.mail_importance_rule_action ??
                                        'llm') === 'fixed'
                                        ? `${t('contacts.importanceRule.fixed')}: ${
                                            selectedContact.mail_importance_rule_importance ??
                                            'high'
                                          }`
                                        : (selectedContact.mail_importance_rule_action ??
                                            'llm') === 'llm_with_instruction'
                                          ? t('contacts.importanceRule.llmWithInstruction')
                                          : t('contacts.importanceRule.llm')}
                                    </p>
                                    {(selectedContact.mail_importance_rule_action ??
                                      'llm') === 'llm_with_instruction' &&
                                      selectedContact.mail_importance_rule_instruction !==
                                        null &&
                                      selectedContact.mail_importance_rule_instruction !==
                                        undefined &&
                                      selectedContact.mail_importance_rule_instruction !== '' && (
                                        <p className="contact-rule-instruction">
                                          {selectedContact.mail_importance_rule_instruction}
                                        </p>
                                      )}
                                  </div>
                                </div>
                              )}
                              {!selectedIsMailingList && (
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
                                      {selectedIsMailingList && (
                                        <span title={t('contacts.email.mailingListFixed')}>
                                          {t('contacts.email.mailingListFixed')}
                                        </span>
                                      )}
                                      {isContactDetailEditing &&
                                        !selectedIsMailingList &&
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
                                        !selectedIsMailingList &&
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
                                        !selectedIsMailingList &&
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
                                        !selectedIsMailingList &&
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
                                {isContactDetailEditing &&
                                  (!selectedIsMailingList ||
                                    selectedContact.email_addresses.length === 0) && (
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
                              )}
                              {isContactDetailEditing && (
                                <div className="contact-detail-edit-buttons contact-detail-secondary">
                                  <button
                                    disabled
                                    title={t('contacts.avatar.unimplemented')}
                                    type="button"
                                  >
                                    {t('contacts.avatar.update')}
                                  </button>
                                  <button
                                    disabled={isSubmitting}
                                    form="contact-detail-edit-form"
                                    type="submit"
                                  >
                                    {t('contacts.detail.save')}
                                  </button>
                                  <button
                                    disabled={isSubmitting || !canDeleteSelectedContact}
                                    onClick={handleDeleteContact}
                                    title={
                                      !canDeleteSelectedContact
                                        ? t('contacts.detail.deleteUnavailable')
                                        : undefined
                                    }
                                    type="button"
                                  >
                                    {t('contacts.detail.delete')}
                                  </button>
                                </div>
                              )}
                              {!isContactDetailEditing && !selectedIsMailingList && (
                                <div className="contact-related-cases contact-detail-secondary">
                                <h3>{t('contacts.relatedCases.heading')}</h3>
                                <p>{t('contacts.relatedCases.empty')}</p>
                                </div>
                              )}
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
