import { useEffect, useState } from 'react'
import type { CSSProperties, DragEvent, FormEvent, MouseEvent, ReactNode } from 'react'
import { t } from './i18n'
import { AppLink, navigateTo } from './navigation'
import downloadIconUrl from './assets/download-icon.svg'
import settingsGearIconUrl from './assets/settings-gear.svg'
import trashIconUrl from './assets/trash-icon.svg'
import {
  createStorageDirectory,
  deleteStorageDirectory,
  deleteStorageObject,
  listStorageDirectories,
  listStorageObjects,
  moveStorageObjectToDirectory,
  updateStorageObjectLlmInput,
  uploadManagedStorageFile,
} from './phase3Api'
import { listContacts } from './phase3Api'
import type { Contact, StorageDirectory, StorageObject } from './phase3Api'
import {
  createCaseStakeholder,
  createCase,
  createCaseToolLink,
  createCaseGenre,
  deleteCaseStakeholder,
  deleteCaseToolLink,
  deleteCaseGenre,
  getCase,
  listCaseMailLinks,
  listCaseToolLinks,
  listCaseGenres,
  listCases,
  reorderCaseToolLinks,
  reorderCaseStakeholders,
  updateCase,
  updateCaseStakeholder,
  updateCaseGenre,
} from './phase7Api'
import type { CaseDetail, CaseGenre, CaseItem, CaseListStatus, CaseMailLink, CaseStakeholder, CaseToolLink } from './phase7Api'
import {
  ActionIconLabel,
  downloadStorageObject,
  StorageDirectoryCard,
  StorageObjectCard,
  storageObjectDragType,
} from './StorageView'

function describeError(error: unknown) {
  return error instanceof Error ? error.message : t('cases.requestFailed')
}

function formatDateTime(value: string | null) {
  if (value === null) return t('common.none')
  return value.slice(0, 16).replace('T', ' ')
}

function jstDateToday() {
  const now = new Date()
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Tokyo',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
    .formatToParts(now)
    .reduce<Record<string, string>>((values, part) => {
      values[part.type] = part.value
      return values
    }, {})
  return `${parts.year}-${parts.month}-${parts.day}`
}

function dateParts(date: string) {
  const [year, month, day] = date.split('-').map(Number)
  return { year, month, day }
}

function formatCalendarDate(year: number, month: number, day: number) {
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

function addMonths(date: string, amount: number) {
  const { year, month } = dateParts(date)
  const nextDate = new Date(Date.UTC(year, month - 1 + amount, 1))
  return formatCalendarDate(nextDate.getUTCFullYear(), nextDate.getUTCMonth() + 1, 1)
}

function calendarDays(date: string) {
  const { year, month } = dateParts(date)
  const firstDay = new Date(Date.UTC(year, month - 1, 1))
  const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate()
  return [
    ...Array.from({ length: firstDay.getUTCDay() }, () => null),
    ...Array.from({ length: daysInMonth }, (_, index) =>
      formatCalendarDate(year, month, index + 1),
    ),
  ]
}

function monthLabel(date: string) {
  return date.slice(0, 7)
}

function randomGenreColor() {
  return `#${Math.floor(Math.random() * 0xffffff)
    .toString(16)
    .padStart(6, '0')}`
}

function genreColor(item: CaseItem, genres: CaseGenre[]) {
  return genres.find((genre) => genre.id === item.genre_id)?.color_hex ?? '#ffffff'
}

function CaseRow({ genres, item }: { genres: CaseGenre[]; item: CaseItem }) {
  return (
    <AppLink
      className="case-row"
      href={`/cases/${encodeURIComponent(item.id)}`}
      style={{ '--case-genre-color': genreColor(item, genres) } as CSSProperties}
    >
      <div className="case-row-main">
        <div className="case-row-title">
          <h2>{item.name}</h2>
        </div>
      </div>
      <dl className="case-row-meta">
        <div>
          <dt>{t('cases.card.nextTask')}</dt>
          <dd>{item.next_task?.title ?? t('cases.card.none')}</dd>
          <small>{formatDateTime(item.next_task?.due_at ?? null)}</small>
        </div>
        <div>
          <dt>{t('cases.card.nextEvent')}</dt>
          <dd>{item.next_calendar_event?.title ?? t('cases.card.none')}</dd>
          <small>{formatDateTime(item.next_calendar_event?.starts_at ?? null)}</small>
        </div>
      </dl>
      <div aria-label={t('cases.tags')} className="case-row-tags">
        {item.tags.length === 0 ? (
          <span>{t('cases.tags.empty')}</span>
        ) : (
          item.tags.map((tag) => <span key={tag}>{tag}</span>)
        )}
      </div>
    </AppLink>
  )
}

function CaseStorageWindow({ rootDirectoryId }: { rootDirectoryId: string }) {
  const [currentDirectoryId, setCurrentDirectoryId] = useState(rootDirectoryId)
  const [objects, setObjects] = useState<StorageObject[]>([])
  const [directories, setDirectories] = useState<StorageDirectory[]>([])
  const [breadcrumbs, setBreadcrumbs] = useState<StorageDirectory[]>([])
  const [contextMenu, setContextMenu] = useState<{
    directory: StorageDirectory | null
    object: StorageObject | null
    x: number
    y: number
  } | null>(null)
  const [selectedObjectId, setSelectedObjectId] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [isDragOver, setIsDragOver] = useState(false)
  const [downloadBusyId, setDownloadBusyId] = useState<string | null>(null)
  const [llmBusyId, setLlmBusyId] = useState<string | null>(null)
  const [deleteBusyId, setDeleteBusyId] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setCurrentDirectoryId(rootDirectoryId)
  }, [rootDirectoryId])

  async function refreshStorage() {
    const [nextObjects, nextDirectories] = await Promise.all([
      listStorageObjects({ directory_id: currentDirectoryId, limit: 200 }),
      listStorageDirectories(currentDirectoryId),
    ])
    setObjects(nextObjects)
    setDirectories(nextDirectories.items)
    setBreadcrumbs(nextDirectories.breadcrumbs)
  }

  useEffect(() => {
    let isMounted = true
    setIsLoading(true)
    setError(null)
    refreshStorage()
      .catch((requestError) => {
        if (isMounted) setError(describeError(requestError))
      })
      .finally(() => {
        if (isMounted) setIsLoading(false)
      })
    return () => {
      isMounted = false
    }
  }, [currentDirectoryId])

  useEffect(() => {
    if (contextMenu === null) return undefined
    const closeMenu = () => setContextMenu(null)
    const closeMenuOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeMenu()
    }
    window.addEventListener('click', closeMenu)
    window.addEventListener('scroll', closeMenu, true)
    window.addEventListener('keydown', closeMenuOnEscape)
    return () => {
      window.removeEventListener('click', closeMenu)
      window.removeEventListener('scroll', closeMenu, true)
      window.removeEventListener('keydown', closeMenuOnEscape)
    }
  }, [contextMenu])

  async function uploadFile(file: File | null) {
    if (file === null) {
      setError(t('storage.noFileSelected'))
      return
    }
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const response = await uploadManagedStorageFile(file, currentDirectoryId)
      setNotice(
        t('storage.uploaded', {
          name: response.storage_object.original_filename ?? response.storage_object.id,
        }),
      )
      await refreshStorage()
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setBusy(false)
    }
  }

  async function handleMoveStorageObject(objectId: string, directoryId: string) {
    if (objectId === '') return
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const movedObject = await moveStorageObjectToDirectory(objectId, directoryId)
      setSelectedObjectId((currentId) => (currentId === objectId ? null : currentId))
      setNotice(t('storage.moved', { name: movedObject.original_filename ?? movedObject.id }))
      await refreshStorage()
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setBusy(false)
    }
  }

  function objectIdFromDragEvent(event: DragEvent<HTMLElement>) {
    return (
      event.dataTransfer.getData(storageObjectDragType) ||
      event.dataTransfer.getData('text/plain')
    )
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setIsDragOver(false)
    if (event.dataTransfer.files.length > 0) {
      void uploadFile(event.dataTransfer.files?.[0] ?? null)
      return
    }
    const objectId = objectIdFromDragEvent(event)
    if (objectId !== '') void handleMoveStorageObject(objectId, currentDirectoryId)
  }

  function handleDragOver(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    event.dataTransfer.dropEffect =
      event.dataTransfer.types.includes('Files') ? 'copy' : 'move'
    setIsDragOver(true)
  }

  function handleDragLeave(event: DragEvent<HTMLDivElement>) {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
      setIsDragOver(false)
    }
  }

  function handleDirectoryDragOver(event: DragEvent<HTMLElement>) {
    event.preventDefault()
    event.stopPropagation()
    event.dataTransfer.dropEffect = 'move'
  }

  function handleDirectoryDrop(event: DragEvent<HTMLElement>, directoryId: string) {
    event.preventDefault()
    event.stopPropagation()
    const objectId = objectIdFromDragEvent(event)
    if (objectId !== '') void handleMoveStorageObject(objectId, directoryId)
  }

  async function handleDownload(object: StorageObject) {
    setDownloadBusyId(object.id)
    setError(null)
    try {
      await downloadStorageObject(object)
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setDownloadBusyId(null)
    }
  }

  async function handleUpdateLlmInput(object: StorageObject, allowed: boolean) {
    setLlmBusyId(object.id)
    setError(null)
    try {
      const updatedObject = await updateStorageObjectLlmInput(object.id, allowed)
      setObjects((currentObjects) =>
        currentObjects.map((currentObject) =>
          currentObject.id === updatedObject.id ? updatedObject : currentObject,
        ),
      )
      if (contextMenu?.object?.id === updatedObject.id) {
        setContextMenu({ ...contextMenu, object: updatedObject })
      }
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setLlmBusyId(null)
    }
  }

  async function handleDelete(object: StorageObject) {
    if (!window.confirm(t('storage.delete.confirm', { name: object.original_filename ?? object.id }))) {
      return
    }
    setDeleteBusyId(object.id)
    setError(null)
    setNotice(null)
    try {
      await deleteStorageObject(object.id)
      setObjects((currentObjects) =>
        currentObjects.filter((currentObject) => currentObject.id !== object.id),
      )
      setSelectedObjectId((currentId) => (currentId === object.id ? null : currentId))
      setNotice(t('storage.deleted', { name: object.original_filename ?? object.id }))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setDeleteBusyId(null)
    }
  }

  function handleOpenStorageObject(object: StorageObject) {
    setSelectedObjectId(object.id)
    setContextMenu(null)
    navigateTo(`/files/${encodeURIComponent(object.id)}`)
  }

  function handleOpenDirectory(directory: StorageDirectory) {
    setSelectedObjectId(null)
    setContextMenu(null)
    setCurrentDirectoryId(directory.id)
  }

  async function createDirectoryByPrompt() {
    const name = window.prompt(t('storage.directory.namePrompt'))?.trim() ?? ''
    if (name === '') return
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      await createStorageDirectory({ name, parent_id: currentDirectoryId })
      await refreshStorage()
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setBusy(false)
    }
  }

  function handleStorageObjectContextMenu(event: MouseEvent<HTMLButtonElement>, object: StorageObject) {
    event.preventDefault()
    event.stopPropagation()
    setSelectedObjectId(object.id)
    setContextMenu({
      directory: null,
      object,
      x: Math.max(8, Math.min(event.clientX, window.innerWidth - 180)),
      y: Math.max(8, Math.min(event.clientY, window.innerHeight - 64)),
    })
  }

  function handleStoragePanelContextMenu(event: MouseEvent<HTMLElement>) {
    event.preventDefault()
    const target = event.target instanceof Element ? event.target : null
    if (target?.closest('.storage-object-card') !== null) {
      return
    }
    setSelectedObjectId(null)
    setContextMenu({
      directory: null,
      object: null,
      x: Math.max(8, Math.min(event.clientX, window.innerWidth - 180)),
      y: Math.max(8, Math.min(event.clientY, window.innerHeight - 64)),
    })
  }

  function handleStorageDirectoryContextMenu(
    event: MouseEvent<HTMLButtonElement>,
    directory: StorageDirectory,
  ) {
    event.preventDefault()
    event.stopPropagation()
    if (directory.directory_kind === 'case' || directory.case_id !== null) {
      setContextMenu(null)
      return
    }
    setSelectedObjectId(null)
    setContextMenu({
      directory,
      object: null,
      x: Math.max(8, Math.min(event.clientX, window.innerWidth - 180)),
      y: Math.max(8, Math.min(event.clientY, window.innerHeight - 64)),
    })
  }

  async function handleDeleteDirectory(directory: StorageDirectory) {
    if (!window.confirm(t('storage.directory.deleteConfirm', { name: directory.name }))) {
      return
    }
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      await deleteStorageDirectory(directory.id)
      setDirectories((currentDirectories) =>
        currentDirectories.filter((currentDirectory) => currentDirectory.id !== directory.id),
      )
      setNotice(t('storage.directory.deleted', { name: directory.name }))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setBusy(false)
    }
  }

  function handleContextDownload() {
    if (contextMenu === null || contextMenu.object === null) return
    const object = contextMenu.object
    setContextMenu(null)
    void handleDownload(object)
  }

  function handleContextLlmInputToggle() {
    if (contextMenu === null || contextMenu.object === null) return
    const object = contextMenu.object
    setContextMenu(null)
    void handleUpdateLlmInput(object, !object.llm_input_allowed)
  }

  function handleContextDelete() {
    if (contextMenu === null || contextMenu.object === null) return
    const object = contextMenu.object
    setContextMenu(null)
    void handleDelete(object)
  }

  function handleContextCreateDirectory() {
    setContextMenu(null)
    void createDirectoryByPrompt()
  }

  function handleContextDeleteDirectory() {
    if (contextMenu === null || contextMenu.directory === null) return
    const directory = contextMenu.directory
    setContextMenu(null)
    void handleDeleteDirectory(directory)
  }

  const rootIndex = breadcrumbs.findIndex((directory) => directory.id === rootDirectoryId)
  const visibleBreadcrumbs = rootIndex >= 0 ? breadcrumbs.slice(rootIndex + 1) : breadcrumbs

  return (
    <section className="case-storage-window">
      {(error !== null || notice !== null) && (
        <div className="mail-feedback case-storage-feedback">
          {error !== null && <p role="alert">{error}</p>}
          {notice !== null && <p>{notice}</p>}
        </div>
      )}
      <nav aria-label={t('storage.directory.breadcrumb')} className="storage-breadcrumb case-storage-breadcrumb">
        <button
          onClick={() => setCurrentDirectoryId(rootDirectoryId)}
          onDragOver={handleDirectoryDragOver}
          onDrop={(event) => handleDirectoryDrop(event, rootDirectoryId)}
          type="button"
        >
          {t('cases.storage.root')}
        </button>
        {visibleBreadcrumbs.map((directory) => (
          <button
            key={directory.id}
            onClick={() => handleOpenDirectory(directory)}
            onDragOver={handleDirectoryDragOver}
            onDrop={(event) => handleDirectoryDrop(event, directory.id)}
            type="button"
          >
            {directory.name}
          </button>
        ))}
      </nav>
      <div
        className={`case-storage-drop-zone storage-drop-zone button-loading-dot${
          busy ? ' is-loading' : ''
        }${isDragOver ? ' is-drag-over' : ''}`}
        onContextMenu={handleStoragePanelContextMenu}
        onDragLeave={handleDragLeave}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
      >
        <div className="section-heading case-storage-drop-heading">
          <div>
            <h2>{t('storage.objects')}</h2>
          </div>
          <p>{t('cases.storage.body')}</p>
        </div>
        <div className="storage-object-grid">
          {directories.map((directory) => (
            <StorageDirectoryCard
              directory={directory}
              key={directory.id}
              onContextMenu={handleStorageDirectoryContextMenu}
              onDropObject={(objectId, directoryId) => {
                if (directoryId !== null) void handleMoveStorageObject(objectId, directoryId)
              }}
              onOpen={handleOpenDirectory}
            />
          ))}
          {objects.map((object) => (
            <StorageObjectCard
              busy={
                downloadBusyId === object.id ||
                llmBusyId === object.id ||
                deleteBusyId === object.id
              }
              key={object.id}
              object={object}
              onContextMenu={handleStorageObjectContextMenu}
              onOpen={handleOpenStorageObject}
              selected={selectedObjectId === object.id}
            />
          ))}
          {objects.length === 0 && directories.length === 0 && (
            <p>{isLoading ? t('storage.loading') : t('storage.noObjects')}</p>
          )}
        </div>
        {contextMenu !== null && (
          <div
            aria-label={t('storage.context.menuLabel')}
            className="storage-context-menu"
            onClick={(event) => event.stopPropagation()}
            role="menu"
            style={{ left: contextMenu.x, top: contextMenu.y }}
          >
            {contextMenu.object === null && contextMenu.directory === null && (
              <button onClick={handleContextCreateDirectory} role="menuitem" type="button">
                {t('storage.context.newDirectory')}
              </button>
            )}
            {contextMenu.directory !== null &&
              contextMenu.directory.directory_kind !== 'case' &&
              contextMenu.directory.case_id === null && (
                <button onClick={handleContextDeleteDirectory} role="menuitem" type="button">
                  <ActionIconLabel
                    iconUrl={trashIconUrl}
                    label={t('storage.context.deleteDirectory')}
                  />
                </button>
              )}
            {contextMenu.object !== null && (
              <>
                <button onClick={handleContextDownload} role="menuitem" type="button">
                  <ActionIconLabel
                    iconUrl={downloadIconUrl}
                    label={t('storage.context.download')}
                  />
                </button>
                <button onClick={handleContextLlmInputToggle} role="menuitem" type="button">
                  {contextMenu.object.llm_input_allowed
                    ? t('storage.llmInput.disallow')
                    : t('storage.llmInput.allow')}
                </button>
                <button onClick={handleContextDelete} role="menuitem" type="button">
                  <ActionIconLabel iconUrl={trashIconUrl} label={t('storage.context.delete')} />
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </section>
  )
}

function CaseWorkbenchPanel({
  title,
  eyebrow,
  count,
  actionLabel,
  actionHref,
  children,
}: {
  title: string
  eyebrow: string
  count: number
  actionLabel: string
  actionHref?: string
  children: ReactNode
}) {
  return (
    <section className="case-workbench-panel">
      <div className="case-workbench-panel-header">
        <div>
          <span>{eyebrow}</span>
          <h2>{title}</h2>
        </div>
        <div className="case-workbench-panel-actions">
          <strong>{count}</strong>
          {actionHref === undefined ? (
            <button type="button">{actionLabel}</button>
          ) : (
            <AppLink href={actionHref}>{actionLabel}</AppLink>
          )}
        </div>
      </div>
      {children}
    </section>
  )
}

const stakeholderRoles = ['owner', 'collaborator', 'reviewer', 'stakeholder'] as const

function stakeholderRoleLabel(role: string) {
  if (role === 'owner') return t('cases.stakeholders.role.owner')
  if (role === 'collaborator') return t('cases.stakeholders.role.collaborator')
  if (role === 'reviewer') return t('cases.stakeholders.role.reviewer')
  return t('cases.stakeholders.role.stakeholder')
}

function CaseStakeholdersPanel({
  caseId,
  initialStakeholders,
}: {
  caseId: string
  initialStakeholders: CaseStakeholder[]
}) {
  const [stakeholders, setStakeholders] = useState(initialStakeholders)
  const [contacts, setContacts] = useState<Contact[]>([])
  const [isSettingsOpen, setIsSettingsOpen] = useState(false)
  const [contactQuery, setContactQuery] = useState('')
  const [role, setRole] = useState('stakeholder')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setStakeholders(initialStakeholders)
  }, [initialStakeholders])

  useEffect(() => {
    let isMounted = true
    listContacts()
      .then((items) => {
        if (isMounted) setContacts(items)
      })
      .catch((requestError) => {
        if (isMounted) setError(describeError(requestError))
      })
    return () => {
      isMounted = false
    }
  }, [])

  const normalizedQuery = contactQuery.trim().toLowerCase()
  const suggestedContacts = normalizedQuery === ''
    ? []
    : contacts
        .filter((contact) =>
          [contact.display_name, ...contact.email_addresses.map((email) => email.email_address)]
            .join(' ')
            .toLowerCase()
            .includes(normalizedQuery),
        )
        .slice(0, 5)
  const selectedContact = contacts.find((contact) => {
    const query = contactQuery.trim().toLowerCase()
    return (
      contact.display_name.toLowerCase() === query ||
      contact.email_addresses.some((email) => email.email_address.toLowerCase() === query)
    )
  })
  const linkedContactIds = new Set(stakeholders.map((stakeholder) => stakeholder.contact_id))
  const canAddStakeholder =
    selectedContact !== undefined &&
    !linkedContactIds.has(selectedContact.id)

  async function addStakeholder(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!canAddStakeholder || selectedContact === undefined) return
    setBusy(true)
    setError(null)
    try {
      const stakeholder = await createCaseStakeholder(caseId, {
        contact_id: selectedContact.id,
        role,
      })
      setStakeholders((current) => [...current, stakeholder])
      setContactQuery('')
      setRole('stakeholder')
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setBusy(false)
    }
  }

  async function changeRole(stakeholder: CaseStakeholder, nextRole: string) {
    setBusy(true)
    setError(null)
    try {
      const updatedStakeholder = await updateCaseStakeholder(caseId, stakeholder.id, {
        role: nextRole,
      })
      setStakeholders((current) =>
        current.map((item) => (item.id === updatedStakeholder.id ? updatedStakeholder : item)),
      )
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setBusy(false)
    }
  }

  async function moveStakeholder(index: number, direction: -1 | 1) {
    const nextIndex = index + direction
    if (nextIndex < 0 || nextIndex >= stakeholders.length) return
    const nextStakeholders = [...stakeholders]
    const [stakeholder] = nextStakeholders.splice(index, 1)
    nextStakeholders.splice(nextIndex, 0, stakeholder)
    setBusy(true)
    setError(null)
    try {
      setStakeholders(
        await reorderCaseStakeholders(
          caseId,
          nextStakeholders.map((item) => item.id),
        ),
      )
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setBusy(false)
    }
  }

  async function removeStakeholder(stakeholder: CaseStakeholder) {
    setBusy(true)
    setError(null)
    try {
      await deleteCaseStakeholder(caseId, stakeholder.id)
      setStakeholders((current) => current.filter((item) => item.id !== stakeholder.id))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="case-stakeholders-panel">
      <div className="case-gadget-heading-row">
        <div>
          <h2>{t('cases.stakeholders.heading')}</h2>
          <p>{t('cases.stakeholders.body')}</p>
        </div>
        <button
          aria-expanded={isSettingsOpen}
          aria-label={t('cases.stakeholders.configure')}
          className="case-icon-button"
          onClick={() => setIsSettingsOpen((current) => !current)}
          title={t('cases.stakeholders.configure')}
          type="button"
        >
          <img alt="" aria-hidden="true" src={settingsGearIconUrl} />
        </button>
      </div>
      {error !== null && <p className="case-stakeholder-error" role="alert">{error}</p>}
      <div className="case-stakeholder-list">
        {stakeholders.length === 0 ? (
          <p>{t('cases.stakeholders.empty')}</p>
        ) : (
          stakeholders.map((stakeholder, index) => (
            <div
              className={`case-stakeholder-item${isSettingsOpen ? ' is-editing' : ''}`}
              key={stakeholder.id}
            >
              <span>{stakeholder.contact_display_name.slice(0, 2).toUpperCase()}</span>
              <strong>{stakeholder.contact_display_name}</strong>
              {isSettingsOpen ? (
                <>
                  <select
                    aria-label={t('cases.stakeholders.role')}
                    disabled={busy}
                    onChange={(event) => void changeRole(stakeholder, event.target.value)}
                    value={stakeholder.role}
                  >
                    {stakeholderRoles.map((roleValue) => (
                      <option key={roleValue} value={roleValue}>
                        {stakeholderRoleLabel(roleValue)}
                      </option>
                    ))}
                  </select>
                  <button
                    disabled={busy || index === 0}
                    onClick={() => void moveStakeholder(index, -1)}
                    type="button"
                  >
                    {t('cases.stakeholders.moveUp')}
                  </button>
                  <button
                    disabled={busy || index === stakeholders.length - 1}
                    onClick={() => void moveStakeholder(index, 1)}
                    type="button"
                  >
                    {t('cases.stakeholders.moveDown')}
                  </button>
                  <button
                    disabled={busy}
                    onClick={() => void removeStakeholder(stakeholder)}
                    type="button"
                  >
                    {t('cases.stakeholders.delete')}
                  </button>
                </>
              ) : (
                <em>{stakeholderRoleLabel(stakeholder.role)}</em>
              )}
            </div>
          ))
        )}
      </div>
      {isSettingsOpen && (
        <form className="case-stakeholder-form" onSubmit={addStakeholder}>
          <label>
            <span>{t('cases.stakeholders.contact')}</span>
            <input
              onChange={(event) => setContactQuery(event.target.value)}
              type="text"
              value={contactQuery}
            />
            {suggestedContacts.length > 0 && (
              <div className="case-stakeholder-suggestions">
                {suggestedContacts.map((contact) => (
                  <button
                    key={contact.id}
                    onClick={() => setContactQuery(contact.display_name)}
                    type="button"
                  >
                    <strong>{contact.display_name}</strong>
                    <span>
                      {contact.email_addresses.find((email) => email.is_primary)
                        ?.email_address ?? t('common.none')}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </label>
          <label>
            <span>{t('cases.stakeholders.role')}</span>
            <select onChange={(event) => setRole(event.target.value)} value={role}>
              {stakeholderRoles.map((roleValue) => (
                <option key={roleValue} value={roleValue}>
                  {stakeholderRoleLabel(roleValue)}
                </option>
              ))}
            </select>
          </label>
          <button disabled={busy || !canAddStakeholder} type="submit">
            {t('cases.stakeholders.add')}
          </button>
          {contactQuery.trim() !== '' && selectedContact === undefined && (
            <p>{t('cases.stakeholders.noContact')}</p>
          )}
          {selectedContact !== undefined && linkedContactIds.has(selectedContact.id) && (
            <p>{t('cases.stakeholders.alreadyLinked')}</p>
          )}
        </form>
      )}
    </section>
  )
}

function CaseCalendarGadget({ caseItem }: { caseItem: CaseItem }) {
  const today = jstDateToday()
  const initialMonth = caseItem.next_calendar_event?.starts_at?.slice(0, 10) ?? today
  const [calendarMonth, setCalendarMonth] = useState(initialMonth)
  const eventDate = caseItem.next_calendar_event?.starts_at?.slice(0, 10) ?? null
  const selectedMonthDays = calendarDays(calendarMonth)

  return (
    <section
      aria-label={t('cases.calendar.label')}
      className="mail-panel mail-calendar-panel case-calendar-gadget"
    >
      <button
        className="mail-calendar-today"
        onClick={() => setCalendarMonth(today)}
        type="button"
      >
        {t('mail.today')}
      </button>
      <div className="mail-calendar-heading">
        <button
          aria-label={t('mail.previousMonth')}
          onClick={() => setCalendarMonth((currentMonth) => addMonths(currentMonth, -1))}
          type="button"
        >
          {'<'}
        </button>
        <strong>{monthLabel(calendarMonth)}</strong>
        <button
          aria-label={t('mail.nextMonth')}
          onClick={() => setCalendarMonth((currentMonth) => addMonths(currentMonth, 1))}
          type="button"
        >
          {'>'}
        </button>
      </div>
      <div aria-label={t('cases.calendar.label')} className="mail-calendar-grid">
        {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map((weekday) => (
          <span className="mail-calendar-weekday" key={weekday}>
            {weekday}
          </span>
        ))}
        {selectedMonthDays.map((date, index) => {
          if (date === null) {
            return (
              <span
                aria-hidden="true"
                className="mail-calendar-empty"
                key={`empty-${index}`}
              />
            )
          }
          const hasEvent = date === eventDate
          return (
            <button
              aria-current={date === today ? 'date' : undefined}
              aria-label={hasEvent ? t('cases.calendar.openDate', { date }) : date}
              className={`${hasEvent ? 'mail-calendar-day case-calendar-day-has-event' : 'mail-calendar-day mail-calendar-day-empty'}`}
              disabled={!hasEvent}
              key={date}
              type="button"
            >
              {Number(date.slice(8, 10))}
            </button>
          )
        })}
      </div>
      <div className="case-calendar-gadget-next">
        <span>{t('cases.calendar.next')}</span>
        <strong>{caseItem.next_calendar_event?.title ?? t('cases.card.none')}</strong>
        <small>{formatDateTime(caseItem.next_calendar_event?.starts_at ?? null)}</small>
      </div>
      <button className="case-gadget-action" type="button">
        {t('cases.calendar.add')}
      </button>
    </section>
  )
}

function caseToolIconLabelFromUrl(url: string) {
  return (
    url
      .replace(/^https?:\/\//, '')
      .replace(/^www\./, '')
      .trim()
      .replace(/[^a-zA-Z0-9]/g, '')
      .slice(0, 2)
      .toUpperCase() || 'TL'
  )
}

function CaseToolsGadget({
  caseId,
  initialTools,
}: {
  caseId: string
  initialTools: CaseToolLink[]
}) {
  const [tools, setTools] = useState<CaseToolLink[]>(initialTools)
  const [isSettingsOpen, setIsSettingsOpen] = useState(false)
  const [url, setUrl] = useState('')
  const [draggedToolId, setDraggedToolId] = useState<string | null>(null)
  const [dropIndex, setDropIndex] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setTools(initialTools)
  }, [initialTools])

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const normalizedUrl = url.trim()
    if (normalizedUrl === '') return
    setBusy(true)
    setError(null)
    try {
      const tool = await createCaseToolLink(caseId, {
        url: normalizedUrl,
        icon_label: caseToolIconLabelFromUrl(normalizedUrl),
      })
      setTools((currentTools) => [...currentTools, tool])
      setUrl('')
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setBusy(false)
    }
  }

  async function moveDraggedTool(nextIndex: number) {
    if (draggedToolId === null) return
    const currentIndex = tools.findIndex((tool) => tool.id === draggedToolId)
    if (currentIndex < 0) return
    const boundedIndex = Math.max(0, Math.min(nextIndex, tools.length))
    const adjustedIndex = currentIndex < boundedIndex ? boundedIndex - 1 : boundedIndex
    if (currentIndex === adjustedIndex) {
      setDraggedToolId(null)
      setDropIndex(null)
      return
    }
    const nextTools = [...tools]
    const [tool] = nextTools.splice(currentIndex, 1)
    nextTools.splice(adjustedIndex, 0, tool)
    setTools(nextTools)
    setDraggedToolId(null)
    setDropIndex(null)
    setBusy(true)
    setError(null)
    try {
      setTools(await reorderCaseToolLinks(caseId, nextTools.map((item) => item.id)))
    } catch (requestError) {
      setError(describeError(requestError))
      setTools(await listCaseToolLinks(caseId))
    } finally {
      setBusy(false)
    }
  }

  function insertionIndexFromPointer(event: DragEvent<HTMLElement>, index: number) {
    const rect = event.currentTarget.getBoundingClientRect()
    const isAfter = event.clientY > rect.top + rect.height / 2 ||
      (Math.abs(event.clientY - (rect.top + rect.height / 2)) < rect.height / 2 &&
        event.clientX > rect.left + rect.width / 2)
    return index + (isAfter ? 1 : 0)
  }

  function handleToolDragOver(event: DragEvent<HTMLElement>, index: number) {
    if (draggedToolId === null) return
    event.preventDefault()
    event.dataTransfer.dropEffect = 'move'
    setDropIndex(insertionIndexFromPointer(event, index))
  }

  function handleToolListDragOver(event: DragEvent<HTMLDivElement>) {
    if (draggedToolId === null) return
    event.preventDefault()
    event.dataTransfer.dropEffect = 'move'
    const target = event.target instanceof Element ? event.target : null
    if (target?.closest('.case-tool-manage-item') === null) {
      setDropIndex(tools.length)
    }
  }

  function handleToolDrop(event: DragEvent<HTMLElement>) {
    if (draggedToolId === null || dropIndex === null) return
    event.preventDefault()
    void moveDraggedTool(dropIndex)
  }

  async function deleteTool(toolId: string) {
    setBusy(true)
    setError(null)
    try {
      await deleteCaseToolLink(caseId, toolId)
      setTools((currentTools) => currentTools.filter((tool) => tool.id !== toolId))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="case-gadget-card case-tools-gadget">
      <div className="case-gadget-heading-row">
        <h2>{t('cases.tools.gadgetHeading')}</h2>
        <button
          aria-expanded={isSettingsOpen}
          aria-label={t('cases.tools.configure')}
          className="case-icon-button"
          onClick={() => setIsSettingsOpen((current) => !current)}
          title={t('cases.tools.configure')}
          type="button"
        >
          <img alt="" aria-hidden="true" src={settingsGearIconUrl} />
        </button>
      </div>
      <div className="case-tool-icon-grid">
        {error !== null && <p className="case-tool-error" role="alert">{error}</p>}
        {tools.length === 0 ? (
          <p className="case-tool-empty">{t('cases.tools.empty')}</p>
        ) : (
          tools.map((tool, index) => (
            <div
              className={`case-tool-icon-item${
                isSettingsOpen ? ' is-configuring' : ''
              }${draggedToolId === tool.id ? ' is-dragging' : ''}${
                dropIndex === index ? ' is-drop-before' : ''
              }${dropIndex === index + 1 ? ' is-drop-after' : ''}`}
              draggable={isSettingsOpen}
              key={tool.id}
              onDragEnd={() => {
                setDraggedToolId(null)
                setDropIndex(null)
              }}
              onDragOver={(event) => handleToolDragOver(event, index)}
              onDragStart={(event) => {
                if (!isSettingsOpen) return
                setDraggedToolId(tool.id)
                setDropIndex(index)
                event.dataTransfer.effectAllowed = 'move'
                event.dataTransfer.setData('text/plain', tool.id)
              }}
              onDrop={handleToolDrop}
            >
              <a
                href={tool.url}
                onClick={(event) => {
                  if (isSettingsOpen || tool.url === '#') event.preventDefault()
                }}
                rel="noreferrer"
                target={tool.url.startsWith('http') ? '_blank' : undefined}
                title={tool.url}
              >
                <span>{tool.icon_label}</span>
              </a>
              {isSettingsOpen && (
                <button
                  aria-label={t('cases.tools.deleteTool', { title: tool.icon_label })}
                  disabled={busy}
                  onClick={() => void deleteTool(tool.id)}
                  type="button"
                >
                  ×
                </button>
              )}
            </div>
          ))
        )}
        {isSettingsOpen && tools.length > 0 && (
          <div
            aria-hidden="true"
            className={`case-tool-drop-tail${dropIndex === tools.length ? ' is-active' : ''}`}
            onDragOver={handleToolListDragOver}
            onDrop={handleToolDrop}
          />
        )}
      </div>
      {isSettingsOpen && (
        <div className="case-tool-settings">
          <AppLink className="case-tool-icon-library-link" href="/case-tool-icons">
            {t('cases.tools.iconLibrary')}
          </AppLink>
          <form onSubmit={handleSubmit}>
            <label>
              <span>{t('cases.tools.url')}</span>
              <input
                onChange={(event) => setUrl(event.target.value)}
                placeholder="https://example.com"
                type="url"
                value={url}
              />
            </label>
            <button disabled={busy} type="submit">{t('cases.tools.add')}</button>
          </form>
        </div>
      )}
    </section>
  )
}

function CaseListView() {
  const [cases, setCases] = useState<CaseItem[]>([])
  const [allCases, setAllCases] = useState<CaseItem[]>([])
  const [genres, setGenres] = useState<CaseGenre[]>([])
  const [status, setStatus] = useState<CaseListStatus>('user_ball')
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedTag, setSelectedTag] = useState<string | null>(null)
  const [sortMode, setSortMode] = useState('updated_desc')
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let isMounted = true
    setIsLoading(true)
    setError(null)
    listCases(status)
      .then((items) => {
        if (isMounted) setCases(items)
      })
      .catch((requestError) => {
        if (isMounted) setError(describeError(requestError))
      })
      .finally(() => {
        if (isMounted) setIsLoading(false)
      })
    return () => {
      isMounted = false
    }
  }, [status])

  useEffect(() => {
    let isMounted = true
    Promise.all([
      listCaseGenres(),
      listCases('user_ball'),
      listCases('waiting'),
      listCases('completed'),
    ])
      .then(([nextGenres, userBallCases, waitingCases, completedCases]) => {
        if (!isMounted) return
        setGenres(nextGenres)
        const mergedCases = new Map<string, CaseItem>()
        ;[...userBallCases, ...waitingCases, ...completedCases].forEach((item) => {
          mergedCases.set(item.id, item)
        })
        setAllCases(Array.from(mergedCases.values()))
      })
      .catch((requestError) => {
        if (isMounted) setError(describeError(requestError))
      })
    return () => {
      isMounted = false
    }
  }, [])

  function refreshGenres() {
    listCaseGenres()
      .then(setGenres)
      .catch((requestError) => setError(describeError(requestError)))
  }

  const normalizedQuery = searchQuery.trim().toLowerCase()
  const normalizedSelectedTag = selectedTag?.toLocaleLowerCase() ?? null
  const currentTabTagCounts = cases.reduce<Map<string, number>>((counts, item) => {
    item.tags.forEach((tag) => {
      const key = tag.toLocaleLowerCase()
      counts.set(key, (counts.get(key) ?? 0) + 1)
    })
    return counts
  }, new Map<string, number>())
  const caseTags = Array.from(
    allCases.reduce<Map<string, string>>((tags, item) => {
      item.tags.forEach((tag) => {
        const key = tag.toLocaleLowerCase()
        if (!tags.has(key)) tags.set(key, tag)
      })
      return tags
    }, new Map<string, string>()),
  )
    .map(([, tag]) => tag)
    .sort((first, second) => first.localeCompare(second))
  const visibleCases = cases
    .filter((item) => {
      if (
        normalizedSelectedTag !== null &&
        !item.tags.some((tag) => tag.toLocaleLowerCase() === normalizedSelectedTag)
      ) {
        return false
      }
      if (normalizedQuery === '') return true
      return [item.name, item.description ?? '', item.progress_status, item.ball_status, ...item.tags]
        .join(' ')
        .toLowerCase()
        .includes(normalizedQuery)
    })
    .sort((first, second) => {
      if (sortMode === 'name') return first.name.localeCompare(second.name)
      if (sortMode === 'created_desc') return second.created_at.localeCompare(first.created_at)
      return second.updated_at.localeCompare(first.updated_at)
    })

  return (
    <main className="app-shell">
      <div className="case-shell">
        <header className="maintenance-header">
          <div>
            <p>{t('app.name')}</p>
            <h1>{t('cases.heading')}</h1>
          </div>
          <nav aria-label={t('cases.navigation')} className="maintenance-nav">
            <AppLink href="/">{t('top.heading')}</AppLink>
            <AppLink href="/mail">{t('mail.heading')}</AppLink>
          </nav>
        </header>

        {error !== null && (
          <div className="mail-feedback">
            <p role="alert">{error}</p>
          </div>
        )}

        <section aria-labelledby="case-tools-heading" className="case-tools-panel">
          <div className="section-heading">
            <h2 id="case-tools-heading">{t('cases.tools.heading')}</h2>
          </div>
          <div className="case-tools">
            <div aria-label={t('cases.search.region')} role="search">
              <label>
                <span>{t('cases.search.label')}</span>
                <input
                  aria-label={t('cases.search.label')}
                  onChange={(event) => setSearchQuery(event.target.value)}
                  placeholder={t('cases.search.label')}
                  type="search"
                  value={searchQuery}
                />
              </label>
            </div>
            <label className="case-sort">
              <span>{t('cases.sort.label')}</span>
              <select
                aria-label={t('cases.sort.aria')}
                onChange={(event) => setSortMode(event.target.value)}
                value={sortMode}
              >
                <option value="updated_desc">{t('cases.sort.updated')}</option>
                <option value="created_desc">{t('cases.sort.created')}</option>
                <option value="name">{t('cases.sort.name')}</option>
              </select>
            </label>
            <div aria-label={t('cases.tags.filter')} className="case-tag-filters">
              {caseTags.length === 0 ? (
                <span>{t('cases.tags.filterEmpty')}</span>
              ) : (
                caseTags.map((tag) => (
                  <button
                    aria-pressed={selectedTag?.toLocaleLowerCase() === tag.toLocaleLowerCase()}
                    key={tag}
                    onClick={() =>
                      setSelectedTag((currentTag) =>
                        currentTag?.toLocaleLowerCase() === tag.toLocaleLowerCase() ? null : tag,
                      )
                    }
                    type="button"
                  >
                    {tag}
                    <span>{currentTabTagCounts.get(tag.toLocaleLowerCase()) ?? 0}</span>
                  </button>
                ))
              )}
            </div>
          </div>
        </section>

        <div className="case-main-layout">
          <section aria-labelledby="case-list-heading" className="case-list-workspace">
            <nav aria-label={t('cases.statusFilter')} className="case-tabs" role="tablist">
              <div>
                {(['user_ball', 'waiting', 'completed'] as CaseListStatus[]).map((tab) => (
                  <button
                    aria-selected={status === tab}
                    key={tab}
                    onClick={() => setStatus(tab)}
                    role="tab"
                    type="button"
                  >
                    {t(`cases.tab.${tab}`)}
                  </button>
                ))}
              </div>
            </nav>

            <div className="case-list-panel">
              <div className="section-heading">
                <div>
                  <h2 id="case-list-heading">{t(`cases.tab.${status}`)}</h2>
                  <p>{t(`cases.tabNote.${status}`)}</p>
                </div>
              </div>
              <div className="case-list">
              {isLoading ? (
                <p>{t('cases.loading')}</p>
              ) : visibleCases.length === 0 ? (
                <p>{t('cases.empty')}</p>
              ) : (
                visibleCases.map((item) => <CaseRow genres={genres} item={item} key={item.id} />)
              )}
              </div>
            </div>
          </section>
          <aside aria-label={t('cases.gadgets')} className="case-gadget-column">
            <div className="case-gadget-card">
              <AppLink className="case-gadget-action" href="/cases/new">
                {t('cases.gadget.newCases')}
              </AppLink>
            </div>
            <CaseGenreGadget
              genres={genres}
              onError={(message) => setError(message)}
              onUpdated={refreshGenres}
            />
          </aside>
        </div>
      </div>
    </main>
  )
}

function CaseGenreGadget({
  genres,
  onError,
  onUpdated,
}: {
  genres: CaseGenre[]
  onError: (message: string) => void
  onUpdated: () => void
}) {
  const [title, setTitle] = useState('')
  const [color, setColor] = useState(randomGenreColor())
  const [editingId, setEditingId] = useState<string | null>(null)
  const [isSettingsOpen, setIsSettingsOpen] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)

  function startEdit(genre: CaseGenre) {
    setIsSettingsOpen(true)
    setEditingId(genre.id)
    setTitle(genre.title)
    setColor(genre.color_hex)
  }

  function resetForm() {
    setEditingId(null)
    setTitle('')
    setColor(randomGenreColor())
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setIsSubmitting(true)
    try {
      if (editingId === null) {
        await createCaseGenre({ title, color_hex: color })
      } else {
        await updateCaseGenre(editingId, { title, color_hex: color })
      }
      resetForm()
      onUpdated()
    } catch (requestError) {
      onError(describeError(requestError))
    } finally {
      setIsSubmitting(false)
    }
  }

  async function handleDelete(genreId: string) {
    setIsSubmitting(true)
    try {
      await deleteCaseGenre(genreId)
      if (editingId === genreId) resetForm()
      onUpdated()
    } catch (requestError) {
      onError(describeError(requestError))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="case-gadget-card case-genre-gadget">
      <div className="case-gadget-heading-row">
        <h2>{t('cases.genre.settings')}</h2>
        <button
          aria-expanded={isSettingsOpen}
          aria-label={t('cases.genre.configure')}
          className="case-icon-button"
          onClick={() => setIsSettingsOpen((current) => !current)}
          title={t('cases.genre.configure')}
          type="button"
        >
          <img alt="" aria-hidden="true" src={settingsGearIconUrl} />
        </button>
      </div>
      <div aria-label={t('cases.genre.legend')} className="case-genre-legend">
        <span>
          <i style={{ background: '#ffffff' }} />
          {t('cases.genre.none')}
        </span>
        {genres.map((genre) => (
          <span key={genre.id}>
            <i style={{ background: genre.color_hex }} />
            {genre.title}
          </span>
        ))}
      </div>
      {isSettingsOpen && (
        <>
          <form onSubmit={handleSubmit}>
            <label>
              <span>{t('cases.genre.title')}</span>
              <input
                onChange={(event) => setTitle(event.target.value)}
                required
                type="text"
                value={title}
              />
            </label>
            <label>
              <span>{t('cases.genre.color')}</span>
              <div className="case-genre-color-row">
                <input
                  onChange={(event) => setColor(event.target.value)}
                  required
                  type="text"
                  value={color}
                />
                <button onClick={() => setColor(randomGenreColor())} type="button">
                  {t('cases.genre.random')}
                </button>
              </div>
            </label>
            <div className="case-genre-actions">
              <button className={`button-loading-dot${isSubmitting ? ' is-loading' : ''}`} type="submit">
                {editingId === null ? t('cases.genre.add') : t('cases.genre.save')}
              </button>
              {editingId !== null && (
                <button onClick={resetForm} type="button">
                  {t('common.cancel')}
                </button>
              )}
            </div>
          </form>
      <div className="case-genre-list">
        {genres.length === 0 ? (
          <p>{t('cases.genre.empty')}</p>
        ) : (
          genres.map((genre) => (
            <div className="case-genre-item" key={genre.id}>
                  <span>
                    <i style={{ background: genre.color_hex }} />
                    {genre.title}
                  </span>
                  <button onClick={() => startEdit(genre)} type="button">
                    {t('cases.genre.edit')}
                  </button>
                  <button onClick={() => handleDelete(genre.id)} type="button">
                    {t('cases.genre.delete')}
                  </button>
                </div>
              ))
            )}
          </div>
        </>
      )}
    </div>
  )
}

function CaseDetailView({ caseId }: { caseId: string }) {
  const [detail, setDetail] = useState<CaseDetail | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isOverviewEditing, setIsOverviewEditing] = useState(false)
  const [overviewDraft, setOverviewDraft] = useState('')
  const [openWhenDraft, setOpenWhenDraft] = useState('')
  const [closedWhenDraft, setClosedWhenDraft] = useState('')
  const [tagDraft, setTagDraft] = useState('')
  const [isOverviewSaving, setIsOverviewSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let isMounted = true
    setIsLoading(true)
    setError(null)
    getCase(caseId)
      .then((nextDetail) => {
        if (isMounted) setDetail(nextDetail)
      })
      .catch((requestError) => {
        if (isMounted) setError(describeError(requestError))
      })
      .finally(() => {
        if (isMounted) setIsLoading(false)
      })
    return () => {
      isMounted = false
    }
  }, [caseId])

  const item = detail?.case ?? null

  function startOverviewEdit() {
    if (item === null) return
    setOverviewDraft(item.description ?? '')
    setOpenWhenDraft(item.open_when_text ?? '')
    setClosedWhenDraft(item.closed_when_text ?? '')
    setTagDraft(item.tags.join(', '))
    setIsOverviewEditing(true)
  }

  function parseTagDraft(value: string) {
    const tags: string[] = []
    const seen = new Set<string>()
    value
      .split(/[,\n]/)
      .map((tag) => tag.trim())
      .filter(Boolean)
      .forEach((tag) => {
        const key = tag.toLocaleLowerCase()
        if (!seen.has(key)) {
          seen.add(key)
          tags.push(tag)
        }
      })
    return tags
  }

  async function handleOverviewSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (item === null) return
    setIsOverviewSaving(true)
    setError(null)
    try {
      const updatedCase = await updateCase(caseId, {
        description: overviewDraft.trim() === '' ? null : overviewDraft,
        open_when_text: openWhenDraft.trim() === '' ? null : openWhenDraft,
        closed_when_text: closedWhenDraft.trim() === '' ? null : closedWhenDraft,
        tags: parseTagDraft(tagDraft),
      })
      setDetail((currentDetail) =>
        currentDetail === null ? currentDetail : { ...currentDetail, case: updatedCase },
      )
      setIsOverviewEditing(false)
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsOverviewSaving(false)
    }
  }

  return (
    <main className="app-shell">
      <div className="case-shell">
        <header className="maintenance-header">
          <div>
            <p>{t('app.name')}</p>
            <h1>{item?.name ?? t('cases.detailHeading')}</h1>
          </div>
          <nav aria-label={t('cases.navigation')} className="maintenance-nav">
            <AppLink href="/cases">{t('cases.heading')}</AppLink>
            <AppLink href="/">{t('top.heading')}</AppLink>
          </nav>
        </header>

        {error !== null && (
          <div className="mail-feedback">
            <p role="alert">{error}</p>
          </div>
        )}

        {isLoading || detail === null || item === null ? (
          <p className="mail-empty">{t('cases.loading')}</p>
        ) : (
          <div className="case-detail-layout">
            <div className="case-detail-workspace">
              <section className="case-overview-panel">
                <button
                  aria-expanded={isOverviewEditing}
                  aria-label={t('cases.overview.configure')}
                  className="case-icon-button case-overview-settings-button"
                  onClick={() =>
                    isOverviewEditing ? setIsOverviewEditing(false) : startOverviewEdit()
                  }
                  title={t('cases.overview.configure')}
                  type="button"
                >
                  <img alt="" aria-hidden="true" src={settingsGearIconUrl} />
                </button>
                <div className="case-overview-main">
                  <div>
                    <div className="case-overview-title-row">
                      <h2>{t('cases.section.overview')}</h2>
                      <span>{t('cases.updated')}: {formatDateTime(item.updated_at)}</span>
                    </div>
                  </div>
                  {isOverviewEditing ? (
                    <form className="case-overview-form" onSubmit={handleOverviewSubmit}>
                      <textarea
                        aria-label={t('cases.section.overview')}
                        autoFocus
                        onChange={(event) => setOverviewDraft(event.target.value)}
                        rows={5}
                        value={overviewDraft}
                      />
                      <label className="case-overview-tags-field">
                        <span>{t('cases.tags')}</span>
                        <input
                          aria-label={t('cases.tags')}
                          onChange={(event) => setTagDraft(event.target.value)}
                          placeholder={t('cases.tags.placeholder')}
                          value={tagDraft}
                        />
                      </label>
                      <div className="case-overview-actions">
                        <button
                          className={`button-loading-dot${isOverviewSaving ? ' is-loading' : ''}`}
                          disabled={isOverviewSaving}
                          type="submit"
                        >
                          {t('cases.overview.save')}
                        </button>
                        <button
                          disabled={isOverviewSaving}
                          onClick={() => setIsOverviewEditing(false)}
                          type="button"
                        >
                          {t('common.cancel')}
                        </button>
                      </div>
                    </form>
                  ) : (
                    <>
                      <p>{item.description ?? t('cases.overview.empty')}</p>
                      <div aria-label={t('cases.tags')} className="case-row-tags case-overview-tags">
                        {item.tags.length === 0 ? (
                          <span>{t('cases.tags.empty')}</span>
                        ) : (
                          item.tags.map((tag) => <span key={tag}>{tag}</span>)
                        )}
                      </div>
                    </>
                )}
                </div>
                <dl>
                  <div>
                    <dt>{t('cases.overview.openWhen')}</dt>
                    <dd>
                      {isOverviewEditing ? (
                        <textarea
                          aria-label={t('cases.overview.openWhen')}
                          onChange={(event) => setOpenWhenDraft(event.target.value)}
                          rows={3}
                          value={openWhenDraft}
                        />
                      ) : (
                        item.open_when_text ?? t('cases.overview.openWhenEmpty')
                      )}
                    </dd>
                  </div>
                  <div>
                    <dt>{t('cases.overview.closedWhen')}</dt>
                    <dd>
                      {isOverviewEditing ? (
                        <textarea
                          aria-label={t('cases.overview.closedWhen')}
                          onChange={(event) => setClosedWhenDraft(event.target.value)}
                          rows={3}
                          value={closedWhenDraft}
                        />
                      ) : (
                        item.closed_when_text ?? t('cases.overview.doneCriteriaEmpty')
                      )}
                    </dd>
                  </div>
                </dl>
              </section>
              <section className="case-ai-status-panel">
                <div className="case-ai-status-heading">
                  <div>
                    <span>{t('cases.aiStatus.eyebrow')}</span>
                    <h2>{t('cases.aiStatus.heading')}</h2>
                  </div>
                  <button type="button">{t('cases.aiStatus.refresh')}</button>
                </div>
                <p>{t('cases.aiStatus.empty')}</p>
                <div className="case-ai-status-grid">
                  <span>{t('cases.aiStatus.source.mail')}</span>
                  <span>{t('cases.aiStatus.source.task')}</span>
                  <span>{t('cases.aiStatus.source.calendar')}</span>
                  <span>{t('cases.aiStatus.source.file')}</span>
                </div>
              </section>
              <div className="case-workbench-grid">
                <CaseWorkbenchPanel
                  actionLabel={t('cases.mail.attach')}
                  actionHref={`/cases/${encodeURIComponent(item.id)}/mails`}
                  count={item.mail_count}
                  eyebrow={t('cases.section.mail')}
                  title={t('cases.mail.window')}
                >
                  <div className="case-mail-preview-list">
                    <div>
                      <time>--:--</time>
                      <span>{t('cases.mail.empty')}</span>
                      <b>{t('cases.card.none')}</b>
                    </div>
                  </div>
                </CaseWorkbenchPanel>
                <CaseWorkbenchPanel
                  actionLabel={t('cases.task.new')}
                  count={item.open_task_count}
                  eyebrow={t('cases.section.tasks')}
                  title={t('cases.task.window')}
                >
                  <div className="case-task-lane">
                    <div>
                      <span>{t('cases.task.next')}</span>
                      <strong>{item.next_task?.title ?? t('cases.card.none')}</strong>
                      <small>{formatDateTime(item.next_task?.due_at ?? null)}</small>
                    </div>
                    <div>
                      <span>{t('cases.task.overdue')}</span>
                      <strong>{item.overdue_task_count}</strong>
                    </div>
                  </div>
                </CaseWorkbenchPanel>
              </div>
              <CaseStorageWindow rootDirectoryId={item.storage_directory_id} />
              <CaseStakeholdersPanel
                caseId={item.id}
                initialStakeholders={detail.stakeholders ?? []}
              />
            </div>
            <aside aria-label={t('cases.gadgets')} className="case-gadget-column">
              <CaseCalendarGadget caseItem={item} />
              <CaseToolsGadget caseId={item.id} initialTools={detail.tool_links ?? []} />
              <button className="case-complete-gadget-button" type="button">
                {t('cases.complete.button')}
              </button>
            </aside>
          </div>
        )}
      </div>
    </main>
  )
}

function CaseCreateView() {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [ballStatus, setBallStatus] = useState('none')
  const [genres, setGenres] = useState<CaseGenre[]>([])
  const [genreId, setGenreId] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let isMounted = true
    listCaseGenres()
      .then((items) => {
        if (isMounted) setGenres(items)
      })
      .catch((requestError) => {
        if (isMounted) setError(describeError(requestError))
      })
    return () => {
      isMounted = false
    }
  }, [])

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setIsSubmitting(true)
    setError(null)
    try {
      const created = await createCase({
        name,
        description: description.trim() === '' ? null : description,
        progress_status: 'not_started',
        ball_status: ballStatus,
        genre_id: genreId === '' ? null : genreId,
      })
      navigateTo(`/cases/${encodeURIComponent(created.id)}`)
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <main className="app-shell">
      <div className="case-shell">
        <header className="maintenance-header">
          <div>
            <p>{t('app.name')}</p>
            <h1>{t('cases.new')}</h1>
          </div>
          <nav aria-label={t('cases.navigation')} className="maintenance-nav">
            <AppLink href="/cases">{t('cases.heading')}</AppLink>
            <AppLink href="/">{t('top.heading')}</AppLink>
          </nav>
        </header>

        {error !== null && (
          <div className="mail-feedback">
            <p role="alert">{error}</p>
          </div>
        )}

        <form className="case-form" onSubmit={handleSubmit}>
          <label>
            <span>{t('cases.name')}</span>
            <input
              autoFocus
              onChange={(event) => setName(event.target.value)}
              required
              type="text"
              value={name}
            />
          </label>
          <label>
            <span>{t('cases.description')}</span>
            <textarea
              onChange={(event) => setDescription(event.target.value)}
              rows={5}
              value={description}
            />
          </label>
          <label>
            <span>{t('cases.genre.select')}</span>
            <select onChange={(event) => setGenreId(event.target.value)} value={genreId}>
              <option value="">{t('cases.genre.none')}</option>
                  {genres.map((genre) => (
                    <option key={genre.id} value={genre.id}>
                      {genre.title}
                    </option>
              ))}
            </select>
          </label>
          <label>
            <span>{t('cases.ball')}</span>
            <select onChange={(event) => setBallStatus(event.target.value)} value={ballStatus}>
              <option value="none">{t('cases.ball.none')}</option>
              <option value="user">{t('cases.ball.user')}</option>
              <option value="other">{t('cases.ball.other')}</option>
              <option value="date_wait">{t('cases.ball.dateWait')}</option>
              <option value="stalled">{t('cases.ball.stalled')}</option>
            </select>
          </label>
          <button className={`button-loading-dot${isSubmitting ? ' is-loading' : ''}`} type="submit">
            {t('cases.create')}
          </button>
        </form>
      </div>
    </main>
  )
}

function CaseMailListView({ caseId }: { caseId: string }) {
  const [caseItem, setCaseItem] = useState<CaseItem | null>(null)
  const [mailLinks, setMailLinks] = useState<CaseMailLink[]>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let isMounted = true
    setIsLoading(true)
    setError(null)
    Promise.all([getCase(caseId), listCaseMailLinks(caseId)])
      .then(([detail, links]) => {
        if (!isMounted) return
        setCaseItem(detail.case)
        setMailLinks(links)
      })
      .catch((requestError) => {
        if (isMounted) setError(describeError(requestError))
      })
      .finally(() => {
        if (isMounted) setIsLoading(false)
      })
    return () => {
      isMounted = false
    }
  }, [caseId])

  const normalizedQuery = searchQuery.trim().toLowerCase()
  const visibleMailLinks = mailLinks.filter((mail) => {
    if (normalizedQuery === '') return true
    return [
      mail.subject ?? '',
      mail.from_name ?? '',
      mail.from_address,
      mail.summary ?? '',
      mail.effective_importance,
      mail.processed_status,
    ]
      .join(' ')
      .toLowerCase()
      .includes(normalizedQuery)
  })

  return (
    <main className="app-shell">
      <div className="case-shell">
        <header className="maintenance-header">
          <div>
            <p>{t('app.name')}</p>
            <h1>{t('cases.mail.assignedHeading')}</h1>
            {caseItem !== null && <span>{caseItem.name}</span>}
          </div>
          <nav aria-label={t('cases.navigation')} className="maintenance-nav">
            <AppLink href={`/cases/${encodeURIComponent(caseId)}`}>{t('cases.detailHeading')}</AppLink>
            <AppLink href="/cases">{t('cases.heading')}</AppLink>
            <AppLink href="/mail">{t('mail.heading')}</AppLink>
          </nav>
        </header>

        {error !== null && (
          <div className="mail-feedback">
            <p role="alert">{error}</p>
          </div>
        )}

        <section className="case-mail-assignment-tools">
          <div className="section-heading">
            <h2>{t('cases.mail.assignedTools')}</h2>
          </div>
          <label>
            <span>{t('cases.search.label')}</span>
            <input
              aria-label={t('cases.search.label')}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder={t('cases.mail.searchPlaceholder')}
              type="search"
              value={searchQuery}
            />
          </label>
        </section>

        <section className="case-mail-assignment-panel">
          <div className="section-heading">
            <div>
              <h2>{t('cases.mail.assignedList')}</h2>
              <p>{t('cases.mail.assignedCount', { count: visibleMailLinks.length })}</p>
            </div>
          </div>
          {isLoading ? (
            <p className="mail-empty">{t('cases.loading')}</p>
          ) : visibleMailLinks.length === 0 ? (
            <p className="mail-empty">{t('cases.mail.assignedEmpty')}</p>
          ) : (
            <div className="case-assigned-mail-list">
              {visibleMailLinks.map((mail) => (
                <AppLink className="case-assigned-mail-row" href={mail.mail_url} key={mail.id}>
                  <time>{formatDateTime(mail.received_at)}</time>
                  <div>
                    <strong>{mail.subject ?? t('mail.noSubject')}</strong>
                    <span>{mail.from_name ?? mail.from_address}</span>
                  </div>
                  <p>{mail.summary ?? ''}</p>
                  <div className="case-assigned-mail-badges">
                    <span>{mail.effective_importance}</span>
                    <span>{mail.processed_status}</span>
                  </div>
                </AppLink>
              ))}
            </div>
          )}
        </section>
      </div>
    </main>
  )
}

export default function CaseView({
  caseId,
  mode = 'list',
}: {
  caseId?: string
  mode?: 'list' | 'detail' | 'new' | 'mail-list'
}) {
  if (mode === 'new') {
    return <CaseCreateView />
  }
  if (mode === 'mail-list' && caseId !== undefined) {
    return <CaseMailListView caseId={caseId} />
  }
  if (mode === 'detail' && caseId !== undefined) {
    return <CaseDetailView caseId={caseId} />
  }
  return <CaseListView />
}
