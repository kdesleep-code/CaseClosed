import { useEffect, useMemo, useState } from 'react'
import defaultContactAvatarUrl from './assets/default-contact-avatar.svg'
import settingsGearIconUrl from './assets/settings-gear.svg'
import { t } from './i18n'
import { TopNav } from './navigation'
import { listContacts } from './phase3Api'
import type { Contact } from './phase3Api'
import { getProfile, updateProfile } from './profileApi'
import type { UserProfile } from './profileApi'

type ProfileTextField = {
  key: keyof UserProfile
  label: string
  multiline?: boolean
}

const emptyProfile: UserProfile = {
  display_name: '',
  primary_email: '',
  email_aliases: [],
  affiliation: '',
  academic_title: '',
  lab_or_group: '',
  research_fields: '',
  teaching_responsibilities: '',
  committee_roles: '',
  administrative_roles: '',
  supervised_people: '',
  collaborators: '',
  important_projects: '',
  priority_keywords: '',
  low_priority_keywords: '',
  important_senders_or_domains: '',
  expected_response_policy: '',
  unavailable_times: '',
  default_reply_language: 'japanese',
  llm_self_description: '',
  mail_importance_notes: '',
  updated_at: null,
}

const identityFields: ProfileTextField[] = [
  { key: 'display_name', label: 'Name' },
  { key: 'primary_email', label: 'Primary email' },
  { key: 'affiliation', label: 'Affiliation' },
  { key: 'academic_title', label: 'Academic title' },
  { key: 'lab_or_group', label: 'Lab / group' },
]

const academicContextFields: ProfileTextField[] = [
  { key: 'research_fields', label: 'Research fields', multiline: true },
]

const academicContextListFields: ProfileTextField[] = [
  {
    key: 'teaching_responsibilities',
    label: 'Teaching responsibilities',
    multiline: true,
  },
  { key: 'committee_roles', label: 'Committee roles', multiline: true },
  { key: 'administrative_roles', label: 'Administrative roles', multiline: true },
  { key: 'important_projects', label: 'Important projects', multiline: true },
]

function describeError(error: unknown) {
  return error instanceof Error ? error.message : t('app.requestFailed')
}

function formatDateTime(value: string | null) {
  if (value === null) {
    return t('time.unavailable')
  }
  return value.replace('T', ' ').replace('+09:00', ' JST')
}

function textValue(profile: UserProfile, field: keyof UserProfile) {
  const value = profile[field]
  return typeof value === 'string' ? value : ''
}

function hasValue(value: string | string[]) {
  return Array.isArray(value)
    ? value.length > 0
    : value.trim() !== ''
}

function splitEmailAliasInput(value: string) {
  return value
    .split(/[\r\n,;]+/)
    .map((item) => item.trim())
    .filter((item) => item !== '')
}

function splitProfileListInput(value: string) {
  return value
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter((item) => item !== '')
}

function joinProfileListItems(items: string[]) {
  return items
    .map((item) => item.trim())
    .filter((item) => item !== '')
    .join('\n')
}

function splitProfileListEditorInput(value: string) {
  return value === '' ? [''] : value.split(/\r?\n/)
}

function joinProfileListEditorItems(items: string[]) {
  return items.map((item) => item.trim()).join('\n')
}

function normalizeProfileListFields(profile: UserProfile) {
  function normalizedField(field: keyof UserProfile) {
    return joinProfileListItems(
      splitProfileListEditorInput(textValue(profile, field)),
    )
  }
  return {
    ...profile,
    teaching_responsibilities: normalizedField('teaching_responsibilities'),
    committee_roles: normalizedField('committee_roles'),
    administrative_roles: normalizedField('administrative_roles'),
    important_projects: normalizedField('important_projects'),
  }
}

function contactHasTag(contact: Contact, tag: string) {
  return contact.tags.some(
    (contactTag) => contactTag.trim().toLowerCase() === tag,
  )
}

function sortedContactsByName(contacts: Contact[]) {
  return [...contacts].sort((firstContact, secondContact) =>
    firstContact.display_name.localeCompare(secondContact.display_name),
  )
}

function ProfileFieldList({
  fields,
  profile,
}: {
  fields: ProfileTextField[]
  profile: UserProfile
}) {
  return (
    <dl className="profile-field-list">
      {fields.map((field) => {
        const value = textValue(profile, field.key)
        return (
          <div key={field.key}>
            <dt>{field.label}</dt>
            <dd className={!hasValue(value) ? 'is-empty' : undefined}>
              {hasValue(value) ? value : t('profile.emptyValue')}
            </dd>
          </div>
        )
      })}
    </dl>
  )
}

function ProfileContactGroup({
  contacts,
  title,
}: {
  contacts: Contact[]
  title: string
}) {
  return (
    <details className="profile-contact-group">
      <summary>
        <span>{title}</span>
        <strong>{contacts.length}</strong>
      </summary>
      {contacts.length > 0 ? (
        <ul>
          {contacts.map((contact) => (
            <li key={contact.id}>
              <img
                alt=""
                aria-hidden="true"
                src={contact.avatar_url ?? defaultContactAvatarUrl}
              />
              <span>{contact.display_name}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p>{t('profile.contactGroups.empty')}</p>
      )}
    </details>
  )
}

function ProfileBulletGroup({
  field,
  profile,
}: {
  field: ProfileTextField
  profile: UserProfile
}) {
  const items = splitProfileListInput(textValue(profile, field.key))
  return (
    <details className="profile-bullet-group">
      <summary>
        <span>{field.label}</span>
        <strong>{items.length}</strong>
      </summary>
      {items.length > 0 ? (
        <ul>
          {items.map((item, index) => (
            <li key={`${field.key}-${index}`}>{item}</li>
          ))}
        </ul>
      ) : (
        <p>{t('profile.emptyValue')}</p>
      )}
    </details>
  )
}

function ProfileBulletEditor({
  field,
  onChange,
  profile,
}: {
  field: ProfileTextField
  onChange: (nextProfile: UserProfile) => void
  profile: UserProfile
}) {
  const visibleItems = splitProfileListEditorInput(textValue(profile, field.key))

  function updateItem(index: number, value: string) {
    const nextItems = [...visibleItems]
    nextItems[index] = value
    onChange({ ...profile, [field.key]: joinProfileListEditorItems(nextItems) })
  }

  function addItem() {
    onChange({
      ...profile,
      [field.key]: joinProfileListEditorItems([...visibleItems, '']),
    })
  }

  function removeItem(index: number) {
    onChange({
      ...profile,
      [field.key]: joinProfileListItems(visibleItems.filter((_, itemIndex) => itemIndex !== index)),
    })
  }

  return (
    <fieldset className="profile-bullet-editor">
      <legend>{field.label}</legend>
      {visibleItems.map((item, index) => (
        <div key={`${field.key}-${index}`}>
          <input
            aria-label={`${field.label} ${index + 1}`}
            type="text"
            value={item}
            onChange={(event) => updateItem(index, event.target.value)}
          />
          <button
            aria-label={t('profile.listItem.remove', {
              label: field.label,
              index: String(index + 1),
            })}
            onClick={() => removeItem(index)}
            type="button"
          >
            -
          </button>
        </div>
      ))}
      <button onClick={addItem} type="button">
        {t('profile.listItem.add')}
      </button>
    </fieldset>
  )
}

function ProfileEditor({
  aliasInput,
  draft,
  isSaving,
  onAliasInputChange,
  onCancel,
  onChange,
  onSave,
}: {
  aliasInput: string
  draft: UserProfile
  isSaving: boolean
  onAliasInputChange: (value: string) => void
  onCancel: () => void
  onChange: (nextProfile: UserProfile) => void
  onSave: () => void
}) {
  function updateTextField(field: keyof UserProfile, value: string) {
    onChange({ ...draft, [field]: value })
  }

  function fieldControl(field: ProfileTextField) {
    const value = textValue(draft, field.key)
    if (field.multiline) {
      return (
        <textarea
          value={value}
          onChange={(event) => updateTextField(field.key, event.target.value)}
        />
      )
    }
    return (
      <input
        type="text"
        value={value}
        onChange={(event) => updateTextField(field.key, event.target.value)}
      />
    )
  }

  return (
    <div className="profile-editor">
      <section>
        <h2>{t('profile.section.identity')}</h2>
        <div className="profile-form-grid">
          {identityFields.map((field) => (
            <label key={field.key}>
              <span>{field.label}</span>
              {fieldControl(field)}
            </label>
          ))}
          <label className="profile-form-wide">
            <span>{t('profile.emailAliases')}</span>
            <textarea
              value={aliasInput}
              onChange={(event) => onAliasInputChange(event.target.value)}
              placeholder={t('profile.emailAliasesPlaceholder')}
            />
          </label>
          <label>
            <span>{t('profile.defaultReplyLanguage')}</span>
            <select
              value={draft.default_reply_language}
              onChange={(event) =>
                onChange({
                  ...draft,
                  default_reply_language:
                    event.target.value === 'english' ? 'english' : 'japanese',
                })
              }
            >
              <option value="japanese">{t('profile.languageJapanese')}</option>
              <option value="english">{t('profile.languageEnglish')}</option>
            </select>
          </label>
        </div>
      </section>
      <section>
        <h2>{t('profile.section.academicContext')}</h2>
        <div className="profile-form-grid">
          {academicContextFields.map((field) => (
            <label className="profile-form-wide" key={field.key}>
              <span>{field.label}</span>
              {fieldControl(field)}
            </label>
          ))}
          {academicContextListFields.map((field) => (
            <ProfileBulletEditor
              field={field}
              key={field.key}
              onChange={onChange}
              profile={draft}
            />
          ))}
        </div>
      </section>
      <div className="profile-editor-actions">
        <button disabled={isSaving} onClick={onCancel} type="button">
          {t('common.cancel')}
        </button>
        <button disabled={isSaving} onClick={onSave} type="button">
          {isSaving ? t('profile.saving') : t('profile.save')}
        </button>
      </div>
    </div>
  )
}

export default function ProfileView() {
  const [profile, setProfile] = useState<UserProfile>(emptyProfile)
  const [draft, setDraft] = useState<UserProfile>(emptyProfile)
  const [contacts, setContacts] = useState<Contact[]>([])
  const [aliasInput, setAliasInput] = useState('')
  const [isEditing, setIsEditing] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [feedback, setFeedback] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let isActive = true
    setIsLoading(true)
    Promise.all([getProfile(), listContacts()])
      .then(([loadedProfile, loadedContacts]) => {
        if (!isActive) return
        setProfile(loadedProfile)
        setDraft(loadedProfile)
        setContacts(loadedContacts)
        setAliasInput(loadedProfile.email_aliases.join(', '))
        setError(null)
      })
      .catch((loadError: unknown) => {
        if (!isActive) return
        setError(describeError(loadError))
      })
      .finally(() => {
        if (!isActive) return
        setIsLoading(false)
      })
    return () => {
      isActive = false
    }
  }, [])

  const ownedEmails = useMemo(
    () =>
      [profile.primary_email, ...profile.email_aliases].filter(
        (address) => address.trim() !== '',
      ),
    [profile.email_aliases, profile.primary_email],
  )
  const supervisedContacts = useMemo(
    () =>
      sortedContactsByName(
        contacts.filter((contact) =>
          contactHasTag(contact, 'supervised-student'),
        ),
      ),
    [contacts],
  )
  const collaboratorContacts = useMemo(
    () =>
      sortedContactsByName(
        contacts.filter((contact) => contactHasTag(contact, 'collaborator')),
      ),
    [contacts],
  )

  function openSettings() {
    setDraft(profile)
    setAliasInput(profile.email_aliases.join(', '))
    setFeedback(null)
    setError(null)
    setIsEditing(true)
  }

  async function handleSettingsButton() {
    if (!isEditing) {
      openSettings()
      return
    }
    if (isSaving) {
      return
    }
    if (!window.confirm(t('profile.confirmSaveAndClose'))) {
      return
    }
    await saveProfile()
  }

  function cancelEditing() {
    setDraft(profile)
    setAliasInput(profile.email_aliases.join(', '))
    setIsEditing(false)
  }

  async function saveProfile() {
    setIsSaving(true)
    setFeedback(null)
    setError(null)
    try {
      const savedProfile = await updateProfile({
        ...normalizeProfileListFields(draft),
        email_aliases: splitEmailAliasInput(aliasInput),
      })
      setProfile(savedProfile)
      setDraft(savedProfile)
      setAliasInput(savedProfile.email_aliases.join(', '))
      setIsEditing(false)
      setFeedback(t('profile.saved'))
    } catch (saveError) {
      setError(describeError(saveError))
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <main className="app-shell">
      <div className="case-shell profile-shell">
        <header className="maintenance-header">
          <div>
            <p>{t('app.name')}</p>
            <h1>{t('profile.heading')}</h1>
          </div>
          <TopNav
            ariaLabelKey="profile.navigation"
            items={[
              { href: '/', labelKey: 'top.heading' },
              { href: '/settings', labelKey: 'nav.settings' },
              { href: '/maintenance', labelKey: 'nav.maintenance' },
              { href: '/logs', labelKey: 'nav.logs' },
            ]}
          />
        </header>

        <section className="profile-card">
          <header className="profile-card-header">
            <div>
              <h2>{t('profile.overview')}</h2>
              <p>{t('profile.updatedAt', { value: formatDateTime(profile.updated_at) })}</p>
            </div>
            <button
              aria-expanded={isEditing}
              aria-label={t('profile.settings')}
              className="case-icon-button"
              disabled={isSaving}
              onClick={handleSettingsButton}
              title={t('profile.settings')}
              type="button"
            >
              <img alt="" aria-hidden="true" src={settingsGearIconUrl} />
            </button>
          </header>

          {feedback !== null && <p className="profile-feedback is-success">{feedback}</p>}
          {error !== null && <p className="profile-feedback is-error">{error}</p>}
          {isLoading ? (
            <p className="profile-loading">{t('common.loading')}</p>
          ) : isEditing ? (
            <ProfileEditor
              aliasInput={aliasInput}
              draft={draft}
              isSaving={isSaving}
              onAliasInputChange={setAliasInput}
              onCancel={cancelEditing}
              onChange={setDraft}
              onSave={saveProfile}
            />
          ) : (
            <div className="profile-sections">
              <section>
                <h2>{t('profile.section.identity')}</h2>
                <ProfileFieldList fields={identityFields} profile={profile} />
                <div className="profile-email-list">
                  <h3>{t('profile.ownedEmails')}</h3>
                  {ownedEmails.length > 0 ? (
                    <ul>
                      {ownedEmails.map((address) => (
                        <li key={address}>{address}</li>
                      ))}
                    </ul>
                  ) : (
                    <p>{t('profile.noOwnedEmails')}</p>
                  )}
                </div>
              </section>
              <section>
                <h2>{t('profile.section.academicContext')}</h2>
                <ProfileFieldList fields={academicContextFields} profile={profile} />
                <div className="profile-bullet-groups">
                  {academicContextListFields.map((field) => (
                    <ProfileBulletGroup
                      field={field}
                      key={field.key}
                      profile={profile}
                    />
                  ))}
                </div>
                <div className="profile-contact-groups">
                  <ProfileContactGroup
                    contacts={supervisedContacts}
                    title={t('profile.contactGroups.supervisedPeople')}
                  />
                  <ProfileContactGroup
                    contacts={collaboratorContacts}
                    title={t('profile.contactGroups.collaborators')}
                  />
                </div>
              </section>
            </div>
          )}
        </section>
      </div>
    </main>
  )
}
