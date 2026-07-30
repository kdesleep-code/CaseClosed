import { useEffect, useState } from 'react'
import type { DragEvent, MouseEvent, ReactNode } from 'react'
import { t } from './i18n'
import { navigateTo } from './navigation'
import defaultContactAvatarUrl from './assets/default-contact-avatar.svg'
import downloadIconUrl from './assets/download-icon.svg'
import folderDirectoryIconUrl from './assets/folder-directory-icon.svg'
import paperclipDiagonalUrl from './assets/paperclip-diagonal.svg'
import trashIconUrl from './assets/trash-icon.svg'
import { fileExtension } from './storagePreview'
import {
  createStorageDirectory,
  deleteStorageDirectory,
  deleteStorageObject,
  listStorageDirectories,
  listStorageExtensions,
  listStorageObjects,
  moveStorageDirectoryToDirectory,
  moveStorageObjectToDirectory,
  searchStorageObjects,
  updateStorageObjectLlmInput,
} from './phase3Api'
import type {
  StorageDirectory,
  StorageObject,
  StorageSourceMail,
} from './phase3Api'
import { listCaseFiles, unlinkCaseFile } from './phase7Api'
import {
  droppedStorageFilesFromDataTransfer,
  uploadDroppedStorageFiles,
} from './storageDirectoryDrop'

export const storageObjectDragType = 'application/x-caseclosed-storage-object'
export const storageDirectoryDragType = 'application/x-caseclosed-storage-directory'

type StorageBrowserContextMenu = {
  directory: StorageDirectory | null
  object: StorageObject | null
  x: number
  y: number
}

type StorageBrowserTopTools = {
  breadcrumbs: StorageDirectory[]
  openRootDirectory: () => void
  openDirectory: (directory: StorageDirectory) => void
  onDirectoryDragOver: (event: DragEvent<HTMLElement>) => void
  onDirectoryDrop: (event: DragEvent<HTMLElement>, directoryId: string | null) => void
}

type StorageBrowserProps = {
  rootDirectoryId: string | null
  rootLabel: string
  heading?: string
  body?: string
  caseId?: string
  rootListMode?: 'case' | 'directory'
  deleteMode?: 'case' | 'physical'
  currentDirectoryId?: string | null
  searchQuery?: string
  sortMode?: 'created_desc' | 'created_asc' | 'name'
  extensionFilter?: string | null
  panelClassName?: string
  gridClassName?: string
  breadcrumbClassName?: string
  showBreadcrumb?: boolean
  showHeading?: boolean
  showPath?: boolean
  collapsible?: boolean
  defaultCollapsed?: boolean
  extraHeadingActions?: ReactNode
  renderTopTools?: (tools: StorageBrowserTopTools) => ReactNode
  onAvailableExtensionsChange?: (extensions: string[]) => void
  onDirectoryChange?: (directoryId: string | null) => void
  onOpenDirectory?: (directory: StorageDirectory | null) => void
  onOpenObject?: (object: StorageObject) => void
}

function describeError(error: unknown) {
  return error instanceof Error ? error.message : t('storage.requestFailed')
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`
  const kib = value / 1024
  if (kib < 1024) return `${kib.toFixed(kib >= 10 ? 0 : 1)} KB`
  const mib = kib / 1024
  if (mib < 1024) return `${mib.toFixed(mib >= 10 ? 0 : 1)} MB`
  const gib = mib / 1024
  return `${gib.toFixed(gib >= 10 ? 0 : 1)} GB`
}

function directoryPathLabel(path: string[] | undefined) {
  if (path === undefined || path.length === 0) {
    return t('storage.directory.root')
  }
  return [t('storage.directory.root'), ...path].join(' / ')
}

function storageSourceMailSender(mail: StorageSourceMail) {
  return mail.from_name?.trim() || mail.from_address
}

export async function downloadStorageObject(object: {
  id: string
  original_filename: string | null
  download_url?: string
}) {
  const href = object.download_url ?? `/api/v1/storage/objects/${encodeURIComponent(object.id)}/download`
  const anchor = document.createElement('a')
  anchor.href = href
  anchor.download = object.original_filename ?? object.id
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
}

function openStorageObjectInNewWindow(object: StorageObject) {
  const openedWindow = window.open(
    `/files/${encodeURIComponent(object.id)}`,
    '_blank',
    'noopener,noreferrer',
  )
  if (openedWindow !== null) {
    openedWindow.opener = null
  }
}

export function ActionIconLabel({
  iconUrl,
  label,
}: {
  iconUrl: string
  label: string
}) {
  return (
    <span className="storage-action-label">
      <img alt="" aria-hidden="true" src={iconUrl} />
      <span>{label}</span>
    </span>
  )
}

function LlmInputBlockedIcon() {
  return (
    <svg
      aria-hidden="true"
      className="storage-llm-blocked-icon"
      viewBox="0 0 48 48"
    >
      <rect fill="none" height="48" width="48" />
      <path
        d="M17 18h14a7 7 0 0 1 7 7v7a7 7 0 0 1-7 7H17a7 7 0 0 1-7-7v-7a7 7 0 0 1 7-7Z"
        fill="#fff6e8"
        stroke="#6e3428"
        strokeWidth="3"
      />
      <path d="M24 18v-5" stroke="#6e3428" strokeLinecap="round" strokeWidth="3" />
      <circle cx="24" cy="10" fill="#6e3428" r="3" />
      <circle cx="19" cy="28" fill="#6e3428" r="2.5" />
      <circle cx="29" cy="28" fill="#6e3428" r="2.5" />
      <path d="M19 34h10" stroke="#6e3428" strokeLinecap="round" strokeWidth="3" />
      <circle
        cx="34"
        cy="34"
        fill="#fff6e8"
        r="10"
        stroke="#b34035"
        strokeWidth="4"
      />
      <path d="M27 41 41 27" stroke="#b34035" strokeLinecap="round" strokeWidth="4" />
    </svg>
  )
}

export function StorageObjectCard({
  object,
  busy,
  selected,
  showPath = false,
  onContextMenu,
  onOpen,
}: {
  object: StorageObject
  busy: boolean
  selected: boolean
  showPath?: boolean
  onContextMenu: (event: MouseEvent<HTMLButtonElement>, object: StorageObject) => void
  onOpen: (object: StorageObject) => void
}) {
  const filename = object.original_filename ?? object.id
  const customIconUrl = object.file_icon_url ?? ''
  const hasCustomIcon = customIconUrl !== ''
  return (
    <button
      aria-label={t('storage.openFile', { name: filename })}
      aria-selected={selected}
      className={`storage-object-card button-loading-dot${
        object.display_source === 'link' ? ' storage-object-card-linked' : ''
      }${busy ? ' is-loading' : ''}`}
      data-storage-object-id={object.id}
      draggable
      disabled={busy}
      onClick={() => onOpen(object)}
      onContextMenu={(event) => onContextMenu(event, object)}
      onDragStart={(event) => {
        event.dataTransfer.clearData()
        event.dataTransfer.setData(storageObjectDragType, object.id)
        event.dataTransfer.setData('text/plain', object.id)
        event.dataTransfer.effectAllowed = 'copyMove'
      }}
      type="button"
    >
      {!object.llm_input_allowed && (
        <span className="storage-llm-blocked-badge" title={t('storage.llmInput.blocked')}>
          <LlmInputBlockedIcon />
        </span>
      )}
      <span
        aria-hidden="true"
        className={`storage-object-icon${hasCustomIcon ? ' storage-object-image-icon' : ''}`}
      >
        {hasCustomIcon ? (
          <img alt="" draggable={false} src={customIconUrl} />
        ) : (
          fileExtension(object.original_filename)
        )}
      </span>
      <span className="storage-object-card-main">
        <strong>{filename}</strong>
      </span>
      <span className="storage-object-card-meta">
        <span>{object.created_at.slice(0, 10)}</span>
        <span>{formatBytes(object.byte_size)}</span>
        {showPath && <span>{directoryPathLabel(object.directory_path)}</span>}
      </span>
    </button>
  )
}

export function StorageDirectoryCard({
  directory,
  onDropFiles,
  onDropDirectory,
  onDropObject,
  onContextMenu,
  onOpen,
}: {
  directory: StorageDirectory
  onDropFiles?: (dataTransfer: DataTransfer, directoryId: string) => void
  onDropDirectory?: (directoryId: string, parentId: string | null) => void
  onDropObject: (objectId: string, directoryId: string | null) => void
  onContextMenu: (event: MouseEvent<HTMLButtonElement>, directory: StorageDirectory) => void
  onOpen: (directory: StorageDirectory) => void
}) {
  const isTaskDirectory = directory.directory_kind === 'task'
  const isCaseDirectory =
    directory.directory_kind === 'case' || (directory.case_id !== null && !isTaskDirectory)
  return (
    <button
      aria-label={t('storage.openDirectory', { name: directory.name })}
      className={`storage-object-card storage-directory-card${
        isCaseDirectory ? ' storage-case-directory-card' : ''
      }${isTaskDirectory ? ' storage-task-directory-card' : ''}`}
      draggable
      onClick={() => onOpen(directory)}
      onContextMenu={(event) => onContextMenu(event, directory)}
      onDragStart={(event) => {
        event.dataTransfer.clearData()
        event.dataTransfer.setData(storageDirectoryDragType, directory.id)
        event.dataTransfer.effectAllowed = 'move'
      }}
      onDragOver={(event) => {
        event.preventDefault()
        event.stopPropagation()
        event.dataTransfer.dropEffect = event.dataTransfer.types.includes('Files') ? 'copy' : 'move'
      }}
      onDrop={(event) => {
        event.preventDefault()
        event.stopPropagation()
        const draggedDirectoryId = event.dataTransfer.getData(storageDirectoryDragType)
        if (draggedDirectoryId !== '') {
          if (draggedDirectoryId !== directory.id) {
            onDropDirectory?.(draggedDirectoryId, directory.id)
          }
          return
        }
        const objectId =
          event.dataTransfer.getData(storageObjectDragType) ||
          event.dataTransfer.getData('text/plain')
        if (objectId !== '') {
          onDropObject(objectId, directory.id)
          return
        }
        if (event.dataTransfer.types.includes('Files')) {
          onDropFiles?.(event.dataTransfer, directory.id)
        }
      }}
      type="button"
    >
      <span aria-hidden="true" className="storage-object-icon storage-directory-icon">
        <img alt="" src={folderDirectoryIconUrl} />
      </span>
      <span className="storage-object-card-main">
        <strong>{directory.name}</strong>
      </span>
      <span className="storage-object-card-meta">
        <span>{directory.created_at.slice(0, 10)}</span>
        <span>{t('storage.directory.label')}</span>
      </span>
    </button>
  )
}

function StorageSourceMailCard({ mail }: { mail: StorageSourceMail }) {
  return (
    <section className="storage-source-mail-section">
      <h2>{t('storage.source.mail')}</h2>
      <article
        className="mail-list-item storage-source-mail-card mail-read-read"
        onClick={() => navigateTo(`/mail/${encodeURIComponent(mail.id)}`)}
        role="link"
        tabIndex={0}
      >
        <div className="mail-list-sender-media">
          <span className="mail-list-time">{mail.received_at.slice(11, 16)}</span>
          <img
            alt={t('mail.senderAvatarAlt', {
              name: storageSourceMailSender(mail),
            })}
            src={defaultContactAvatarUrl}
          />
        </div>
        <div className="mail-list-main">
          <strong>
            <span>{mail.subject ?? t('mail.noSubject')}</span>
          </strong>
          <span>{storageSourceMailSender(mail)}</span>
        </div>
        <p className="mail-list-summary">{mail.summary ?? ''}</p>
        <div className="mail-list-cases">
          {mail.has_attachments === true && (
            <span
              aria-label={t('mail.attachmentsPresent')}
              className="mail-attachment-indicator"
              title={t('mail.attachmentsPresent')}
            >
              <img alt="" src={paperclipDiagonalUrl} />
            </span>
          )}
          <span>{t('mail.noCase')}</span>
        </div>
      </article>
    </section>
  )
}

export default function StorageBrowser({
  rootDirectoryId,
  rootLabel,
  heading = t('storage.objects'),
  body = t('storage.objectsBody'),
  caseId,
  rootListMode = 'directory',
  deleteMode = 'physical',
  currentDirectoryId: controlledDirectoryId,
  searchQuery = '',
  sortMode = 'created_desc',
  extensionFilter = null,
  panelClassName = 'mail-panel storage-objects-panel',
  gridClassName = 'storage-object-grid',
  breadcrumbClassName = 'storage-breadcrumb',
  showBreadcrumb = true,
  showHeading = true,
  showPath,
  collapsible = false,
  defaultCollapsed = false,
  extraHeadingActions = null,
  renderTopTools,
  onAvailableExtensionsChange,
  onDirectoryChange,
  onOpenDirectory,
  onOpenObject,
}: StorageBrowserProps) {
  const [internalDirectoryId, setInternalDirectoryId] = useState<string | null>(
    controlledDirectoryId ?? rootDirectoryId,
  )
  const currentDirectoryId = controlledDirectoryId ?? internalDirectoryId
  const [isCollapsed, setIsCollapsed] = useState(defaultCollapsed)
  const [objects, setObjects] = useState<StorageObject[]>([])
  const [directories, setDirectories] = useState<StorageDirectory[]>([])
  const [breadcrumbs, setBreadcrumbs] = useState<StorageDirectory[]>([])
  const [contextMenu, setContextMenu] = useState<StorageBrowserContextMenu | null>(null)
  const [selectedObjectId, setSelectedObjectId] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [isDragOver, setIsDragOver] = useState(false)
  const [downloadBusyId, setDownloadBusyId] = useState<string | null>(null)
  const [llmBusyId, setLlmBusyId] = useState<string | null>(null)
  const [deleteBusyId, setDeleteBusyId] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [debouncedSearchQuery, setDebouncedSearchQuery] = useState(searchQuery)
  const isSearchMode = debouncedSearchQuery.trim() !== '' || extensionFilter !== null

  useEffect(() => {
    const timerId = window.setTimeout(() => {
      setDebouncedSearchQuery(searchQuery)
    }, 250)
    return () => window.clearTimeout(timerId)
  }, [searchQuery])

  useEffect(() => {
    setInternalDirectoryId(controlledDirectoryId ?? rootDirectoryId)
  }, [controlledDirectoryId, rootDirectoryId])

  async function refreshStorage() {
    setError(null)
    if (isSearchMode) {
      const [searchResult, nextDirectories] = await Promise.all([
        searchStorageObjects({
          query: debouncedSearchQuery,
          directory_id: currentDirectoryId,
          recursive: true,
          sort: sortMode,
          extension: extensionFilter,
          limit: 200,
        }),
        listStorageDirectories(currentDirectoryId),
      ])
      setObjects(searchResult.items)
      setDirectories([])
      setBreadcrumbs(nextDirectories.breadcrumbs)
      onAvailableExtensionsChange?.(searchResult.extensions)
      return
    }

    const objectsRequest =
      rootListMode === 'case' && currentDirectoryId === rootDirectoryId && caseId !== undefined
        ? listCaseFiles(caseId)
        : listStorageObjects({ directory_id: currentDirectoryId, limit: 200 })
    const [nextObjects, nextDirectories, nextExtensions] = await Promise.all([
      objectsRequest,
      listStorageDirectories(currentDirectoryId),
      listStorageExtensions({
        directory_id: currentDirectoryId,
        recursive: true,
      }),
    ])
    setObjects(nextObjects)
    setDirectories(nextDirectories.items)
    setBreadcrumbs(nextDirectories.breadcrumbs)
    onAvailableExtensionsChange?.(nextExtensions)
  }

  useEffect(() => {
    let isMounted = true
    setIsLoading(true)
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
  }, [currentDirectoryId, debouncedSearchQuery, sortMode, extensionFilter, caseId, rootListMode])

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

  function setDirectory(directoryId: string | null) {
    setSelectedObjectId(null)
    setContextMenu(null)
    setInternalDirectoryId(directoryId)
    onDirectoryChange?.(directoryId)
  }

  function handleOpenDirectory(directory: StorageDirectory) {
    setDirectory(directory.id)
    onOpenDirectory?.(directory)
  }

  function handleOpenRootDirectory() {
    setDirectory(rootDirectoryId)
    onOpenDirectory?.(null)
  }

  async function uploadDroppedItems(dataTransfer: DataTransfer, directoryId: string | null) {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const droppedFiles = await droppedStorageFilesFromDataTransfer(dataTransfer)
      if (droppedFiles.length === 0) {
        setError(t('storage.noFileSelected'))
        return
      }
      const result = await uploadDroppedStorageFiles(droppedFiles, directoryId)
      setNotice(
        result.count === 1
          ? t('storage.uploaded', { name: result.lastUploadedName })
          : t('storage.uploadedMany', { count: String(result.count) }),
      )
      await refreshStorage()
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setBusy(false)
    }
  }

  async function handleMoveStorageObject(objectId: string, directoryId: string | null) {
    if (objectId === '') return
    const draggedObject = objects.find((object) => object.id === objectId)
    if (
      draggedObject !== undefined &&
      (draggedObject.physical_directory_id ?? draggedObject.directory_id ?? null) === directoryId
    ) {
      setSelectedObjectId(objectId)
      return
    }
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

  async function handleMoveStorageDirectory(directoryId: string, parentId: string | null) {
    if (directoryId === '') return
    if (directoryId === parentId) return
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const movedDirectory = await moveStorageDirectoryToDirectory(directoryId, parentId)
      setSelectedObjectId(null)
      setNotice(t('storage.directory.moved', { name: movedDirectory.name }))
      await refreshStorage()
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setBusy(false)
    }
  }

  function directoryIdFromDragEvent(event: DragEvent<HTMLElement>) {
    return event.dataTransfer.getData(storageDirectoryDragType)
  }

  function objectIdFromDragEvent(event: DragEvent<HTMLElement>) {
    if (directoryIdFromDragEvent(event) !== '') return ''
    return (
      event.dataTransfer.getData(storageObjectDragType) ||
      event.dataTransfer.getData('text/plain')
    )
  }

  function isStorageObjectDrag(event: DragEvent<HTMLElement>) {
    return Array.from(event.dataTransfer.types).includes(storageObjectDragType)
  }

  function isStorageDirectoryDrag(event: DragEvent<HTMLElement>) {
    return Array.from(event.dataTransfer.types).includes(storageDirectoryDragType)
  }

  function handleDirectoryDragOver(event: DragEvent<HTMLElement>) {
    event.preventDefault()
    event.stopPropagation()
    event.dataTransfer.dropEffect = 'move'
  }

  function handleDirectoryDrop(event: DragEvent<HTMLElement>, directoryId: string | null) {
    event.preventDefault()
    event.stopPropagation()
    const draggedDirectoryId = directoryIdFromDragEvent(event)
    if (draggedDirectoryId !== '') {
      void handleMoveStorageDirectory(draggedDirectoryId, directoryId)
      return
    }
    const objectId = objectIdFromDragEvent(event)
    if (objectId !== '') {
      void handleMoveStorageObject(objectId, directoryId)
      return
    }
    if (Array.from(event.dataTransfer.types).includes('Files')) {
      void uploadDroppedItems(event.dataTransfer, directoryId)
    }
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setIsDragOver(false)
    const draggedDirectoryId = directoryIdFromDragEvent(event)
    if (draggedDirectoryId !== '') {
      void handleMoveStorageDirectory(draggedDirectoryId, currentDirectoryId)
      return
    }
    const objectId = objectIdFromDragEvent(event)
    if (objectId !== '') {
      void handleMoveStorageObject(objectId, currentDirectoryId)
      return
    }
    if (!Array.from(event.dataTransfer.types).includes('Files')) return
    void uploadDroppedItems(event.dataTransfer, currentDirectoryId)
  }

  function handleDragOver(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    event.dataTransfer.dropEffect =
      isStorageDirectoryDrag(event) || isStorageObjectDrag(event)
        ? 'move'
        : event.dataTransfer.types.includes('Files') ? 'copy' : 'none'
    setIsDragOver(true)
  }

  function handleDragLeave(event: DragEvent<HTMLDivElement>) {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
      setIsDragOver(false)
    }
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
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setLlmBusyId(null)
    }
  }

  async function handleDelete(object: StorageObject) {
    if (deleteMode === 'physical' || object.display_source !== 'link') {
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
      return
    }
    const choice = window.prompt(
      t('cases.storage.deleteChoice', { name: object.original_filename ?? object.id }),
      'exclude',
    )
    const normalizedChoice = choice?.trim().toLowerCase() ?? ''
    if (normalizedChoice === '') return
    if (!['exclude', 'delete'].includes(normalizedChoice)) {
      setError(t('cases.storage.deleteChoiceInvalid'))
      return
    }
    setDeleteBusyId(object.id)
    setError(null)
    setNotice(null)
    try {
      if (normalizedChoice === 'exclude') {
        if (caseId === undefined) throw new Error(t('storage.requestFailed'))
        await unlinkCaseFile(caseId, object.id)
      } else {
        if (!window.confirm(t('storage.delete.confirm', { name: object.original_filename ?? object.id }))) {
          return
        }
        await deleteStorageObject(object.id)
      }
      setObjects((currentObjects) =>
        currentObjects.filter((currentObject) => currentObject.id !== object.id),
      )
      setSelectedObjectId((currentId) => (currentId === object.id ? null : currentId))
      setNotice(
        normalizedChoice === 'exclude'
          ? t('cases.storage.unlinked', { name: object.original_filename ?? object.id })
          : t('storage.deleted', { name: object.original_filename ?? object.id }),
      )
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setDeleteBusyId(null)
    }
  }

  function handleOpenStorageObject(object: StorageObject) {
    setSelectedObjectId(object.id)
    setContextMenu(null)
    if (onOpenObject !== undefined) {
      onOpenObject(object)
      return
    }
    navigateTo(`/files/${encodeURIComponent(object.id)}`)
  }

  async function createDirectoryByPrompt() {
    setContextMenu(null)
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
    if (target?.closest('.storage-object-card') !== null) return
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

  const rootIndex =
    rootDirectoryId === null
      ? -1
      : breadcrumbs.findIndex((directory) => directory.id === rootDirectoryId)
  const visibleBreadcrumbs =
    rootDirectoryId === null
      ? breadcrumbs
      : rootIndex >= 0 ? breadcrumbs.slice(rootIndex + 1) : breadcrumbs

  const topTools = renderTopTools?.({
    breadcrumbs,
    openRootDirectory: handleOpenRootDirectory,
    openDirectory: handleOpenDirectory,
    onDirectoryDragOver: handleDirectoryDragOver,
    onDirectoryDrop: handleDirectoryDrop,
  })

  return (
    <section className={`case-storage-window${isCollapsed ? ' is-collapsed' : ''}`}>
      {collapsible && (
        <div className="case-storage-window-header">
          <div>
            <h2>{heading}</h2>
            {body !== '' && <p>{body}</p>}
          </div>
          <button
            aria-expanded={!isCollapsed}
            onClick={() => {
              setContextMenu(null)
              setIsCollapsed((current) => !current)
            }}
            type="button"
          >
            {isCollapsed ? t('common.expand') : t('common.collapse')}
          </button>
        </div>
      )}
      {(error !== null || notice !== null) && (
        <div className="mail-feedback case-storage-feedback">
          {error !== null && <p role="alert">{error}</p>}
          {notice !== null && <p>{notice}</p>}
        </div>
      )}
      {!isCollapsed && (
        <>
          {topTools}
          {showBreadcrumb && (
            <nav aria-label={t('storage.directory.breadcrumb')} className={breadcrumbClassName}>
              <button
                onClick={handleOpenRootDirectory}
                onDragOver={handleDirectoryDragOver}
                onDrop={(event) => handleDirectoryDrop(event, rootDirectoryId)}
                type="button"
              >
                {rootLabel}
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
          )}
          <div
            className={`${panelClassName} storage-drop-zone button-loading-dot${
              busy ? ' is-loading' : ''
            }${isDragOver ? ' is-drag-over' : ''}`}
            onContextMenu={handleStoragePanelContextMenu}
            onDragLeave={handleDragLeave}
            onDragOver={handleDragOver}
            onDrop={handleDrop}
          >
            {showHeading && (
              <div className="section-heading case-storage-drop-heading">
                <div>
                  <h2>{heading}</h2>
                </div>
                <div className="storage-heading-actions">
                  {body !== '' && <p>{body}</p>}
                  {extraHeadingActions}
                </div>
              </div>
            )}
            <div className={gridClassName}>
              {directories.map((directory) => (
                <StorageDirectoryCard
                  directory={directory}
                  key={directory.id}
                  onContextMenu={handleStorageDirectoryContextMenu}
                  onDropFiles={(dataTransfer, directoryId) =>
                    void uploadDroppedItems(dataTransfer, directoryId)
                  }
                  onDropDirectory={(directoryId, parentId) =>
                    void handleMoveStorageDirectory(directoryId, parentId)
                  }
                  onDropObject={(objectId, directoryId) =>
                    void handleMoveStorageObject(objectId, directoryId)
                  }
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
                  showPath={showPath ?? isSearchMode}
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
                  <button
                    onClick={() => {
                      setContextMenu(null)
                      void createDirectoryByPrompt()
                    }}
                    role="menuitem"
                    type="button"
                  >
                    {t('storage.context.newDirectory')}
                  </button>
                )}
                {contextMenu.directory !== null &&
                  contextMenu.directory.directory_kind !== 'case' &&
                  contextMenu.directory.case_id === null && (
                    <button
                      onClick={() => {
                        const directory = contextMenu.directory
                        setContextMenu(null)
                        if (directory !== null) void handleDeleteDirectory(directory)
                      }}
                      role="menuitem"
                      type="button"
                    >
                      <ActionIconLabel
                        iconUrl={trashIconUrl}
                        label={t('storage.context.deleteDirectory')}
                      />
                    </button>
                  )}
                {contextMenu.object !== null && (
                  <>
                    <button
                      onClick={() => {
                        const object = contextMenu.object
                        setContextMenu(null)
                        if (object !== null) openStorageObjectInNewWindow(object)
                      }}
                      role="menuitem"
                      type="button"
                    >
                      {t('storage.context.openInNewWindow')}
                    </button>
                    <button
                      onClick={() => {
                        const object = contextMenu.object
                        setContextMenu(null)
                        if (object !== null) void handleDownload(object)
                      }}
                      role="menuitem"
                      type="button"
                    >
                      <ActionIconLabel
                        iconUrl={downloadIconUrl}
                        label={t('storage.context.download')}
                      />
                    </button>
                    <button
                      onClick={() => {
                        const object = contextMenu.object
                        setContextMenu(null)
                        if (object !== null) void handleUpdateLlmInput(object, !object.llm_input_allowed)
                      }}
                      role="menuitem"
                      type="button"
                    >
                      {contextMenu.object.llm_input_allowed
                        ? t('storage.llmInput.disallow')
                        : t('storage.llmInput.allow')}
                    </button>
                    <button
                      onClick={() => {
                        const object = contextMenu.object
                        setContextMenu(null)
                        if (object !== null) void handleDelete(object)
                      }}
                      role="menuitem"
                      type="button"
                    >
                      <ActionIconLabel iconUrl={trashIconUrl} label={t('storage.context.delete')} />
                    </button>
                  </>
                )}
              </div>
            )}
          </div>
          {objects.some((object) => object.source_mail !== null && object.source_mail !== undefined) &&
            objects.map((object) =>
              object.source_mail ? (
                <StorageSourceMailCard key={`source-${object.id}`} mail={object.source_mail} />
              ) : null,
            )}
        </>
      )}
    </section>
  )
}
