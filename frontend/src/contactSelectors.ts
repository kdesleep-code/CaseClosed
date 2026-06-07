import type { Contact } from './phase3Api'
import type { CaseItem, CaseStakeholder } from './phase7Api'

export type ContactSelectorCaseContext = {
  case: CaseItem
  stakeholders: CaseStakeholder[]
}

export type ContactSelectorSuggestion = {
  label: string
  value: string
}

function normalizeToken(value: string) {
  return value.trim().toLowerCase()
}

function activeContactEmailAddresses(contact: Contact) {
  return contact.email_addresses.filter(
    (emailAddress) => (emailAddress.status ?? 'active') === 'active',
  )
}

function primaryActiveEmailAddress(contact: Contact) {
  return (
    activeContactEmailAddresses(contact).find((emailAddress) => emailAddress.is_primary) ??
    activeContactEmailAddresses(contact)[0] ??
    null
  )
}

export function splitContactSelectorList(value: string) {
  return value
    .split(/[,\n;]/)
    .map((item) => item.trim())
    .filter((item) => item !== '')
}

export function contactSelectorTerms(selector: string) {
  return selector
    .trim()
    .replace(/^\{|\}$/g, '')
    .split('&')
    .map((term) => term.trim())
    .filter(Boolean)
}

function contactMatchesTagExpression(contact: Contact, selector: string) {
  const terms = contactSelectorTerms(selector)
  if (terms.length === 0) {
    return false
  }
  const tags = new Set(contact.tags.map(normalizeToken))
  return terms.every((term) => {
    if (term.startsWith('!')) {
      return !tags.has(normalizeToken(term.slice(1)))
    }
    return tags.has(normalizeToken(term))
  })
}

function isLikelyEmailAddress(value: string) {
  return /@/.test(value)
}

function contactMatchesIdentity(contact: Contact, selector: string) {
  const normalized = normalizeToken(selector)
  return (
    normalizeToken(contact.display_name) === normalized ||
    contact.email_addresses.some(
      (emailAddress) => normalizeToken(emailAddress.email_address) === normalized,
    )
  )
}

function caseRoleSelectorParts(selector: string) {
  const match = selector.trim().match(/^case:([^:]+):([^:]+)$/i)
  if (match === null) {
    return null
  }
  return {
    caseName: normalizeToken(match[1] ?? ''),
    role: normalizeToken(match[2] ?? ''),
  }
}

function uniqueCaseRoles(context: ContactSelectorCaseContext) {
  const roles = Array.from(
    new Set(
      context.stakeholders
        .map((stakeholder) => stakeholder.role.trim())
        .filter((role) => role !== ''),
    ),
  ).sort((left, right) => left.localeCompare(right))
  return context.stakeholders.length === 0 ? roles : ['ALL', ...roles]
}

export function caseRoleSelectorSuggestions(
  value: string,
  caseContexts: ContactSelectorCaseContext[] = [],
): ContactSelectorSuggestion[] {
  const selectors = splitContactSelectorList(value)
  const activeSelector = selectors[selectors.length - 1] ?? value.trim()
  const trimmedActiveSelector = activeSelector.trim()
  if (!trimmedActiveSelector.toLowerCase().startsWith('case:')) {
    return []
  }

  const selectorBody = trimmedActiveSelector.slice('case:'.length)
  const colonIndex = selectorBody.indexOf(':')
  if (colonIndex < 0) {
    const normalizedCaseQuery = normalizeToken(selectorBody)
    return caseContexts
      .filter(
        (context) =>
          normalizeToken(context.case.name).startsWith(normalizedCaseQuery) ||
          normalizeToken(context.case.id).startsWith(normalizedCaseQuery),
      )
      .map((context) => ({
        label: context.case.name,
        value: `Case:${context.case.name}:`,
      }))
      .slice(0, 8)
  }

  const caseQuery = normalizeToken(selectorBody.slice(0, colonIndex))
  const roleQuery = normalizeToken(selectorBody.slice(colonIndex + 1))
  return caseContexts
    .filter(
      (context) =>
        normalizeToken(context.case.name) === caseQuery ||
        normalizeToken(context.case.id) === caseQuery,
    )
    .flatMap((context) =>
      uniqueCaseRoles(context)
        .filter((role) => normalizeToken(role).startsWith(roleQuery))
        .map((role) => ({
          label: role,
          value: `Case:${context.case.name}:${role}`,
        })),
    )
    .slice(0, 8)
}

export function replaceLastContactSelector(value: string, nextSelector: string) {
  const match = value.match(/^(.*?)([^,;\n]*)$/s)
  if (match === null) {
    return nextSelector
  }
  const prefix = match[1] ?? ''
  return `${prefix}${nextSelector}`
}

function resolveCaseRoleSelector(
  selector: string,
  contacts: Contact[],
  caseContexts: ContactSelectorCaseContext[],
) {
  const parts = caseRoleSelectorParts(selector)
  if (parts === null || parts.caseName === '' || parts.role === '') {
    return []
  }

  const contactById = new Map(contacts.map((contact) => [contact.id, contact]))
  const selectedContacts: Contact[] = []
  const seen = new Set<string>()
  for (const context of caseContexts) {
    if (
      normalizeToken(context.case.name) !== parts.caseName &&
      normalizeToken(context.case.id) !== parts.caseName
    ) {
      continue
    }
    for (const stakeholder of context.stakeholders) {
      if (parts.role !== 'all' && normalizeToken(stakeholder.role) !== parts.role) {
        continue
      }
      const contact = contactById.get(stakeholder.contact_id)
      if (contact === undefined || seen.has(contact.id)) {
        continue
      }
      seen.add(contact.id)
      selectedContacts.push(contact)
    }
  }
  return selectedContacts
}

export function resolveContactSelector(
  selector: string,
  contacts: Contact[],
  caseContexts: ContactSelectorCaseContext[] = [],
) {
  const trimmed = selector.trim()
  if (trimmed === '' || isLikelyEmailAddress(trimmed)) {
    return []
  }

  const caseRoleContacts = resolveCaseRoleSelector(trimmed, contacts, caseContexts)
  if (caseRoleContacts.length > 0) {
    return caseRoleContacts
  }

  const exactContact = contacts.find((contact) => contactMatchesIdentity(contact, trimmed))
  if (exactContact !== undefined) {
    return [exactContact]
  }

  return contacts.filter((contact) => contactMatchesTagExpression(contact, trimmed))
}

export function resolveContactSelectorList(value: string, contacts: Contact[]) {
  const selectedContacts: Contact[] = []
  const seen = new Set<string>()
  for (const selector of splitContactSelectorList(value)) {
    for (const contact of resolveContactSelector(selector, contacts)) {
      if (seen.has(contact.id)) {
        continue
      }
      seen.add(contact.id)
      selectedContacts.push(contact)
    }
  }
  return selectedContacts
}

export function resolveContactSelectorListWithCases(
  value: string,
  contacts: Contact[],
  caseContexts: ContactSelectorCaseContext[] = [],
) {
  const selectedContacts: Contact[] = []
  const seen = new Set<string>()
  for (const selector of splitContactSelectorList(value)) {
    for (const contact of resolveContactSelector(selector, contacts, caseContexts)) {
      if (seen.has(contact.id)) {
        continue
      }
      seen.add(contact.id)
      selectedContacts.push(contact)
    }
  }
  return selectedContacts
}

export function describeContactSelectorList(
  value: string,
  contacts: Contact[],
  caseContexts: ContactSelectorCaseContext[] = [],
) {
  return splitContactSelectorList(value)
    .map((selector) => ({
      selector,
      contacts: resolveContactSelector(selector, contacts, caseContexts),
    }))
    .filter((item) => item.selector.trim() !== '')
}

export function resolveRecipientAddressList(
  value: string,
  contacts: Contact[],
  caseContexts: ContactSelectorCaseContext[] = [],
) {
  const addresses: string[] = []
  const seen = new Set<string>()
  for (const selector of splitContactSelectorList(value)) {
    const resolvedContacts = resolveContactSelector(selector, contacts, caseContexts)
    const resolvedAddresses =
      resolvedContacts.length === 0
        ? [selector]
        : resolvedContacts
            .map(primaryActiveEmailAddress)
            .filter((emailAddress) => emailAddress !== null)
            .map((emailAddress) => emailAddress.email_address)
    for (const address of resolvedAddresses) {
      const normalized = normalizeToken(address)
      if (normalized === '' || seen.has(normalized)) {
        continue
      }
      seen.add(normalized)
      addresses.push(address)
    }
  }
  return addresses
}

export function resolvedRecipientAddressText(value: string, contacts: Contact[]) {
  return resolveRecipientAddressList(value, contacts).join(', ')
}

export function resolvedRecipientAddressTextWithCases(
  value: string,
  contacts: Contact[],
  caseContexts: ContactSelectorCaseContext[] = [],
) {
  return resolveRecipientAddressList(value, contacts, caseContexts).join(', ')
}
