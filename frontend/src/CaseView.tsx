import { useEffect, useMemo, useState } from 'react'
import type { CSSProperties, DragEvent, FormEvent, MouseEvent, ReactNode } from 'react'
import { t } from './i18n'
import { AppLink, navigateTo } from './navigation'
import downloadIconUrl from './assets/download-icon.svg'
import defaultContactAvatarUrl from './assets/default-contact-avatar.svg'
import defaultMailingListAvatarUrl from './assets/default-mailing-list-avatar.svg'
import defaultServiceAvatarUrl from './assets/default-service-avatar.svg'
import defaultSpamAvatarUrl from './assets/default-spam-avatar.webp'
import paperclipDiagonalUrl from './assets/paperclip-diagonal.svg'
import settingsGearIconUrl from './assets/settings-gear.svg'
import trashIconUrl from './assets/trash-icon.svg'
import {
  createStorageDirectory,
  deleteStorageDirectory,
  deleteStorageObject,
  listStorageDirectories,
  listStorageObjects,
  moveStorageDirectoryToDirectory,
  moveStorageObjectToDirectory,
  updateStorageObjectLlmInput,
} from './phase3Api'
import { listContacts } from './phase3Api'
import type { Contact, StorageDirectory, StorageObject } from './phase3Api'
import {
  assignMailThreadToCase,
  importSpecialGoogleGmailThread,
  listMailPage,
  unassignMailThreadFromCase,
} from './phase4Api'
import type { MailListItem } from './phase4Api'
import {
  caseRoleSelectorSuggestions,
  resolveContactSelectorListWithCases,
} from './contactSelectors'
import {
  droppedStorageFilesFromDataTransfer,
  uploadDroppedStorageFiles,
} from './storageDirectoryDrop'
import type { ContactSelectorCaseContext } from './contactSelectors'
import SuggestInput from './SuggestInput'
import type { SuggestInputOption } from './SuggestInput'
import {
  archiveCase,
  completeCase,
  createCaseAutoAssignRule,
  createCaseStakeholder,
  createCase,
  createCaseToolLink,
  createCaseGenre,
  deleteCaseStakeholder,
  deleteCaseToolLink,
  deleteCaseGenre,
  deleteCase,
  deleteCaseAutoAssignRule,
  getCase,
  listCaseAutoAssignRules,
  listCaseFiles,
  listCaseMailLinks,
  listCaseStakeholders,
  listCaseToolLinks,
  listCaseGenres,
  listCases,
  prefillCase,
  reorderCaseGenres,
  regenerateCaseCurrentSituation,
  reorderCaseToolLinks,
  reorderCaseStakeholders,
  reopenCase,
  updateCase,
  updateCaseStakeholder,
  updateCaseGenre,
  unlinkCaseFile,
} from './phase7Api'
import type { CaseAutoAssignRule, CaseCalendarSummary, CaseDetail, CaseGenre, CaseItem, CaseListStatus, CaseMailLink, CaseStakeholder, CaseToolLink } from './phase7Api'
import {
  ActionIconLabel,
  downloadStorageObject,
  StorageDirectoryCard,
  StorageObjectCard,
  storageDirectoryDragType,
  storageObjectDragType,
} from './StorageView'

type CaseMailAssignSort = 'newest' | 'importance'

function describeError(error: unknown) {
  return error instanceof Error ? error.message : t('cases.requestFailed')
}

function formatDateTime(value: string | null) {
  if (value === null) return t('common.none')
  return value.slice(0, 16).replace('T', ' ')
}

function formatMailTime(value: string) {
  return value.slice(11, 16)
}

function caseMailSenderDisplayName(mail: MailListItem) {
  return mail.sender_contact?.display_name ?? mail.from_name ?? mail.from_address
}

function caseMailSenderAvatarUrl(mail: MailListItem) {
  if (mail.sender_contact === null || mail.sender_contact === undefined) {
    return defaultContactAvatarUrl
  }
  return (
    mail.sender_contact.avatar_url ??
    (mail.sender_contact.status === 'spam'
      ? defaultSpamAvatarUrl
      : mail.sender_contact.kind === 'mailing_list'
        ? defaultMailingListAvatarUrl
        : mail.sender_contact.kind === 'service'
          ? defaultServiceAvatarUrl
          : defaultContactAvatarUrl)
  )
}

function caseMailSummary(mail: MailListItem) {
  const summary = mail.summary?.trim()
  if (summary === undefined || summary === '') {
    return ''
  }
  return summary.length > 96 ? `${summary.slice(0, 95)}...` : summary
}

function caseMailPriorityClass(importance: string) {
  if (importance === 'pending') {
    return 'mail-priority-bug'
  }
  return `mail-priority-${importance}`
}

function caseMailGroupLabel(mail: MailListItem, sort: CaseMailAssignSort) {
  if (sort === 'importance') {
    return mail.effective_importance
  }
  return mail.received_date ?? mail.received_at.slice(0, 10)
}

function shouldShowCaseMailGroupLabel(
  mail: MailListItem,
  index: number,
  mailsToRender: MailListItem[],
  sort: CaseMailAssignSort,
) {
  if (index === 0) {
    return true
  }
  return (
    caseMailGroupLabel(mail, sort) !==
    caseMailGroupLabel(mailsToRender[index - 1], sort)
  )
}

function isCaseMailMiddleOrHigherImportance(importance: string) {
  return importance === 'pinned' || importance === 'high' || importance === 'middle'
}

function shouldShowCaseMailImportanceThreshold(
  mail: MailListItem,
  index: number,
  mailsToRender: MailListItem[],
  sort: CaseMailAssignSort,
) {
  if (sort !== 'importance' || index === 0) {
    return false
  }
  return (
    isCaseMailMiddleOrHigherImportance(mailsToRender[index - 1].effective_importance) &&
    !isCaseMailMiddleOrHigherImportance(mail.effective_importance)
  )
}

function caseMailThreadKey(mail: MailListItem) {
  return mail.thread_id ?? mail.gmail_thread_id
}

function latestCaseMailThreadItems(mails: MailListItem[]) {
  const latestByThread = new Map<string, MailListItem>()
  for (const mail of mails) {
    const threadKey = caseMailThreadKey(mail)
    const current = latestByThread.get(threadKey)
    if (
      current === undefined ||
      mail.received_at.localeCompare(current.received_at) > 0 ||
      (mail.received_at === current.received_at && mail.id.localeCompare(current.id) > 0)
    ) {
      latestByThread.set(threadKey, mail)
    }
  }
  return Array.from(latestByThread.values())
}

function compareCaseMailAssignItems(sort: CaseMailAssignSort) {
  return (left: MailListItem, right: MailListItem) => {
    if (sort === 'importance') {
      const rank = (left.importance_rank ?? 99) - (right.importance_rank ?? 99)
      if (rank !== 0) {
        return rank
      }
    }
    return right.received_at.localeCompare(left.received_at) || left.id.localeCompare(right.id)
  }
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

const CASE_TITLE_MAX_LENGTH = 42
const CASE_ROW_VISIBLE_TAG_LIMIT = 4

function genreColor(item: CaseItem, genres: CaseGenre[]) {
  return genres.find((genre) => genre.id === item.genre_id)?.color_hex ?? '#ffffff'
}

function visibleCaseTags(
  tags: string[],
  tagFrequency: Map<string, number>,
  selectedTag: string | null,
) {
  if (tags.length <= CASE_ROW_VISIBLE_TAG_LIMIT) return { visible: tags, hiddenCount: 0 }
  const normalizedSelectedTag = selectedTag?.toLocaleLowerCase() ?? null
  const indexedTags = tags.map((tag, index) => ({ tag, index, key: tag.toLocaleLowerCase() }))
  const selected = normalizedSelectedTag === null
    ? []
    : indexedTags.filter((item) => item.key === normalizedSelectedTag)
  const selectedKeys = new Set(selected.map((item) => item.key))
  const others = indexedTags
    .filter((item) => !selectedKeys.has(item.key))
    .toSorted((first, second) => {
      const frequency = (tagFrequency.get(second.key) ?? 0) - (tagFrequency.get(first.key) ?? 0)
      if (frequency !== 0) return frequency
      return first.index - second.index
    })
  const visible = [...selected, ...others].slice(0, CASE_ROW_VISIBLE_TAG_LIMIT).map((item) => item.tag)
  return { visible, hiddenCount: tags.length - visible.length }
}

function CaseRow({
  genres,
  item,
  selectedTag,
  tagFrequency,
}: {
  genres: CaseGenre[]
  item: CaseItem
  selectedTag: string | null
  tagFrequency: Map<string, number>
}) {
  const tagDisplay = visibleCaseTags(item.tags, tagFrequency, selectedTag)
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
          <>
            {tagDisplay.visible.map((tag) => <span key={tag}>{tag}</span>)}
            {tagDisplay.hiddenCount > 0 && (
              <span className="case-row-tags-more">{t('cases.tags.more', { count: String(tagDisplay.hiddenCount) })}</span>
            )}
          </>
        )}
      </div>
    </AppLink>
  )
}

export function CaseStorageWindow({
  caseId,
  rootDirectoryId,
  rootListMode = 'case',
  rootLabel = t('cases.storage.root'),
  heading = t('storage.objects'),
  body = t('cases.storage.body'),
  deleteMode = 'case',
  collapsible = false,
  defaultCollapsed = false,
}: {
  caseId: string
  rootDirectoryId: string
  rootListMode?: 'case' | 'directory'
  rootLabel?: string
  heading?: string
  body?: string
  deleteMode?: 'case' | 'physical'
  collapsible?: boolean
  defaultCollapsed?: boolean
}) {
  const [currentDirectoryId, setCurrentDirectoryId] = useState(rootDirectoryId)
  const [isCollapsed, setIsCollapsed] = useState(defaultCollapsed)
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
      rootListMode === 'case' && currentDirectoryId === rootDirectoryId
        ? listCaseFiles(caseId)
        : listStorageObjects({ directory_id: currentDirectoryId, limit: 200 }),
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

  async function uploadDroppedItems(dataTransfer: DataTransfer, directoryId: string) {
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

  async function handleMoveStorageObject(objectId: string, directoryId: string) {
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
    if (directoryIdFromDragEvent(event) !== '') {
      return ''
    }
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
    if (event.dataTransfer.files.length > 0) {
      void uploadDroppedItems(event.dataTransfer, currentDirectoryId)
    }
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

  function handleDirectoryDragOver(event: DragEvent<HTMLElement>) {
    event.preventDefault()
    event.stopPropagation()
    event.dataTransfer.dropEffect = 'move'
  }

  function handleDirectoryDrop(event: DragEvent<HTMLElement>, directoryId: string) {
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
    if (deleteMode === 'physical' || object.display_source !== 'link') {
      if (
        !window.confirm(
          t('storage.delete.confirm', { name: object.original_filename ?? object.id }),
        )
      ) {
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
    if (normalizedChoice === '') {
      return
    }
    if (!['exclude', 'delete'].includes(normalizedChoice)) {
      setError(t('cases.storage.deleteChoiceInvalid'))
      return
    }
    setDeleteBusyId(object.id)
    setError(null)
    setNotice(null)
    try {
      if (normalizedChoice === 'exclude') {
        await unlinkCaseFile(caseId, object.id)
      } else {
        if (
          !window.confirm(
            t('storage.delete.confirm', { name: object.original_filename ?? object.id }),
          )
        ) {
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
    <section className={`case-storage-window${isCollapsed ? ' is-collapsed' : ''}`}>
      {collapsible && (
        <div className="case-storage-window-header">
          <div>
            <h2>{heading}</h2>
            <p>{body}</p>
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
          <nav aria-label={t('storage.directory.breadcrumb')} className="storage-breadcrumb case-storage-breadcrumb">
            <button
              onClick={() => setCurrentDirectoryId(rootDirectoryId)}
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
              {!collapsible && (
                <div>
                  <h2>{heading}</h2>
                </div>
              )}
              <p>{body}</p>
            </div>
            <div className="storage-object-grid">
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
        </>
      )}
    </section>
  )
}

function CaseWorkbenchPanel({
  title,
  eyebrow,
  count,
  actionLabel,
  actionHref,
  actions,
  children,
}: {
  title: string
  eyebrow: string
  count: number
  actionLabel?: string
  actionHref?: string
  actions?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="case-workbench-panel">
      <div className="case-workbench-panel-header">
        <span>{eyebrow}</span>
        <div className="case-workbench-panel-actions">
          {actions !== undefined ? (
            actions
          ) : actionHref === undefined ? (
            <button type="button">{actionLabel}</button>
          ) : (
            <AppLink href={actionHref}>{actionLabel}</AppLink>
          )}
        </div>
        <h2>{title}: <small>{count}</small></h2>
      </div>
      {children}
    </section>
  )
}

const defaultStakeholderRoles = ['owner', 'collaborator', 'reviewer', 'stakeholder'] as const

function stakeholderRoleLabel(role: string) {
  if (role === 'owner') return t('cases.stakeholders.role.owner')
  if (role === 'collaborator') return t('cases.stakeholders.role.collaborator')
  if (role === 'reviewer') return t('cases.stakeholders.role.reviewer')
  if (role === 'stakeholder') return t('cases.stakeholders.role.stakeholder')
  return role
}

function StakeholderRoleSuggestInput({
  role,
  options,
  disabled,
  onCommit,
  ariaLabel,
}: {
  role: string
  options: string[]
  disabled: boolean
  onCommit: (role: string) => void
  ariaLabel: string
}) {
  const [draft, setDraft] = useState(role)

  useEffect(() => {
    setDraft(role)
  }, [role])

  function handleChange(nextRole: string) {
    setDraft(nextRole)
    const trimmedNextRole = nextRole.trim()
    const trimmedCurrentRole = role.trim()
    if (trimmedNextRole === trimmedCurrentRole) return
    if (trimmedNextRole === '' || options.includes(trimmedNextRole)) {
      onCommit(nextRole)
    }
  }

  return (
    <SuggestInput
      ariaLabel={ariaLabel}
      className={role.trim() === '' ? undefined : 'case-stakeholder-role-suggest'}
      disabled={disabled}
      maxItems={1}
      onChange={handleChange}
      options={options.map((roleValue) => ({
        key: roleValue,
        value: roleValue,
        label: stakeholderRoleLabel(roleValue),
        badgeLabel: stakeholderRoleLabel(roleValue),
      }))}
      value={draft}
    />
  )
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
  const [caseContexts, setCaseContexts] = useState<ContactSelectorCaseContext[]>([])
  const [isSettingsOpen, setIsSettingsOpen] = useState(false)
  const [contactQuery, setContactQuery] = useState('')
  const [role, setRole] = useState('')
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

  useEffect(() => {
    let isMounted = true
    async function loadCaseContexts() {
      const caseLists = await Promise.all([
        listCases('user_ball'),
        listCases('waiting'),
        listCases('completed'),
      ])
      const caseItems = caseLists.flat()
      const contexts = await Promise.all(
        caseItems.map(async (caseItem) => ({
          case: caseItem,
          stakeholders: await listCaseStakeholders(caseItem.id),
        })),
      )
      if (isMounted) {
        setCaseContexts(contexts)
      }
    }
    void loadCaseContexts().catch(() => {
      if (isMounted) setCaseContexts([])
    })
    return () => {
      isMounted = false
    }
  }, [])

  const selectedContact = contacts.find((contact) => {
    const query = contactQuery.trim().toLowerCase()
    return (
      contact.display_name.toLowerCase() === query ||
      contact.email_addresses.some((email) => email.email_address.toLowerCase() === query)
    )
  })
  const linkedContactIds = new Set(stakeholders.map((stakeholder) => stakeholder.contact_id))
  const selectedContacts = resolveContactSelectorListWithCases(
    contactQuery,
    contacts,
    caseContexts,
  ).filter((contact) => !linkedContactIds.has(contact.id))
  const caseSelectorSuggestions = caseRoleSelectorSuggestions(contactQuery, caseContexts)
  const stakeholderContactOptions: SuggestInputOption[] = [
    ...contacts.map((contact) => {
      const primaryEmail =
        contact.email_addresses.find((email) => email.is_primary)?.email_address ?? t('common.none')
      return {
        key: contact.id,
        value: contact.display_name,
        label: primaryEmail,
        badgeLabel: contact.display_name,
      }
    }),
    ...caseSelectorSuggestions.map((suggestion) => ({
      key: suggestion.value,
      value: suggestion.value,
      label: suggestion.label,
      badgeLabel: suggestion.label,
    })),
  ]
  const stakeholderRoleSuggestions = Array.from(
    new Set([
      ...defaultStakeholderRoles,
      ...stakeholders.map((stakeholder) => stakeholder.role),
      ...caseContexts.flatMap((context) =>
        context.stakeholders.map((stakeholder) => stakeholder.role),
      ),
    ]),
  )
    .filter((roleValue) => roleValue.trim() !== '')
    .sort((left, right) => left.localeCompare(right))
  const canAddStakeholder =
    selectedContacts.length > 0 ||
    (selectedContact !== undefined && !linkedContactIds.has(selectedContact.id))

  async function addStakeholder(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!canAddStakeholder) return
    setBusy(true)
    setError(null)
    try {
      const contactsToAdd =
        selectedContacts.length > 0
          ? selectedContacts
          : selectedContact === undefined
            ? []
            : [selectedContact]
      const createdStakeholders = await Promise.all(
        contactsToAdd.map((contact) =>
          createCaseStakeholder(caseId, {
            contact_id: contact.id,
            role,
          }),
        ),
      )
      setStakeholders((current) => [...current, ...createdStakeholders])
      setContactQuery('')
      setRole('')
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setBusy(false)
    }
  }

  async function changeRole(stakeholder: CaseStakeholder, nextRole: string) {
    const trimmedRole = nextRole.trim()
    if (trimmedRole === stakeholder.role) return
    setBusy(true)
    setError(null)
    try {
      const updatedStakeholder = await updateCaseStakeholder(caseId, stakeholder.id, {
        role: trimmedRole,
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
              <span className="case-stakeholder-avatar">
                <img
                  alt=""
                  aria-hidden="true"
                  src={stakeholder.contact_avatar_url ?? defaultContactAvatarUrl}
                />
              </span>
              <strong>{stakeholder.contact_display_name}</strong>
              {isSettingsOpen ? (
                <>
                  <StakeholderRoleSuggestInput
                    ariaLabel={t('cases.stakeholders.role')}
                    disabled={busy}
                    options={stakeholderRoleSuggestions}
                    role={stakeholder.role}
                    onCommit={(nextRole) => void changeRole(stakeholder, nextRole)}
                  />
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
              ) : stakeholder.role.trim() !== '' ? (
                <em>{stakeholderRoleLabel(stakeholder.role)}</em>
              ) : (
                <i aria-hidden="true" className="case-stakeholder-empty-role" />
              )}
            </div>
          ))
        )}
      </div>
      {isSettingsOpen && (
        <form className="case-stakeholder-form" onSubmit={addStakeholder}>
          <label>
            <span>{t('cases.stakeholders.contact')}</span>
            <SuggestInput
              ariaLabel={t('cases.stakeholders.contact')}
              onChange={setContactQuery}
              options={stakeholderContactOptions}
              value={contactQuery}
            />
          </label>
          <label>
            <span>{t('cases.stakeholders.role')}</span>
            <SuggestInput
              ariaLabel={t('cases.stakeholders.role')}
              maxItems={1}
              onChange={setRole}
              options={stakeholderRoleSuggestions.map((roleValue) => ({
                key: roleValue,
                value: roleValue,
                label: stakeholderRoleLabel(roleValue),
                badgeLabel: stakeholderRoleLabel(roleValue),
              }))}
              value={role}
            />
          </label>
          <button disabled={busy || !canAddStakeholder} type="submit">
            {t('cases.stakeholders.add')}
          </button>
        </form>
      )}
    </section>
  )
}

function CaseCalendarGadget({
  caseItem,
  calendarEvents,
}: {
  caseItem: CaseItem
  calendarEvents: CaseCalendarSummary[]
}) {
  const today = jstDateToday()
  const latestCalendarEventDate = calendarEvents
    .map((event) => event.starts_at?.slice(0, 10) ?? '')
    .filter((date) => date !== '')
    .toSorted((first, second) => second.localeCompare(first))[0]
  const initialMonth =
    caseItem.next_calendar_event?.starts_at?.slice(0, 10) ?? latestCalendarEventDate ?? today
  const [calendarMonth, setCalendarMonth] = useState(initialMonth)
  const selectedMonthDays = calendarDays(calendarMonth)
  const eventsByDate = useMemo(() => {
    const grouped = new Map<string, CaseCalendarSummary[]>()
    calendarEvents.forEach((event) => {
      const startsAt = event.starts_at ?? ''
      const date = startsAt.slice(0, 10)
      if (date === '') return
      const events = grouped.get(date) ?? []
      events.push(event)
      grouped.set(date, events)
    })
    grouped.forEach((events) => {
      events.sort((first, second) => {
        const firstTime = first.starts_at ?? ''
        const secondTime = second.starts_at ?? ''
        if (firstTime !== secondTime) return firstTime.localeCompare(secondTime)
        return first.title.localeCompare(second.title)
      })
    })
    return grouped
  }, [calendarEvents])

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
          const dayEvents = eventsByDate.get(date) ?? []
          const hasEvent = dayEvents.length > 0
          return (
            <button
              aria-label={hasEvent ? t('cases.calendar.openDate', { date }) : date}
              className={`${hasEvent ? 'mail-calendar-day case-calendar-day-has-event' : 'mail-calendar-day mail-calendar-day-empty'}${
                date === today ? ' is-today' : ''
              }`}
              disabled={!hasEvent}
              key={date}
              type="button"
            >
              {Number(date.slice(8, 10))}
              {hasEvent && (
                <span className="case-calendar-day-popover" role="tooltip">
                  {dayEvents.slice(0, 4).map((event) => (
                    <span key={event.id}>
                      <strong>{event.title}</strong>
                      <small>{formatDateTime(event.starts_at)}</small>
                    </span>
                  ))}
                  {dayEvents.length > 4 && (
                    <span>
                      <strong>{`+${dayEvents.length - 4}`}</strong>
                    </span>
                  )}
                </span>
              )}
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
                {tool.icon_url !== null && tool.icon_url !== '' ? (
                  <img alt="" aria-hidden="true" src={tool.icon_url} />
                ) : (
                  <span>{tool.icon_label}</span>
                )}
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
  const [sortMode, setSortMode] = useState('genre_name')
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
      listCases('all'),
    ])
      .then(([nextGenres, nextAllCases]) => {
        if (!isMounted) return
        setGenres(nextGenres)
        setAllCases(nextAllCases)
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
  const caseTagFrequency = allCases.reduce<Map<string, number>>((counts, item) => {
    item.tags.forEach((tag) => {
      const key = tag.toLocaleLowerCase()
      counts.set(key, (counts.get(key) ?? 0) + 1)
    })
    return counts
  }, new Map<string, number>())
  const genreOrder = new Map(genres.map((genre, index) => [genre.id, index]))
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
      if (sortMode === 'genre_name') {
        const firstGenreOrder = first.genre_id !== null ? (genreOrder.get(first.genre_id) ?? 9998) : 9999
        const secondGenreOrder = second.genre_id !== null ? (genreOrder.get(second.genre_id) ?? 9998) : 9999
        if (firstGenreOrder !== secondGenreOrder) return firstGenreOrder - secondGenreOrder
        const nameComparison = first.name.localeCompare(second.name)
        if (nameComparison !== 0) return nameComparison
        return first.created_at.localeCompare(second.created_at)
      }
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
                <option value="genre_name">{t('cases.sort.genreName')}</option>
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
              <div className="case-tab-group case-tab-group-primary">
                {(['user_ball', 'waiting'] as CaseListStatus[]).map((tab) => (
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
              <div className="case-tab-group case-tab-group-secondary">
                {(['not_started', 'completed', 'archived'] as CaseListStatus[]).map((tab) => (
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
                visibleCases.map((item) => (
                  <CaseRow
                    genres={genres}
                    item={item}
                    key={item.id}
                    selectedTag={selectedTag}
                    tagFrequency={caseTagFrequency}
                  />
                ))
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

  async function handleMove(genreId: string, direction: -1 | 1) {
    const currentIndex = genres.findIndex((genre) => genre.id === genreId)
    const nextIndex = currentIndex + direction
    if (currentIndex < 0 || nextIndex < 0 || nextIndex >= genres.length) return
    const nextGenreIds = genres.map((genre) => genre.id)
    ;[nextGenreIds[currentIndex], nextGenreIds[nextIndex]] = [
      nextGenreIds[nextIndex],
      nextGenreIds[currentIndex],
    ]
    setIsSubmitting(true)
    try {
      await reorderCaseGenres(nextGenreIds)
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
                <i
                  aria-hidden="true"
                  className="case-genre-color-swatch"
                  style={{ background: color }}
                />
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
          genres.map((genre, index) => (
            <div className="case-genre-item" key={genre.id}>
                  <span>
                    <i style={{ background: genre.color_hex }} />
                    {genre.title}
                  </span>
                  <div className="case-genre-item-actions">
                    <button
                      disabled={isSubmitting || index === 0}
                      onClick={() => handleMove(genre.id, -1)}
                      type="button"
                    >
                      {t('cases.genre.moveUp')}
                    </button>
                    <button
                      disabled={isSubmitting || index === genres.length - 1}
                      onClick={() => handleMove(genre.id, 1)}
                      type="button"
                    >
                      {t('cases.genre.moveDown')}
                    </button>
                    <button onClick={() => startEdit(genre)} type="button">
                      {t('cases.genre.edit')}
                    </button>
                    <button onClick={() => handleDelete(genre.id)} type="button">
                      {t('cases.genre.delete')}
                    </button>
                  </div>
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
  const [nameDraft, setNameDraft] = useState('')
  const [overviewDraft, setOverviewDraft] = useState('')
  const [openWhenDraft, setOpenWhenDraft] = useState('')
  const [closedWhenDraft, setClosedWhenDraft] = useState('')
  const [tagDraft, setTagDraft] = useState('')
  const [genreDraft, setGenreDraft] = useState('')
  const [genres, setGenres] = useState<CaseGenre[]>([])
  const [isOverviewSaving, setIsOverviewSaving] = useState(false)
  const [isCaseStateBusy, setIsCaseStateBusy] = useState(false)
  const [isCurrentSituationRefreshing, setIsCurrentSituationRefreshing] = useState(false)
  const [isCurrentSituationExpanded, setIsCurrentSituationExpanded] = useState(false)
  const [isDeletingCase, setIsDeletingCase] = useState(false)
  const [deleteMenuPosition, setDeleteMenuPosition] = useState<{
    x: number
    y: number
  } | null>(null)
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

  useEffect(() => {
    let isMounted = true
    listCaseGenres()
      .then((items) => {
        if (isMounted) setGenres(items)
      })
      .catch(() => {
        if (isMounted) setGenres([])
      })
    return () => {
      isMounted = false
    }
  }, [])

  useEffect(() => {
    if (deleteMenuPosition === null) {
      return
    }
    function closeDeleteMenu() {
      setDeleteMenuPosition(null)
    }
    window.addEventListener('click', closeDeleteMenu)
    window.addEventListener('keydown', closeDeleteMenu)
    window.addEventListener('scroll', closeDeleteMenu, true)
    return () => {
      window.removeEventListener('click', closeDeleteMenu)
      window.removeEventListener('keydown', closeDeleteMenu)
      window.removeEventListener('scroll', closeDeleteMenu, true)
    }
  }, [deleteMenuPosition])

  const item = detail?.case ?? null

  function startOverviewEdit() {
    if (item === null) return
    setNameDraft(item.name)
    setOverviewDraft(item.description ?? '')
    setOpenWhenDraft(item.open_when_date ?? '')
    setClosedWhenDraft(item.closed_when_text ?? '')
    setTagDraft(item.tags.join(', '))
    setGenreDraft(item.genre_id ?? '')
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
        ...(item.is_system_case ? {} : { name: nameDraft.trim() }),
        description: overviewDraft.trim() === '' ? null : overviewDraft,
        open_when_date: openWhenDraft.trim() === '' ? null : openWhenDraft,
        open_when_text: null,
        closed_when_text: closedWhenDraft.trim() === '' ? null : closedWhenDraft,
        genre_id: genreDraft === '' ? null : genreDraft,
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

  function openDeleteMenu(event: MouseEvent<HTMLButtonElement>) {
    event.preventDefault()
    if (item?.is_system_case) {
      return
    }
    setDeleteMenuPosition({ x: event.clientX, y: event.clientY })
  }

  async function handleDeleteCase() {
    if (item === null || isDeletingCase) return
    setDeleteMenuPosition(null)
    if (!window.confirm(t('cases.delete.confirm', { name: item.name }))) {
      return
    }
    setIsDeletingCase(true)
    setError(null)
    try {
      await deleteCase(item.id)
      navigateTo('/cases')
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsDeletingCase(false)
    }
  }

  async function updateCaseState(action: 'complete' | 'reopen' | 'archive') {
    if (item === null || isCaseStateBusy) return
    setIsCaseStateBusy(true)
    setError(null)
    try {
      const updatedCase =
        action === 'complete'
          ? await completeCase(item.id)
          : action === 'reopen'
            ? await reopenCase(item.id)
            : await archiveCase(item.id)
      setDetail((currentDetail) =>
        currentDetail === null ? currentDetail : { ...currentDetail, case: updatedCase },
      )
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsCaseStateBusy(false)
    }
  }

  async function handleCurrentSituationRefresh() {
    if (item === null || isCurrentSituationRefreshing) return
    setIsCurrentSituationRefreshing(true)
    setError(null)
    try {
      const currentSituation = await regenerateCaseCurrentSituation(item.id)
      setDetail((currentDetail) =>
        currentDetail === null
          ? currentDetail
          : { ...currentDetail, current_situation: currentSituation },
      )
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsCurrentSituationRefreshing(false)
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
                      {!item.is_system_case && (
                        <label>
                          <span>{t('cases.name')}</span>
                          <input
                            aria-label={t('cases.name')}
                            onChange={(event) => setNameDraft(event.target.value)}
                            required
                            value={nameDraft}
                          />
                        </label>
                      )}
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
                      <label className="case-overview-tags-field">
                        <span>{t('cases.genre.select')}</span>
                        <select
                          aria-label={t('cases.genre.select')}
                          onChange={(event) => setGenreDraft(event.target.value)}
                          value={genreDraft}
                        >
                          <option value="">{t('cases.genre.none')}</option>
                          {genres.map((genre) => (
                            <option key={genre.id} value={genre.id}>
                              {genre.title}
                            </option>
                          ))}
                        </select>
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
                        <input
                          aria-label={t('cases.overview.openWhen')}
                          onChange={(event) => setOpenWhenDraft(event.target.value)}
                          type="date"
                          value={openWhenDraft}
                        />
                      ) : (
                        item.open_when_date ?? t('cases.overview.openWhenEmpty')
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
                  <div className="case-ai-status-actions">
                    <button
                      aria-expanded={isCurrentSituationExpanded}
                      onClick={() => setIsCurrentSituationExpanded((current) => !current)}
                      type="button"
                    >
                      {isCurrentSituationExpanded
                        ? t('common.collapse')
                        : t('common.expand')}
                    </button>
                    <button
                      className={`button-loading-dot${
                        isCurrentSituationRefreshing ? ' is-loading' : ''
                      }`}
                      disabled={isCurrentSituationRefreshing}
                      onClick={handleCurrentSituationRefresh}
                      type="button"
                    >
                      {isCurrentSituationRefreshing
                        ? t('cases.aiStatus.refreshing')
                        : t('cases.aiStatus.refresh')}
                    </button>
                  </div>
                </div>
                {isCurrentSituationExpanded && (
                  <>
                    {detail.current_situation === null || detail.current_situation === undefined ? (
                      <p>{t('cases.aiStatus.empty')}</p>
                    ) : (
                      <>
                        <pre className="case-ai-status-text">
                          {detail.current_situation.context_markdown}
                        </pre>
                        <p className="case-ai-status-meta">
                          {t('cases.aiStatus.version', {
                            version: detail.current_situation.version_no,
                            time: formatDateTime(detail.current_situation.created_at),
                          })}
                        </p>
                      </>
                    )}
                    <div className="case-ai-status-grid">
                      <span>{t('cases.aiStatus.source.mail')}</span>
                      <span>{t('cases.aiStatus.source.task')}</span>
                      <span>{t('cases.aiStatus.source.calendar')}</span>
                      <span>{t('cases.aiStatus.source.file')}</span>
                    </div>
                  </>
                )}
              </section>
              <div className="case-workbench-grid">
                <CaseWorkbenchPanel
                  actions={
                    <>
                      <AppLink href={`/cases/${encodeURIComponent(item.id)}/mails`}>
                        {t('cases.mail.viewAll')}
                      </AppLink>
                      <AppLink href={`/cases/${encodeURIComponent(item.id)}/mails?assign=1`}>
                        {t('cases.mail.assign')}
                      </AppLink>
                    </>
                  }
                  count={item.mail_count}
                  eyebrow={t('cases.section.mail')}
                  title={t('cases.mail.window')}
                >
                  <div className="case-mail-preview-list">
                    {detail.related_mails.length === 0 ? (
                      <div>
                        <time>--:--</time>
                        <span>{t('cases.mail.empty')}</span>
                        <b>{t('cases.card.none')}</b>
                      </div>
                    ) : (
                      detail.related_mails.slice(0, 2).map((mail) => (
                        <AppLink className="case-mail-preview-row" href={mail.mail_url} key={mail.id}>
                          <time>{formatDateTime(mail.received_at)}</time>
                          <span>{mail.subject ?? t('mail.noSubject')}</span>
                          <b>{mail.effective_importance}</b>
                        </AppLink>
                      ))
                    )}
                  </div>
                </CaseWorkbenchPanel>
                <CaseWorkbenchPanel
                  actionLabel={t('cases.task.new')}
                  actionHref={`/tasks/new?case_id=${encodeURIComponent(item.id)}`}
                  count={item.open_task_count}
                  eyebrow={t('cases.section.tasks')}
                  title={t('cases.task.window')}
                >
                  <AppLink
                    className="case-task-lane case-task-lane-link"
                    href={`/tasks?case_id=${encodeURIComponent(item.id)}`}
                  >
                    <div>
                      <span>{t('cases.task.next')}</span>
                      <strong>{item.next_task?.title ?? t('cases.card.none')}</strong>
                      <small>{formatDateTime(item.next_task?.due_at ?? null)}</small>
                    </div>
                    <div>
                      <span>{t('cases.task.overdue')}</span>
                      <strong>{item.overdue_task_count}</strong>
                    </div>
                  </AppLink>
                </CaseWorkbenchPanel>
              </div>
              <CaseStorageWindow
                caseId={item.id}
                collapsible
                defaultCollapsed
                heading={t('cases.storage.heading')}
                rootDirectoryId={item.storage_directory_id}
              />
              <CaseStakeholdersPanel
                caseId={item.id}
                initialStakeholders={detail.stakeholders ?? []}
              />
            </div>
            <aside aria-label={t('cases.gadgets')} className="case-gadget-column">
              <CaseCalendarGadget caseItem={item} calendarEvents={detail.calendar_events} />
              <CaseToolsGadget caseId={item.id} initialTools={detail.tool_links ?? []} />
              {!item.is_system_case && (
                <>
                  {item.closed_at === null && item.archived_at === null ? (
                    <button
                      className={`case-complete-gadget-button button-loading-dot${
                        isCaseStateBusy || isDeletingCase ? ' is-loading' : ''
                      }`}
                      disabled={isCaseStateBusy || isDeletingCase}
                      onClick={() => {
                        void updateCaseState('complete')
                      }}
                      onContextMenu={openDeleteMenu}
                      type="button"
                    >
                      {t('cases.complete.button')}
                    </button>
                  ) : (
                    <button
                      className={`case-complete-gadget-button button-loading-dot${
                        isCaseStateBusy || isDeletingCase ? ' is-loading' : ''
                      }`}
                      disabled={isCaseStateBusy || isDeletingCase}
                      onClick={() => {
                        void updateCaseState('reopen')
                      }}
                      onContextMenu={openDeleteMenu}
                      type="button"
                    >
                      {t('cases.reopen.button')}
                    </button>
                  )}
                  {item.archived_at === null && (
                    <button
                      className={`case-secondary-gadget-button button-loading-dot${
                        isCaseStateBusy ? ' is-loading' : ''
                      }`}
                      disabled={isCaseStateBusy || isDeletingCase}
                      onClick={() => {
                        void updateCaseState('archive')
                      }}
                      type="button"
                    >
                      {t('cases.archive.button')}
                    </button>
                  )}
                </>
              )}
              {deleteMenuPosition !== null && (
                <div
                  className="case-complete-context-menu"
                  role="menu"
                  style={{
                    left: deleteMenuPosition.x,
                    top: deleteMenuPosition.y,
                  }}
                >
                  <button
                    disabled={isDeletingCase}
                    onClick={() => {
                      void handleDeleteCase()
                    }}
                    role="menuitem"
                    type="button"
                  >
                    {t('cases.delete.button')}
                  </button>
                </div>
              )}
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
  const [openWhenText, setOpenWhenText] = useState('')
  const [closedWhenText, setClosedWhenText] = useState('')
  const [tagText, setTagText] = useState('')
  const [genres, setGenres] = useState<CaseGenre[]>([])
  const [genreId, setGenreId] = useState('')
  const [llmPrompt, setLlmPrompt] = useState('')
  const [llmNotice, setLlmNotice] = useState<string | null>(null)
  const [isPrefilling, setIsPrefilling] = useState(false)
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

  function parseCaseTagInput(value: string) {
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

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setIsSubmitting(true)
    setError(null)
    try {
      const created = await createCase({
        name,
        description: description.trim() === '' ? null : description,
        open_when_date: openWhenText.trim() === '' ? null : openWhenText,
        open_when_text: null,
        closed_when_text: closedWhenText.trim() === '' ? null : closedWhenText,
        progress_status: 'not_started',
        genre_id: genreId === '' ? null : genreId,
        tags: parseCaseTagInput(tagText),
      })
      navigateTo(`/cases/${encodeURIComponent(created.id)}`)
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsSubmitting(false)
    }
  }

  async function handleLlmPrefill() {
    const prompt = llmPrompt.trim()
    if (prompt === '' || isPrefilling) return
    setIsPrefilling(true)
    setError(null)
    setLlmNotice(null)
    try {
      const { prefill } = await prefillCase({
        prompt,
        current_fields: {
          name,
          description,
          open_when_date: openWhenText,
          closed_when_text: closedWhenText,
          tags: parseCaseTagInput(tagText),
          genre_id: genreId,
        },
      })
      if (name.trim() === '' && prefill.name !== null) {
        setName(prefill.name.slice(0, CASE_TITLE_MAX_LENGTH))
      }
      if (description.trim() === '' && prefill.description !== null) {
        setDescription(prefill.description)
      }
      if (openWhenText.trim() === '' && prefill.open_when_date !== null) {
        setOpenWhenText(prefill.open_when_date)
      }
      if (closedWhenText.trim() === '' && prefill.closed_when_text !== null) {
        setClosedWhenText(prefill.closed_when_text)
      }
      if (tagText.trim() === '' && prefill.tags.length > 0) {
        setTagText(prefill.tags.join(', '))
      }
      setLlmNotice(t('cases.create.llmApplied'))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsPrefilling(false)
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

        <form className="case-create-layout" onSubmit={handleSubmit}>
          <section className="case-create-main">
            <section className="case-overview-panel case-create-overview-panel">
              <div className="case-overview-main">
                <div>
                  <div className="case-overview-title-row">
                    <h2>{t('cases.section.overview')}</h2>
                  </div>
                </div>
                <label>
                  <span>{t('cases.name')}</span>
                  <input
                    autoFocus
                    maxLength={CASE_TITLE_MAX_LENGTH}
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
                <label className="case-overview-tags-field">
                  <span>{t('cases.tags')}</span>
                  <input
                    onChange={(event) => setTagText(event.target.value)}
                    placeholder={t('cases.tags.placeholder')}
                    value={tagText}
                  />
                </label>
              </div>
              <dl>
                <div>
                  <dt>{t('cases.overview.openWhen')}</dt>
                  <dd>
                    <input
                      onChange={(event) => setOpenWhenText(event.target.value)}
                      type="date"
                      value={openWhenText}
                    />
                  </dd>
                </div>
                <div>
                  <dt>{t('cases.overview.closedWhen')}</dt>
                  <dd>
                    <textarea
                      onChange={(event) => setClosedWhenText(event.target.value)}
                      rows={3}
                      value={closedWhenText}
                    />
                  </dd>
                </div>
              </dl>
            </section>
            <section className="case-panel case-create-placeholder-panel">
              <h2>{t('cases.aiStatus.heading')}</h2>
              <p>{t('cases.aiStatus.empty')}</p>
            </section>
          </section>

          <aside aria-label={t('cases.gadgets')} className="case-gadget-column">
            <section className="case-gadget-card">
              <h2>{t('cases.create.metaHeading')}</h2>
              <label className="case-create-gadget-field">
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
            </section>
            <section className="case-gadget-card">
              <h2>{t('cases.create.llmHeading')}</h2>
              <label className="case-create-gadget-field">
                <span>{t('cases.create.llmPrompt')}</span>
                <textarea
                  onChange={(event) => {
                    setLlmPrompt(event.target.value)
                    setLlmNotice(null)
                  }}
                  placeholder={t('cases.create.llmPlaceholder')}
                  rows={5}
                  value={llmPrompt}
                />
              </label>
              {llmNotice !== null && <p className="task-gadget-empty">{llmNotice}</p>}
              <button
                className={`case-gadget-action button-loading-dot${isPrefilling ? ' is-loading' : ''}`}
                disabled={isPrefilling || llmPrompt.trim() === ''}
                onClick={() => {
                  void handleLlmPrefill()
                }}
                type="button"
              >
                {isPrefilling ? t('cases.create.llmGenerating') : t('cases.create.llmGenerate')}
              </button>
            </section>
            <section className="case-gadget-card">
              <h2>{t('cases.detail.actions')}</h2>
              <button
                className={`case-gadget-action button-loading-dot${isSubmitting ? ' is-loading' : ''}`}
                disabled={isSubmitting}
                type="submit"
              >
                {t('cases.create')}
              </button>
              <AppLink className="case-gadget-secondary-action" href="/cases">
                {t('common.cancel')}
              </AppLink>
            </section>
          </aside>
        </form>
      </div>
    </main>
  )
}

function CaseMailListView({ caseId }: { caseId: string }) {
  const [caseItem, setCaseItem] = useState<CaseItem | null>(null)
  const [mailLinks, setMailLinks] = useState<CaseMailLink[]>([])
  const [autoAssignRules, setAutoAssignRules] = useState<CaseAutoAssignRule[]>([])
  const [stakeholders, setStakeholders] = useState<CaseStakeholder[]>([])
  const [mailSearchResults, setMailSearchResults] = useState<MailListItem[]>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [autoRuleSenderEmail, setAutoRuleSenderEmail] = useState('')
  const [assignSearchQuery, setAssignSearchQuery] = useState('')
  const [specialGmailSource, setSpecialGmailSource] = useState('')
  const [assignSort, setAssignSort] = useState<CaseMailAssignSort>('importance')
  const [assignPageSize, setAssignPageSize] = useState(25)
  const [assignSearchRefreshTick, setAssignSearchRefreshTick] = useState(0)
  const [pinnedMails, setPinnedMails] = useState<Record<string, MailListItem>>({})
  const [isAssignMode, setIsAssignMode] = useState(
    () => new URLSearchParams(window.location.search).get('assign') === '1',
  )
  const [isRemoveMode, setIsRemoveMode] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [isSearchingMails, setIsSearchingMails] = useState(false)
  const [isAssigning, setIsAssigning] = useState(false)
  const [isSpecialGmailLoading, setIsSpecialGmailLoading] = useState(false)
  const [isAutoRuleSaving, setIsAutoRuleSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    let isMounted = true
    setIsLoading(true)
    setError(null)
    Promise.all([
      getCase(caseId),
      listCaseMailLinks(caseId),
      listCaseAutoAssignRules(caseId),
      listCaseStakeholders(caseId),
    ])
      .then(([detail, links, rules, nextStakeholders]) => {
        if (!isMounted) return
        setCaseItem(detail.case)
        setMailLinks(links)
        setAutoAssignRules(rules)
        setStakeholders(nextStakeholders)
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

  useEffect(() => {
    if (!isAssignMode) {
      setMailSearchResults([])
      setIsSearchingMails(false)
      return
    }
    const query = assignSearchQuery.trim()
    if (query === '') {
      setMailSearchResults([])
      setIsSearchingMails(false)
      return
    }

    let isMounted = true
    setIsSearchingMails(true)
    const timeoutId = window.setTimeout(() => {
      listMailPage({
        tab: 'all',
        processed: 'all',
        contact_status: 'all',
        read: 'all',
        q: query,
        limit: assignPageSize,
      })
        .then((page) => {
          if (isMounted) {
            setMailSearchResults(page.items)
          }
        })
        .catch((requestError) => {
          if (isMounted) {
            setError(describeError(requestError))
          }
        })
        .finally(() => {
          if (isMounted) {
            setIsSearchingMails(false)
          }
        })
    }, 220)
    return () => {
      isMounted = false
      window.clearTimeout(timeoutId)
    }
  }, [assignPageSize, assignSearchQuery, assignSearchRefreshTick, isAssignMode])

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
  const autoRuleStakeholderSuggestions = stakeholders
    .filter((stakeholder) => stakeholder.contact_primary_email !== null)
    .reduce<Array<{ email: string; label: string }>>((suggestions, stakeholder) => {
      const email = stakeholder.contact_primary_email
      if (email === null) return suggestions
      if (suggestions.some((suggestion) => suggestion.email.toLowerCase() === email.toLowerCase())) {
        return suggestions
      }
      suggestions.push({
        email,
        label: `${stakeholder.contact_display_name} / ${stakeholder.role}`,
      })
      return suggestions
    }, [])
  const assignedThreadIds = new Set(mailLinks.map((mail) => mail.thread_id))
  const pinnedMailItems = latestCaseMailThreadItems(Object.values(pinnedMails)).toSorted(
    (first, second) => second.received_at.localeCompare(first.received_at),
  )
  const pinnedThreadIds = new Set(pinnedMailItems.map(caseMailThreadKey))
  const normalizedAssignQuery = assignSearchQuery.trim().toLowerCase()
  const visibleMailSearchResults = latestCaseMailThreadItems(mailSearchResults)
    .filter((mail) => {
      const threadId = caseMailThreadKey(mail)
      if (assignedThreadIds.has(threadId) || pinnedThreadIds.has(threadId)) {
        return false
      }
      return normalizedAssignQuery !== ''
    })
    .toSorted(compareCaseMailAssignItems(assignSort))

  function pinMail(mail: MailListItem) {
    setPinnedMails((currentPinnedMails) => ({
      ...currentPinnedMails,
      [caseMailThreadKey(mail)]: mail,
    }))
  }

  function pinVisibleMailSearchResults() {
    if (visibleMailSearchResults.length === 0) {
      return
    }
    setPinnedMails((currentPinnedMails) => {
      const nextPinnedMails = { ...currentPinnedMails }
      for (const mail of visibleMailSearchResults) {
        nextPinnedMails[caseMailThreadKey(mail)] = mail
      }
      return nextPinnedMails
    })
  }

  function unpinMail(mail: MailListItem) {
    setPinnedMails((currentPinnedMails) => {
      const nextPinnedMails = { ...currentPinnedMails }
      delete nextPinnedMails[caseMailThreadKey(mail)]
      return nextPinnedMails
    })
  }

  async function handleRegisterPinnedMails() {
    if (pinnedMailItems.length === 0) {
      return
    }
    setError(null)
    setNotice(null)
    setIsAssigning(true)
    try {
      await Promise.all(
        pinnedMailItems.map((mail) => assignMailThreadToCase(mail.id, caseId)),
      )
      const links = await listCaseMailLinks(caseId)
      setMailLinks(links)
      setPinnedMails({})
      setAssignSearchQuery('')
      setIsAssignMode(false)
      setNotice(t('cases.mail.assignRegistered', { count: pinnedMailItems.length }))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsAssigning(false)
    }
  }

  async function handleUnassignMailThread(mail: CaseMailLink) {
    setError(null)
    setNotice(null)
    setIsAssigning(true)
    try {
      await unassignMailThreadFromCase(mail.message_id, caseId)
      const links = await listCaseMailLinks(caseId)
      setMailLinks(links)
      if (links.length === 0) {
        setIsRemoveMode(false)
      }
      setNotice(t('cases.mail.unassigned', { subject: mail.subject ?? t('mail.noSubject') }))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsAssigning(false)
    }
  }

  async function handleCreateAutoAssignRule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const senderEmail = autoRuleSenderEmail.trim()
    if (senderEmail === '' || isAutoRuleSaving) {
      return
    }
    setError(null)
    setNotice(null)
    setIsAutoRuleSaving(true)
    try {
      const rule = await createCaseAutoAssignRule(caseId, {
        sender_email: senderEmail,
      })
      setAutoAssignRules((currentRules) => [rule, ...currentRules])
      setAutoRuleSenderEmail('')
      setNotice(t('cases.mail.autoRule.created', { email: rule.rule_value }))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsAutoRuleSaving(false)
    }
  }

  async function handleDeleteAutoAssignRule(rule: CaseAutoAssignRule) {
    if (isAutoRuleSaving) {
      return
    }
    setError(null)
    setNotice(null)
    setIsAutoRuleSaving(true)
    try {
      await deleteCaseAutoAssignRule(caseId, rule.id)
      setAutoAssignRules((currentRules) =>
        currentRules.filter((currentRule) => currentRule.id !== rule.id),
      )
      setNotice(t('cases.mail.autoRule.deleted', { email: rule.rule_value }))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsAutoRuleSaving(false)
    }
  }

  async function handleSpecialGmailImport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const source = specialGmailSource.trim()
    if (source === '' || isSpecialGmailLoading) {
      return
    }
    setError(null)
    setNotice(null)
    setIsSpecialGmailLoading(true)
    try {
      const result = await importSpecialGoogleGmailThread(source)
      const firstItem = result.items[0] ?? null
      if (firstItem?.subject !== null && firstItem?.subject !== undefined) {
        setAssignSearchQuery(firstItem.subject)
      } else {
        setAssignSearchQuery(result.source_id)
      }
      setAssignSearchRefreshTick((tick) => tick + 1)
      setSpecialGmailSource('')
      setNotice(t('cases.mail.specialImport.done', { count: result.imported_count }))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setIsSpecialGmailLoading(false)
    }
  }

  function renderMailRow(mail: MailListItem, options: {
    actionLabel: string
    onClick: () => void
  }) {
    return (
      <button
        className={`mail-list-item case-mail-picker-row ${caseMailPriorityClass(
          mail.effective_importance,
        )} mail-read-${mail.read_status ?? 'unread'}`}
        key={mail.id}
        onClick={options.onClick}
        type="button"
      >
        <div className="mail-list-sender-media">
          <span className="mail-list-time">{formatMailTime(mail.received_at)}</span>
          <img
            alt={t('mail.senderAvatarAlt', {
              name: caseMailSenderDisplayName(mail),
            })}
            src={caseMailSenderAvatarUrl(mail)}
          />
        </div>
        <div className="mail-list-main">
          <strong>
            <span>{mail.subject ?? t('mail.noSubject')}</span>
          </strong>
          <span>{caseMailSenderDisplayName(mail)}</span>
        </div>
        <p className="mail-list-summary">{caseMailSummary(mail)}</p>
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
          {(mail.case_links ?? []).length > 0 ? (
            mail.case_links?.map((caseLink) => (
              <span key={caseLink.id}>{caseLink.title}</span>
            ))
          ) : (
            <span>{t('mail.noCase')}</span>
          )}
          <span>{options.actionLabel}</span>
        </div>
      </button>
    )
  }

  function renderMailPickerList(
    mails: MailListItem[],
    options: {
      actionLabel: string
      onClick: (mail: MailListItem) => void
      showGroups?: boolean
    },
  ) {
    return (
      <div className="mail-list case-mail-picker-list" role="list">
        {mails.map((mail, index) => (
          <div className="mail-list-entry" key={mail.id}>
            {options.showGroups !== false &&
              shouldShowCaseMailGroupLabel(mail, index, mails, assignSort) && (
                <div className="mail-list-group-label">
                  <span>{caseMailGroupLabel(mail, assignSort)}</span>
                </div>
              )}
            {shouldShowCaseMailImportanceThreshold(mail, index, mails, assignSort) && (
              <div aria-hidden="true" className="mail-importance-threshold" />
            )}
            {renderMailRow(mail, {
              actionLabel: options.actionLabel,
              onClick: () => options.onClick(mail),
            })}
          </div>
        ))}
      </div>
    )
  }

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
        {notice !== null && (
          <div className="mail-feedback">
            <p>{notice}</p>
          </div>
        )}

        {isAssignMode ? (
          <>
            <div className="mail-main-layout case-mail-assign-layout">
              <div className="mail-main-column">
                <section aria-labelledby="case-mail-search-results-heading" className="mail-list-workspace">
                  <div className="mail-panel mail-list-panel">
                    <div className="section-heading">
                      <div>
                        <h2 id="case-mail-search-results-heading">
                          {t('mail.search.results')}
                        </h2>
                        <p>{t('mail.search.resultNote')}</p>
                      </div>
                      <div className="mail-list-heading-actions">
                        <button
                          className={`button-loading-dot${isSearchingMails ? ' is-loading' : ''}`}
                          disabled={isSearchingMails}
                          onClick={() => setAssignSearchRefreshTick((tick) => tick + 1)}
                          type="button"
                        >
                          {t('mail.refresh')}
                        </button>
                        <button
                          className="case-mail-add-button"
                          onClick={() => {
                            setIsAssignMode(false)
                            setError(null)
                            setNotice(null)
                          }}
                          type="button"
                        >
                          {t('common.cancel')}
                        </button>
                      </div>
                    </div>

                    {pinnedMailItems.length > 0 && (
                      <div className="mail-list case-mail-picker-list case-mail-pinned-list" role="list">
                        <div className="mail-list-entry">
                          <div className="mail-list-group-label">
                            <span>{t('cases.mail.pinned')}</span>
                          </div>
                        </div>
                        {pinnedMailItems.map((mail) => (
                          <div className="mail-list-entry" key={caseMailThreadKey(mail)}>
                            {renderMailRow(mail, {
                              actionLabel: t('cases.mail.unpin'),
                              onClick: () => unpinMail(mail),
                            })}
                          </div>
                        ))}
                      </div>
                    )}

                    {normalizedAssignQuery === '' ? (
                      <p className="mail-empty">{t('cases.mail.assignSearchPrompt')}</p>
                    ) : isSearchingMails ? (
                      <p className="mail-empty">{t('mail.loading')}</p>
                    ) : visibleMailSearchResults.length === 0 ? (
                      <p className="mail-empty">{t('mail.search.empty')}</p>
                    ) : (
                      renderMailPickerList(visibleMailSearchResults, {
                        actionLabel: t('cases.mail.pin'),
                        onClick: pinMail,
                      })
                    )}
                  </div>
                </section>
              </div>

              <aside className="mail-side-column">
                <section aria-labelledby="case-mail-sort-heading" className="mail-panel mail-sort-panel">
                  <div className="section-heading">
                    <h2 id="case-mail-sort-heading">{t('mail.sort.heading')}</h2>
                  </div>
                  <div aria-label={t('mail.sort.label')} className="mail-sort-control">
                    <button
                      aria-pressed={assignSort === 'importance'}
                      onClick={() => setAssignSort('importance')}
                      type="button"
                    >
                      {t('mail.sort.importance')}
                    </button>
                    <button
                      aria-pressed={assignSort === 'newest'}
                      onClick={() => setAssignSort('newest')}
                      type="button"
                    >
                      {t('mail.sort.newest')}
                    </button>
                  </div>
                </section>

                <section aria-labelledby="case-mail-search-heading" className="mail-panel mail-search-panel">
                  <div className="section-heading">
                    <h2 id="case-mail-search-heading">{t('mail.search.heading')}</h2>
                  </div>
                  <form
                    className="mail-search-form"
                    onSubmit={(event) => {
                      event.preventDefault()
                      setAssignSearchRefreshTick((tick) => tick + 1)
                    }}
                  >
                    <input
                      aria-label={t('mail.search.label')}
                      onChange={(event) => setAssignSearchQuery(event.target.value)}
                      placeholder={t('mail.search.placeholder')}
                      value={assignSearchQuery}
                    />
                    <select
                      aria-label={t('mail.pageSize')}
                      onChange={(event) => setAssignPageSize(Number(event.target.value))}
                      value={assignPageSize}
                    >
                      <option value={10}>10</option>
                      <option value={25}>25</option>
                      <option value={50}>50</option>
                    </select>
                    <div className="mail-search-actions">
                      <button
                        className={`button-loading-dot${isSearchingMails ? ' is-loading' : ''}`}
                        disabled={isSearchingMails}
                        type="submit"
                      >
                        {t('mail.search.submit')}
                      </button>
                      <button
                        className={`button-loading-dot${isSearchingMails ? ' is-loading' : ''}`}
                        disabled={isSearchingMails || assignSearchQuery.trim() === ''}
                        onClick={() => setAssignSearchQuery('')}
                        type="button"
                      >
                        {t('mail.search.clear')}
                      </button>
                    </div>
                  </form>
                </section>

                <section aria-labelledby="case-mail-special-import-heading" className="mail-panel mail-search-panel">
                  <div className="section-heading">
                    <div>
                      <h2 id="case-mail-special-import-heading">
                        {t('cases.mail.specialImport.heading')}
                      </h2>
                      <p>{t('cases.mail.specialImport.body')}</p>
                    </div>
                  </div>
                  <form className="mail-search-form" onSubmit={handleSpecialGmailImport}>
                    <input
                      aria-label={t('cases.mail.specialImport.label')}
                      onChange={(event) => setSpecialGmailSource(event.target.value)}
                      placeholder={t('cases.mail.specialImport.placeholder')}
                      value={specialGmailSource}
                    />
                    <div className="mail-search-actions">
                      <button
                        className={`button-loading-dot${isSpecialGmailLoading ? ' is-loading' : ''}`}
                        disabled={isSpecialGmailLoading || specialGmailSource.trim() === ''}
                        type="submit"
                      >
                        {t('cases.mail.specialImport.load')}
                      </button>
                    </div>
                  </form>
                </section>

                <section aria-labelledby="case-mail-pin-heading" className="mail-panel mail-search-panel">
                  <div className="section-heading">
                    <h2 id="case-mail-pin-heading">{t('cases.mail.pinTools')}</h2>
                  </div>
                  <div className="case-mail-pin-actions">
                    <button
                      disabled={
                        isSearchingMails ||
                        normalizedAssignQuery === '' ||
                        visibleMailSearchResults.length === 0
                      }
                      onClick={pinVisibleMailSearchResults}
                      type="button"
                    >
                      {t('cases.mail.pinAllSearchResults')}
                    </button>
                    <button
                      disabled={pinnedMailItems.length === 0}
                      onClick={() => setPinnedMails({})}
                      type="button"
                    >
                      {t('cases.mail.resetPinned')}
                    </button>
                  </div>
                  <p className="case-mail-pin-note">
                    {t('cases.mail.pinnedCount', { count: pinnedMailItems.length })}
                  </p>
                </section>
              </aside>
            </div>
            <div className="case-mail-register-bar">
              <button
                className={`button-loading-dot${isAssigning ? ' is-loading' : ''}`}
                disabled={isAssigning || pinnedMailItems.length === 0}
                onClick={() => {
                  void handleRegisterPinnedMails()
                }}
                type="button"
              >
                {t('cases.mail.registerPinned')}
              </button>
            </div>
          </>
        ) : (
          <>
            <section className="case-mail-assignment-tools">
              <div className="section-heading">
                <h2>{t('cases.mail.assignedTools')}</h2>
                <button
                  className="case-mail-add-button"
                  onClick={() => {
                    setIsAssignMode(true)
                    setError(null)
                    setNotice(null)
                  }}
                  type="button"
                >
                  {t('cases.mail.add')}
                </button>
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

            <section className="case-mail-auto-rule-panel">
              <div className="section-heading">
                <div>
                  <h2>{t('cases.mail.autoRule.heading')}</h2>
                  <p>{t('cases.mail.autoRule.body')}</p>
                </div>
              </div>
              <form className="case-mail-auto-rule-form" onSubmit={handleCreateAutoAssignRule}>
                <label>
                  <span>{t('cases.mail.autoRule.senderEmail')}</span>
                  <SuggestInput
                    ariaLabel={t('cases.mail.autoRule.senderEmail')}
                    maxItems={1}
                    onChange={setAutoRuleSenderEmail}
                    options={autoRuleStakeholderSuggestions.map((suggestion) => ({
                      key: suggestion.email,
                      value: suggestion.email,
                      label: suggestion.label,
                      badgeLabel: suggestion.email,
                    }))}
                    placeholder={t('cases.mail.autoRule.placeholder')}
                    value={autoRuleSenderEmail}
                  />
                </label>
                <button
                  className={`button-loading-dot${isAutoRuleSaving ? ' is-loading' : ''}`}
                  disabled={isAutoRuleSaving || autoRuleSenderEmail.trim() === ''}
                  type="submit"
                >
                  {t('cases.mail.autoRule.add')}
                </button>
              </form>
              {autoAssignRules.length === 0 ? (
                <p className="case-mail-auto-rule-empty">
                  {t('cases.mail.autoRule.empty')}
                </p>
              ) : (
                <div className="case-mail-auto-rule-list">
                  {autoAssignRules.map((rule) => (
                    <div className="case-mail-auto-rule-item" key={rule.id}>
                      <span>{rule.rule_value}</span>
                      <button
                        disabled={isAutoRuleSaving}
                        onClick={() => {
                          void handleDeleteAutoAssignRule(rule)
                        }}
                        type="button"
                      >
                        {t('cases.mail.autoRule.delete')}
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </section>

            <section className="case-mail-assignment-panel">
              <div className="section-heading">
                <div>
                  <h2>{t('cases.mail.assignedList')}</h2>
                  <p>{t('cases.mail.assignedCount', { count: visibleMailLinks.length })}</p>
                </div>
                <button
                  aria-pressed={isRemoveMode}
                  className="case-mail-add-button"
                  disabled={visibleMailLinks.length === 0}
                  onClick={() => setIsRemoveMode((current) => !current)}
                  type="button"
                >
                  {isRemoveMode ? t('cases.mail.removeModeOff') : t('cases.mail.removeModeOn')}
                </button>
              </div>
              {isLoading ? (
                <p className="mail-empty">{t('cases.loading')}</p>
              ) : visibleMailLinks.length === 0 ? (
                <p className="mail-empty">{t('cases.mail.assignedEmpty')}</p>
              ) : (
                <div className="case-assigned-mail-list">
                  {visibleMailLinks.map((mail) => (
                    <div className="case-assigned-mail-row" key={mail.id}>
                      <AppLink className="case-assigned-mail-link" href={mail.mail_url}>
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
                      {isRemoveMode && (
                        <button
                          className="case-assigned-mail-remove"
                          disabled={isAssigning}
                          onClick={() => {
                            void handleUnassignMailThread(mail)
                          }}
                          type="button"
                        >
                          {t('cases.mail.unassign')}
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </section>
          </>
        )}
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
