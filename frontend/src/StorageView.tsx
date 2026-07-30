import { Fragment, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import type { MouseEvent } from 'react'
import { t } from './i18n'
import { AppLink, TopNav, navigateTo } from './navigation'
import defaultContactAvatarUrl from './assets/default-contact-avatar.svg'
import downloadIconUrl from './assets/download-icon.svg'
import folderDirectoryIconUrl from './assets/folder-directory-icon.svg'
import paperclipDiagonalUrl from './assets/paperclip-diagonal.svg'
import settingsGearIconUrl from './assets/settings-gear.svg'
import trashIconUrl from './assets/trash-icon.svg'
import {
  fileExtension,
  isPreviewableImageFile,
  isPreviewableDelimitedTableFile,
  isPreviewableEmlFile,
  isPreviewableMarkdownFile,
  isPreviewablePdfFile,
  isPreviewableTextFile,
  isPreviewableVideoFile,
  isPreviewableZipFile,
  storageImagePreviewUrl,
} from './storagePreview'
import {
  deleteStorageObject,
  deleteStorageObjectCaseLink,
  deleteOlderStorageObjectVersions,
  createStorageObjectCaseLink,
  getStorageObject,
  getStorageObjectArchiveTree,
  getStorageObjectEmlPreview,
  getStorageObjectLlmDigest,
  getStorageObjectVersionEmlPreview,
  getStorageObjectVersionArchiveTree,
  listStorageObjectLinkedCases,
  listStorageObjectVersions,
  prepareStorageObjectLlmDigest,
  uploadStorageObjectVersion,
  updateStorageObjectFilename,
  updateStorageObjectLlmInput,
} from './phase3Api'
import type { StorageObject } from './phase3Api'
import type { StorageDirectory } from './phase3Api'
import type { StorageObjectVersion } from './phase3Api'
import type { StorageSourceMail } from './phase3Api'
import type { StorageEmlPreview } from './phase3Api'
import type { FileSummary, FileVersionDiff } from './phase3Api'
import type { StorageObjectLinkedCase } from './phase3Api'
import { isCaseOpenForSuggestion, listCases } from './phase7Api'
import type { CaseItem } from './phase7Api'
import SuggestInput from './SuggestInput'
import StorageBrowser from './StorageBrowser'

type StoragePreviewFile = {
  id: string
  original_filename: string | null
  content_type: string | null
  byte_size: number
  sha256_hex: string
  url: string
  download_url: string
  updated_at: string
}

function describeError(error: unknown) {
  return error instanceof Error ? error.message : t('storage.requestFailed')
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  const kib = bytes / 1024
  if (kib < 1024) return `${kib.toFixed(kib >= 10 ? 0 : 1)} KB`
  const mib = kib / 1024
  if (mib < 1024) return `${mib.toFixed(mib >= 10 ? 0 : 1)} MB`
  const gib = mib / 1024
  return `${gib.toFixed(gib >= 10 ? 0 : 1)} GB`
}

function formatTime(value: string) {
  return value.slice(11, 16)
}

function formatDateTime(value: string) {
  return `${value.slice(0, 10)} ${value.slice(11, 16)}`
}

function currentStoragePreviewFile(object: StorageObject): StoragePreviewFile {
  const cacheKey = encodeURIComponent(`${object.sha256_hex}-${object.file_updated_at}`)
  return {
    id: object.id,
    original_filename: object.original_filename,
    content_type: object.content_type,
    byte_size: object.byte_size,
    sha256_hex: object.sha256_hex,
    url: `${object.url}?v=${cacheKey}`,
    download_url: `/api/v1/storage/objects/${encodeURIComponent(object.id)}/download`,
    updated_at: object.file_updated_at,
  }
}

function versionStoragePreviewFile(version: StorageObjectVersion): StoragePreviewFile {
  const baseUrl = `/api/v1/storage/objects/${encodeURIComponent(
    version.storage_object_id,
  )}/versions/${encodeURIComponent(version.id)}`
  const cacheKey = encodeURIComponent(`${version.sha256_hex}-${version.created_at}`)
  return {
    id: version.id,
    original_filename: version.original_filename,
    content_type: version.content_type,
    byte_size: version.byte_size,
    sha256_hex: version.sha256_hex,
    url: `${baseUrl}/content?v=${cacheKey}`,
    download_url: baseUrl + '/download',
    updated_at: version.created_at,
  }
}

function mailPriorityClass(importance: string) {
  return `mail-priority-${importance}`
}

function charsetFromContentType(contentType: string | null) {
  const match = /charset=([^;]+)/i.exec(contentType ?? '')
  return match?.[1]?.trim().replace(/^"|"$/g, '').toLowerCase() ?? null
}

function decodeWithEncoding(buffer: ArrayBuffer, encoding: string) {
  try {
    return new TextDecoder(encoding).decode(buffer)
  } catch {
    return null
  }
}

function textDecodeScore(text: string) {
  let score = 0
  for (const char of text) {
    const code = char.charCodeAt(0)
    if (char === '\uFFFD') score += 100
    if ((code < 32 && !['\n', '\r', '\t'].includes(char)) || code === 0x7f) score += 25
  }
  const mojibakePatterns = ['邵ｺ', '郢ｧ', '闕ｳ', '驍ｱ', '・ｽ']
  for (const pattern of mojibakePatterns) {
    score += Math.max(0, text.split(pattern).length - 1) * 12
  }
  return score
}

function decodePreviewText(buffer: ArrayBuffer, contentType: string | null) {
  const preferredCharset = charsetFromContentType(contentType)
  const encodings = [
    preferredCharset,
    'utf-8',
    'shift_jis',
    'euc-jp',
    'iso-2022-jp',
  ].filter((encoding, index, values): encoding is string => (
    encoding !== null && values.indexOf(encoding) === index
  ))

  let bestText = ''
  let bestScore = Number.POSITIVE_INFINITY
  for (const encoding of encodings) {
    const decoded = decodeWithEncoding(buffer, encoding)
    if (decoded === null) continue
    const score = textDecodeScore(decoded)
    if (score < bestScore) {
      bestText = decoded
      bestScore = score
    }
  }
  return bestText
}

export async function downloadStorageObject(object: StoragePreviewFile | StorageObject) {
  const downloadUrl =
    'download_url' in object
      ? object.download_url
      : `/api/v1/storage/objects/${encodeURIComponent(object.id)}/download`
  const response = await fetch(downloadUrl, { credentials: 'include' })
  if (!response.ok) {
    throw new Error(t('storage.downloadFailed'))
  }
  const blob = await response.blob()
  const objectUrl = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = objectUrl
  link.download = object.original_filename ?? object.id
  document.body.append(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(objectUrl)
}

function isPreviewableImage(object: StoragePreviewFile) {
  return isPreviewableImageFile({
    contentType: object.content_type,
    filename: object.original_filename,
  })
}

function isPreviewableText(object: StoragePreviewFile) {
  return isPreviewableTextFile({
    contentType: object.content_type,
    filename: object.original_filename,
  })
}

function isPreviewablePdf(object: StoragePreviewFile) {
  return isPreviewablePdfFile({
    contentType: object.content_type,
    filename: object.original_filename,
  })
}

function isPreviewableVideo(object: StoragePreviewFile) {
  return isPreviewableVideoFile({
    contentType: object.content_type,
    filename: object.original_filename,
  })
}

function isPreviewableMarkdown(object: StoragePreviewFile) {
  return isPreviewableMarkdownFile({
    contentType: object.content_type,
    filename: object.original_filename,
  })
}

function isPreviewableDelimitedTable(object: StoragePreviewFile) {
  return isPreviewableDelimitedTableFile({
    contentType: object.content_type,
    filename: object.original_filename,
  })
}

function isPreviewableZip(object: StoragePreviewFile) {
  return isPreviewableZipFile({
    contentType: object.content_type,
    filename: object.original_filename,
  })
}

function isPreviewableEml(object: StoragePreviewFile) {
  return isPreviewableEmlFile({
    contentType: object.content_type,
    filename: object.original_filename,
  })
}

const textPreviewByteLimit = 2 * 1024 * 1024
export const storageObjectDragType = 'application/x-caseclosed-storage-object'
export const storageDirectoryDragType = 'application/x-caseclosed-storage-directory'

function storageSourceLabel(object: StorageObject) {
  if (object.source_type === 'direct_upload') {
    return t('storage.source.directUpload')
  }
  if (object.source_type === 'mail_attachment') {
    return t('storage.source.mailAttachment')
  }
  return t('common.none')
}

function linkedCaseSourceLabel(source: string) {
  if (source === 'physical') return t('storage.linkedCases.source.physical')
  if (source === 'link') return t('storage.linkedCases.source.link')
  return source
}

function storageSourceMailSender(mail: StorageSourceMail) {
  return mail.from_name?.trim() || mail.from_address
}

function directoryIdFromLocation() {
  const value = new URLSearchParams(window.location.search).get('directory')
  return value === null || value.trim() === '' ? null : value
}

function directoryPathLabel(path: string[] | undefined) {
  if (path === undefined || path.length === 0) {
    return t('storage.directory.root')
  }
  return [t('storage.directory.root'), ...path].join(' / ')
}

function StorageSourceMailCard({ mail }: { mail: StorageSourceMail }) {
  return (
    <section className="storage-source-mail-section">
      <h2>{t('storage.source.mail')}</h2>
      <article
        className={`mail-list-item storage-source-mail-card ${mailPriorityClass(
          mail.effective_importance,
        )} mail-read-${mail.read_status}`}
        onClick={() => navigateTo(`/mail/${encodeURIComponent(mail.id)}`)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault()
            navigateTo(`/mail/${encodeURIComponent(mail.id)}`)
          }
        }}
        role="link"
        tabIndex={0}
      >
        <div className="mail-list-sender-media">
          <span className="mail-list-time">{formatTime(mail.received_at)}</span>
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
      }${isTaskDirectory ? ' storage-task-directory-card' : ''
      }`}
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

function StorageObjectDetailView({ storageObjectId }: { storageObjectId: string }) {
  const [object, setObject] = useState<StorageObject | null>(null)
  const [versions, setVersions] = useState<StorageObjectVersion[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [textPreview, setTextPreview] = useState<string | null>(null)
  const [textPreviewStatus, setTextPreviewStatus] = useState<
    'idle' | 'loading' | 'loaded' | 'too-large' | 'failed'
  >('idle')
  const [archiveTreeText, setArchiveTreeText] = useState<string | null>(null)
  const [archiveTreeStatus, setArchiveTreeStatus] = useState<
    'idle' | 'loading' | 'loaded' | 'failed'
  >('idle')
  const [emlPreview, setEmlPreview] = useState<StorageEmlPreview | null>(null)
  const [emlPreviewStatus, setEmlPreviewStatus] = useState<
    'idle' | 'loading' | 'loaded' | 'failed'
  >('idle')
  const [downloadBusyId, setDownloadBusyId] = useState<string | null>(null)
  const [llmBusy, setLlmBusy] = useState(false)
  const [digestBusy, setDigestBusy] = useState(false)
  const [fileSummary, setFileSummary] = useState<FileSummary | null>(null)
  const [fileSummaryIsStale, setFileSummaryIsStale] = useState(false)
  const [fileSummaryStaleReason, setFileSummaryStaleReason] = useState<string | null>(null)
  const [fileVersionDiff, setFileVersionDiff] = useState<FileVersionDiff | null>(null)
  const [fileSummaryStatus, setFileSummaryStatus] = useState<
    'idle' | 'loading' | 'loaded' | 'missing' | 'failed'
  >('idle')
  const [linkedCases, setLinkedCases] = useState<StorageObjectLinkedCase[]>([])
  const [linkedCasesStatus, setLinkedCasesStatus] = useState<
    'idle' | 'loading' | 'loaded' | 'failed'
  >('idle')
  const [isLinkedCasesEditing, setIsLinkedCasesEditing] = useState(false)
  const [linkedCaseInput, setLinkedCaseInput] = useState('')
  const [caseSuggestions, setCaseSuggestions] = useState<CaseItem[]>([])
  const [linkedCasesBusy, setLinkedCasesBusy] = useState(false)
  const [renameDraft, setRenameDraft] = useState('')
  const [renameBusy, setRenameBusy] = useState(false)
  const [deleteBusy, setDeleteBusy] = useState(false)
  const [versionBusy, setVersionBusy] = useState(false)
  const [isVersionDragOver, setIsVersionDragOver] = useState(false)
  const [selectedVersionId, setSelectedVersionId] = useState('current')
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    let isMounted = true
    setIsLoading(true)
    setError(null)
    setSelectedVersionId('current')
    getStorageObject(storageObjectId)
      .then(async (nextObject) => {
        if (!isMounted) return
        setObject(nextObject)
        setRenameDraft(nextObject.original_filename ?? nextObject.id)
        try {
          const nextVersions = await listStorageObjectVersions(storageObjectId)
          if (isMounted) setVersions(nextVersions)
        } catch {
          if (isMounted) setVersions([])
        }
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
  }, [storageObjectId])

  useEffect(() => {
    const selectedVersion = versions.find((version) => version.id === selectedVersionId) ?? null
    const previewFile =
      object === null
        ? null
        : selectedVersion === null
          ? currentStoragePreviewFile(object)
          : versionStoragePreviewFile(selectedVersion)

    if (
      previewFile === null ||
      !isPreviewableText(previewFile) ||
      isPreviewableImage(previewFile)
    ) {
      setTextPreview(null)
      setTextPreviewStatus('idle')
      return undefined
    }
    const shouldLoadPartial = isPreviewableDelimitedTable(previewFile)
    if (previewFile.byte_size > textPreviewByteLimit && !shouldLoadPartial) {
      setTextPreview(null)
      setTextPreviewStatus('too-large')
      return undefined
    }

    let isMounted = true
    setTextPreview(null)
    setTextPreviewStatus('loading')
    fetch(previewFile.url, {
      credentials: 'include',
      headers: shouldLoadPartial && previewFile.byte_size > textPreviewByteLimit
        ? { Range: `bytes=0-${textPreviewByteLimit - 1}` }
        : undefined,
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error(t('storage.preview.textFailed'))
        }
        const responseContentType = response.headers.get('content-type') ?? ''
        if (responseContentType.toLowerCase().includes('text/html')) {
          throw new Error(t('storage.preview.textFailed'))
        }
        return response.arrayBuffer()
      })
      .then((buffer) => {
        if (!isMounted) return
        setTextPreview(decodePreviewText(buffer, previewFile.content_type))
        setTextPreviewStatus('loaded')
      })
      .catch(() => {
        if (!isMounted) return
        setTextPreview(null)
        setTextPreviewStatus('failed')
      })
    return () => {
      isMounted = false
    }
  }, [object, selectedVersionId, versions])

  useEffect(() => {
    const selectedVersion = versions.find((version) => version.id === selectedVersionId) ?? null
    const previewFile =
      object === null
        ? null
        : selectedVersion === null
          ? currentStoragePreviewFile(object)
          : versionStoragePreviewFile(selectedVersion)

    if (object === null || previewFile === null || !isPreviewableEml(previewFile)) {
      setEmlPreview(null)
      setEmlPreviewStatus('idle')
      return undefined
    }

    let isMounted = true
    setEmlPreview(null)
    setEmlPreviewStatus('loading')
    const request =
      selectedVersion === null
        ? getStorageObjectEmlPreview(object.id)
        : getStorageObjectVersionEmlPreview(object.id, selectedVersion.id)
    request
      .then((preview) => {
        if (!isMounted) return
        setEmlPreview(preview)
        setEmlPreviewStatus('loaded')
      })
      .catch(() => {
        if (!isMounted) return
        setEmlPreview(null)
        setEmlPreviewStatus('failed')
      })
    return () => {
      isMounted = false
    }
  }, [object, selectedVersionId, versions])

  useEffect(() => {
    if (object === null) {
      setFileSummary(null)
      setFileSummaryIsStale(false)
      setFileSummaryStaleReason(null)
      setFileVersionDiff(null)
      setFileSummaryStatus('idle')
      return undefined
    }
    let isMounted = true
    setFileSummary(null)
    setFileSummaryIsStale(false)
    setFileSummaryStaleReason(null)
    setFileVersionDiff(null)
    setFileSummaryStatus('loading')
    const versionId = selectedVersionId === 'current' ? null : selectedVersionId
    getStorageObjectLlmDigest(object.id, versionId)
      .then((response) => {
        if (!isMounted) return
        setFileSummary(response.summary)
        setFileSummaryIsStale(response.is_stale)
        setFileSummaryStaleReason(response.stale_reason)
        setFileVersionDiff(response.diff)
        setFileSummaryStatus(response.summary === null ? 'missing' : 'loaded')
      })
      .catch(() => {
        if (!isMounted) return
        setFileSummary(null)
        setFileSummaryIsStale(false)
        setFileSummaryStaleReason(null)
      setFileVersionDiff(null)
      setFileSummaryStatus('failed')
    })
    return () => {
      isMounted = false
    }
  }, [object, selectedVersionId])

  useEffect(() => {
    if (object === null) {
      setLinkedCases([])
      setLinkedCasesStatus('idle')
      return undefined
    }
    let isMounted = true
    setLinkedCases([])
    setLinkedCasesStatus('loading')
    listStorageObjectLinkedCases(object.id)
      .then((items) => {
        if (!isMounted) return
        setLinkedCases(items)
        setLinkedCasesStatus('loaded')
      })
      .catch(() => {
        if (!isMounted) return
        setLinkedCases([])
        setLinkedCasesStatus('failed')
      })
    return () => {
      isMounted = false
    }
  }, [object])

  useEffect(() => {
    if (!isLinkedCasesEditing) return undefined
    let isMounted = true
    listCases('all')
      .then((items) => {
        if (isMounted) setCaseSuggestions(items.filter((item) => isCaseOpenForSuggestion(item)))
      })
      .catch(() => {
        if (isMounted) setCaseSuggestions([])
      })
    return () => {
      isMounted = false
    }
  }, [isLinkedCasesEditing])

  useEffect(() => {
    const selectedVersion = versions.find((version) => version.id === selectedVersionId) ?? null
    const previewFile =
      object === null
        ? null
        : selectedVersion === null
          ? currentStoragePreviewFile(object)
          : versionStoragePreviewFile(selectedVersion)

    if (object === null || previewFile === null || !isPreviewableZip(previewFile)) {
      setArchiveTreeText(null)
      setArchiveTreeStatus('idle')
      return undefined
    }

    let isMounted = true
    setArchiveTreeText(null)
    setArchiveTreeStatus('loading')
    const request =
      selectedVersion === null
        ? getStorageObjectArchiveTree(object.id)
        : getStorageObjectVersionArchiveTree(object.id, selectedVersion.id)
    request
      .then((tree) => {
        if (!isMounted) return
        setArchiveTreeText(tree.tree_text)
        setArchiveTreeStatus('loaded')
      })
      .catch(() => {
        if (!isMounted) return
        setArchiveTreeText(null)
        setArchiveTreeStatus('failed')
      })
    return () => {
      isMounted = false
    }
  }, [object, selectedVersionId, versions])

  function selectedLinkedCaseCandidate() {
    const normalizedInput = linkedCaseInput.trim().toLowerCase()
    if (normalizedInput === '') return null
    return (
      caseSuggestions.find(
        (item) =>
          item.name.toLowerCase() === normalizedInput ||
          item.id.toLowerCase() === normalizedInput,
      ) ?? null
    )
  }

  async function handleAddLinkedCase() {
    if (object === null || linkedCasesBusy) return
    const candidate = selectedLinkedCaseCandidate()
    if (candidate === null) {
      setError(t('storage.linkedCases.invalidCase'))
      return
    }
    setLinkedCasesBusy(true)
    setError(null)
    setNotice(null)
    try {
      const items = await createStorageObjectCaseLink(object.id, candidate.id)
      setLinkedCases(items)
      setLinkedCaseInput('')
      setNotice(t('storage.linkedCases.added', { name: candidate.name }))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setLinkedCasesBusy(false)
    }
  }

  async function handleDeleteLinkedCase(item: StorageObjectLinkedCase) {
    if (object === null || linkedCasesBusy) return
    setLinkedCasesBusy(true)
    setError(null)
    setNotice(null)
    try {
      const items = await deleteStorageObjectCaseLink(object.id, item.case_id)
      setLinkedCases(items)
      const nextObject = await getStorageObject(object.id)
      setObject(nextObject)
      setNotice(t('storage.linkedCases.deleted', { name: item.case_name }))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setLinkedCasesBusy(false)
    }
  }

  async function handleDownloadPreview(target: StoragePreviewFile) {
    setDownloadBusyId(target.id)
    setError(null)
    try {
      await downloadStorageObject(target)
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setDownloadBusyId(null)
    }
  }

  async function handleUpdateLlmInput(target: StorageObject, allowed: boolean) {
    setLlmBusy(true)
    setError(null)
    try {
      const updatedObject = await updateStorageObjectLlmInput(target.id, allowed)
      setObject(updatedObject)
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setLlmBusy(false)
    }
  }

  async function handleRename(target: StorageObject) {
    const nextName = renameDraft.trim()
    if (nextName === '') {
      setError(t('storage.rename.empty'))
      return
    }
    if (nextName === (target.original_filename ?? target.id)) {
      return
    }
    setRenameBusy(true)
    setError(null)
    setNotice(null)
    try {
      const updatedObject = await updateStorageObjectFilename(target.id, nextName)
      setObject(updatedObject)
      setRenameDraft(updatedObject.original_filename ?? updatedObject.id)
      setNotice(t('storage.rename.updated', { name: updatedObject.original_filename ?? updatedObject.id }))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setRenameBusy(false)
    }
  }

  async function handleDelete(target: StorageObject) {
    if (!window.confirm(t('storage.delete.confirm', { name: target.original_filename ?? target.id }))) {
      return
    }
    setDeleteBusy(true)
    setError(null)
    try {
      await deleteStorageObject(target.id)
      navigateTo('/files')
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setDeleteBusy(false)
    }
  }

  async function handleDeleteOlderVersions(target: StorageObject, version: StorageObjectVersion) {
    if (
      !window.confirm(
        t('storage.version.deleteOlderConfirm', {
          version: String(version.version_number),
        }),
      )
    ) {
      return
    }
    setDeleteBusy(true)
    setError(null)
    setNotice(null)
    try {
      const result = await deleteOlderStorageObjectVersions(target.id, version.id)
      const nextVersions = await listStorageObjectVersions(target.id)
      setObject(result.storage_object)
      setVersions(nextVersions)
      setSelectedVersionId('current')
      setNotice(
        t('storage.version.deletedOlder', {
          count: String(result.deleted_version_count),
        }),
      )
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setDeleteBusy(false)
    }
  }

  async function handleLlmDigest() {
    if (object === null || !object.llm_input_allowed || digestBusy) return
    setDigestBusy(true)
    setError(null)
    setNotice(null)
    try {
      const versionId = selectedVersionId === 'current' ? null : selectedVersionId
      const response = await prepareStorageObjectLlmDigest(object.id, versionId)
      setObject(response.storage_object)
      setFileSummary(response.summary)
      setFileSummaryIsStale(response.is_stale)
      setFileSummaryStaleReason(response.stale_reason)
      setFileVersionDiff(response.diff)
      setFileSummaryStatus('loaded')
      setNotice(t('storage.llmDigest.prepared'))
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setDigestBusy(false)
    }
  }

  async function handleVersionDrop(file: File) {
    if (object === null || versionBusy) return
    const currentExtension = fileExtension(object.original_filename)
    const nextExtension = fileExtension(file.name)
    if (
      currentExtension !== nextExtension &&
      !window.confirm(
        t('storage.version.extensionConfirm', {
          current: currentExtension,
          next: nextExtension,
        }),
      )
    ) {
      return
    }
    setVersionBusy(true)
    setError(null)
    setNotice(null)
    try {
      const response = await uploadStorageObjectVersion(object.id, file)
      const nextVersions = await listStorageObjectVersions(object.id)
      setObject(response.storage_object)
      setVersions(nextVersions)
      setSelectedVersionId('current')
      setNotice(
        response.skipped
          ? t('storage.version.skippedDuplicate')
          : t('storage.version.updated'),
      )
    } catch (requestError) {
      setError(describeError(requestError))
    } finally {
      setVersionBusy(false)
      setIsVersionDragOver(false)
    }
  }

  const filename = object?.original_filename ?? object?.id ?? t('storage.detail.file')
  const selectedVersion = versions.find((version) => version.id === selectedVersionId) ?? null
  const olderVersionCount =
    selectedVersion === null
      ? 0
      : versions.filter((version) => version.version_number <= selectedVersion.version_number)
          .length
  const previewFile =
    object === null
      ? null
      : selectedVersion === null
        ? currentStoragePreviewFile(object)
        : versionStoragePreviewFile(selectedVersion)

  return (
    <main className="app-shell">
      <div className="mail-shell storage-shell">
        <header className="maintenance-header">
          <div>
            <p>{t('storage.heading')}</p>
            <h1>{filename}</h1>
          </div>
          <TopNav
            ariaLabelKey="storage.navigation"
            items={[
              { href: '/files', labelKey: 'nav.files' },
              { href: '/', labelKey: 'top.heading' },
              { href: '/cases', labelKey: 'nav.cases' },
              { href: '/tasks', labelKey: 'nav.tasks' },
            ]}
          />
        </header>

        {error !== null && (
          <section className="notice error" role="alert">
            <p>{error}</p>
          </section>
        )}
        {notice !== null && (
          <section className="notice">
            <p>{notice}</p>
          </section>
        )}

        <section className="mail-panel storage-detail-panel">
          {isLoading && <p>{t('storage.loading')}</p>}
          {!isLoading && object !== null && (
            <>
              <div className="storage-detail-toolbar">
                <button
                  className={`button-loading-dot${
                    previewFile !== null && downloadBusyId === previewFile.id ? ' is-loading' : ''
                  }`}
                  disabled={previewFile !== null && downloadBusyId === previewFile.id}
                  onClick={() => {
                    if (previewFile !== null) void handleDownloadPreview(previewFile)
                  }}
                  type="button"
                >
                  <ActionIconLabel
                    iconUrl={downloadIconUrl}
                    label={t('storage.version.downloadSelected')}
                  />
                </button>
                <button
                  className={`button-loading-dot${deleteBusy ? ' is-loading' : ''}`}
                  disabled={deleteBusy || (selectedVersion !== null && olderVersionCount === 0)}
                  onClick={() => {
                    if (selectedVersion === null) {
                      void handleDelete(object)
                    } else {
                      void handleDeleteOlderVersions(object, selectedVersion)
                    }
                  }}
                  type="button"
                >
                  <ActionIconLabel
                    iconUrl={trashIconUrl}
                    label={
                      selectedVersion === null
                        ? t('storage.context.deleteSeries')
                        : t('storage.version.deleteOlder')
                    }
                  />
                </button>
                <button
                  className={`storage-llm-action-button button-loading-dot${
                    llmBusy ? ' is-loading' : ''
                  }`}
                  disabled={llmBusy}
                  onClick={() => void handleUpdateLlmInput(object, !object.llm_input_allowed)}
                  type="button"
                >
                  {object.llm_input_allowed
                    ? t('storage.llmInput.disallow')
                    : t('storage.llmInput.allow')}
                </button>
                <button
                  className={`storage-llm-action-button button-loading-dot${
                    digestBusy ? ' is-loading' : ''
                  }`}
                  disabled={!object.llm_input_allowed || digestBusy}
                  onClick={() => void handleLlmDigest()}
                  type="button"
                >
                  {t('storage.llmDigest.button')}
                </button>
                <label className="storage-version-toolbar-select">
                  <span>{t('storage.version.selectLabel')}</span>
                  <select
                    onChange={(event) => setSelectedVersionId(event.target.value)}
                    value={selectedVersionId}
                  >
                    <option value="current">
                      {t('storage.version.currentOption', {
                        name: object.original_filename ?? object.id,
                      })}
                    </option>
                    {versions.map((version) => (
                      <option key={version.id} value={version.id}>
                        {t('storage.version.option', {
                          number: String(version.version_number),
                          name: version.original_filename ?? version.id,
                        })}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="storage-rename-row">
                <label>
                  <span>{t('storage.rename.label')}</span>
                  <input
                    onChange={(event) => setRenameDraft(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') {
                        event.preventDefault()
                        void handleRename(object)
                      }
                    }}
                    value={renameDraft}
                  />
                </label>
                <button
                  className={`button-loading-dot${renameBusy ? ' is-loading' : ''}`}
                  disabled={
                    renameBusy ||
                    renameDraft.trim() === '' ||
                    renameDraft.trim() === (object.original_filename ?? object.id)
                  }
                  onClick={() => void handleRename(object)}
                  type="button"
                >
                  {t('storage.rename.save')}
                </button>
              </div>
              <dl className="storage-detail-meta">
                <div>
                  <dt>{t('storage.version.timestamp')}</dt>
                  <dd>
                    {previewFile !== null
                      ? formatDateTime(previewFile.updated_at)
                      : t('time.unavailable')}
                  </dd>
                </div>
                <div>
                  <dt>{t('storage.size')}</dt>
                  <dd>
                    {previewFile !== null
                      ? formatBytes(previewFile.byte_size)
                      : t('time.unavailable')}
                  </dd>
                </div>
                <div>
                  <dt>{t('storage.contentType')}</dt>
                  <dd>{previewFile?.content_type ?? t('common.none')}</dd>
                </div>
                <div>
                  <dt>{t('storage.llmInput.label')}</dt>
                  <dd>
                    {object.llm_input_allowed
                      ? t('storage.llmInput.allowed')
                      : t('storage.llmInput.blocked')}
                  </dd>
                </div>
                <div>
                  <dt>{t('storage.source.label')}</dt>
                  <dd>{storageSourceLabel(object)}</dd>
                </div>
              </dl>
              {object.source_mail !== undefined && object.source_mail !== null && (
                <StorageSourceMailCard mail={object.source_mail} />
              )}
              <section className="storage-linked-cases-card">
                <div className="section-heading">
                  <div>
                    <h2>{t('storage.linkedCases.heading')}</h2>
                    <p>{t('storage.linkedCases.body')}</p>
                  </div>
                  <button
                    aria-pressed={isLinkedCasesEditing}
                    className="storage-linked-cases-settings-button"
                    onClick={() => setIsLinkedCasesEditing((current) => !current)}
                    type="button"
                  >
                    <img alt="" src={settingsGearIconUrl} />
                  </button>
                </div>
                <div className="storage-linked-cases-path">
                  <span>{t('storage.linkedCases.physicalPath')}</span>
                  <AppLink href={object.physical_directory_url ?? '/storage?directory=root'}>
                    {directoryPathLabel(object.physical_directory_path ?? object.directory_path)}
                  </AppLink>
                </div>
                {isLinkedCasesEditing && (
                  <div className="storage-linked-cases-editor">
                    <label>
                      <span>{t('storage.linkedCases.caseName')}</span>
                      <SuggestInput
                        ariaLabel={t('storage.linkedCases.caseName')}
                        maxItems={1}
                        onChange={setLinkedCaseInput}
                        options={caseSuggestions.map((item) => ({
                          key: item.id,
                          value: item.name,
                          label: item.name,
                          badgeLabel: item.name,
                        }))}
                        placeholder={t('storage.linkedCases.placeholder')}
                        value={linkedCaseInput}
                      />
                    </label>
                    <button
                      className={`button-loading-dot${
                        linkedCasesBusy ? ' is-loading' : ''
                      }`}
                      disabled={linkedCasesBusy || selectedLinkedCaseCandidate() === null}
                      onClick={() => void handleAddLinkedCase()}
                      type="button"
                    >
                      {t('storage.linkedCases.add')}
                    </button>
                  </div>
                )}
                {linkedCasesStatus === 'loading' ? (
                  <p>{t('storage.linkedCases.loading')}</p>
                ) : linkedCasesStatus === 'failed' ? (
                  <p>{t('storage.linkedCases.failed')}</p>
                ) : linkedCases.length === 0 ? (
                  <p>{t('storage.linkedCases.empty')}</p>
                ) : (
                  <div className="storage-linked-cases-list">
                    {linkedCases.map((item) => (
                      <div className="storage-linked-case-item" key={item.case_id}>
                        <AppLink href={item.case_url}>{item.case_name}</AppLink>
                        <span>{linkedCaseSourceLabel(item.source)}</span>
                        {isLinkedCasesEditing && item.source !== 'physical' && (
                          <button
                            disabled={linkedCasesBusy}
                            onClick={() => void handleDeleteLinkedCase(item)}
                            type="button"
                          >
                            {t('storage.linkedCases.delete')}
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </section>
              <div
                className={`storage-file-preview storage-version-drop-zone button-loading-dot${
                  versionBusy ? ' is-loading' : ''
                }${isVersionDragOver ? ' is-drag-over' : ''}`}
                onDragEnter={(event) => {
                  event.preventDefault()
                  event.stopPropagation()
                  if (Array.from(event.dataTransfer.types).includes('Files')) {
                    setIsVersionDragOver(true)
                  }
                }}
                onDragOver={(event) => {
                  event.preventDefault()
                  event.stopPropagation()
                  if (Array.from(event.dataTransfer.types).includes('Files')) {
                    event.dataTransfer.dropEffect = 'copy'
                    setIsVersionDragOver(true)
                  }
                }}
                onDragLeave={(event) => {
                  event.preventDefault()
                  event.stopPropagation()
                  setIsVersionDragOver(false)
                }}
                onDrop={(event) => {
                  event.preventDefault()
                  event.stopPropagation()
                  setIsVersionDragOver(false)
                  const file = event.dataTransfer.files.item(0)
                  if (file !== null) void handleVersionDrop(file)
                }}
              >
                {isVersionDragOver && (
                  <div className="storage-version-drop-overlay">
                    <strong>{t('storage.version.dropHeading')}</strong>
                  </div>
                )}
                {previewFile === null ? (
                  <p>{t('storage.preview.unavailable')}</p>
                ) : isPreviewableImage(previewFile) ? (
                  <img
                    alt={previewFile.original_filename ?? t('storage.detail.file')}
                    className="storage-image-preview"
                    src={storageImagePreviewUrl({
                      contentType: previewFile.content_type,
                      filename: previewFile.original_filename,
                      url: previewFile.url,
                    })}
                  />
                ) : isPreviewablePdf(previewFile) ? (
                  <iframe
                    className="storage-pdf-preview"
                    src={previewFile.url}
                    title={previewFile.original_filename ?? t('storage.detail.file')}
                  />
                ) : isPreviewableVideo(previewFile) ? (
                  <video
                    className="storage-video-preview"
                    controls
                    preload="metadata"
                    src={previewFile.url}
                  >
                    {t('storage.preview.unavailable')}
                  </video>
                ) : isPreviewableZip(previewFile) ? (
                  <StorageArchivePreview
                    status={archiveTreeStatus}
                    text={archiveTreeText}
                  />
                ) : isPreviewableEml(previewFile) ? (
                  <StorageEmlPreviewCard
                    preview={emlPreview}
                    status={emlPreviewStatus}
                  />
                ) : isPreviewableMarkdown(previewFile) ? (
                  <StorageMarkdownPreview
                    status={textPreviewStatus}
                    text={textPreview}
                  />
                ) : isPreviewableDelimitedTable(previewFile) ? (
                  <StorageDelimitedTablePreview
                    filename={previewFile.original_filename}
                    partial={previewFile.byte_size > textPreviewByteLimit}
                    status={textPreviewStatus}
                    text={textPreview}
                  />
                ) : isPreviewableText(previewFile) ? (
                  <StorageTextPreview
                    status={textPreviewStatus}
                    text={textPreview}
                  />
                ) : (
                  <p>{t('storage.preview.unavailable')}</p>
                )}
              </div>
              <FileSummaryCard
                isStale={fileSummaryIsStale}
                staleReason={fileSummaryStaleReason}
                status={fileSummaryStatus}
                summary={fileSummary}
              />
              <FileVersionDiffCard diff={fileVersionDiff} />
            </>
          )}
        </section>
      </div>
    </main>
  )
}

function markdownInlineNodes(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = []
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\((?:https?:\/\/|mailto:)[^)]+\))/g
  let lastIndex = 0
  let match: RegExpExecArray | null
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index))
    }
    const token = match[0]
    const key = `${keyPrefix}-${match.index}`
    if (token.startsWith('`')) {
      nodes.push(<code key={key}>{token.slice(1, -1)}</code>)
    } else if (token.startsWith('**')) {
      nodes.push(<strong key={key}>{token.slice(2, -2)}</strong>)
    } else {
      const linkMatch = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(token)
      if (linkMatch === null) {
        nodes.push(token)
      } else {
        nodes.push(
          <a href={linkMatch[2]} key={key} rel="noreferrer" target="_blank">
            {linkMatch[1]}
          </a>,
        )
      }
    }
    lastIndex = pattern.lastIndex
  }
  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex))
  }
  return nodes
}

function renderMarkdownBlocks(text: string) {
  const lines = text.replace(/\r\n?/g, '\n').split('\n')
  const blocks: ReactNode[] = []
  let index = 0

  function isBlockStart(line: string) {
    return (
      /^#{1,6}\s+/.test(line) ||
      /^[-*_]{3,}\s*$/.test(line) ||
      /^>\s?/.test(line) ||
      /^[-*]\s+/.test(line) ||
      /^\d+\.\s+/.test(line) ||
      /^```/.test(line) ||
      isMarkdownTableStart(lines, index)
    )
  }

  while (index < lines.length) {
    const line = lines[index]
    if (line.trim() === '') {
      index += 1
      continue
    }

    if (line.startsWith('```')) {
      const codeLines: string[] = []
      index += 1
      while (index < lines.length && !lines[index].startsWith('```')) {
        codeLines.push(lines[index])
        index += 1
      }
      if (index < lines.length) index += 1
      blocks.push(
        <pre className="storage-markdown-code" key={`code-${index}`}>
          <code>{codeLines.join('\n')}</code>
        </pre>,
      )
      continue
    }

    if (isMarkdownTableStart(lines, index)) {
      const headerCells = splitMarkdownTableRow(lines[index])
      index += 2
      const rows: string[][] = []
      while (index < lines.length && splitMarkdownTableRow(lines[index]).length > 1) {
        rows.push(splitMarkdownTableRow(lines[index]))
        index += 1
      }
      blocks.push(
        <div className="storage-markdown-table-wrap" key={`table-${index}`}>
          <table>
            <thead>
              <tr>
                {headerCells.map((cell, cellIndex) => (
                  <th key={`table-${index}-head-${cellIndex}`} scope="col">
                    {markdownInlineNodes(cell, `table-${index}-head-${cellIndex}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={`table-${index}-row-${rowIndex}`}>
                  {headerCells.map((_, cellIndex) => (
                    <td key={`table-${index}-row-${rowIndex}-${cellIndex}`}>
                      {markdownInlineNodes(
                        row[cellIndex] ?? '',
                        `table-${index}-row-${rowIndex}-${cellIndex}`,
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      )
      continue
    }

    const headingMatch = /^(#{1,6})\s+(.+)$/.exec(line)
    if (headingMatch !== null) {
      const level = headingMatch[1].length
      const content = markdownInlineNodes(headingMatch[2], `heading-${index}`)
      const key = `heading-${index}`
      if (level === 1) blocks.push(<h2 key={key}>{content}</h2>)
      else if (level === 2) blocks.push(<h3 key={key}>{content}</h3>)
      else if (level === 3) blocks.push(<h4 key={key}>{content}</h4>)
      else if (level === 4) blocks.push(<h5 key={key}>{content}</h5>)
      else blocks.push(<h6 key={key}>{content}</h6>)
      index += 1
      continue
    }

    if (/^[-*_]{3,}\s*$/.test(line)) {
      blocks.push(<hr key={`hr-${index}`} />)
      index += 1
      continue
    }

    if (/^>\s?/.test(line)) {
      const quoteLines: string[] = []
      while (index < lines.length && /^>\s?/.test(lines[index])) {
        quoteLines.push(lines[index].replace(/^>\s?/, ''))
        index += 1
      }
      blocks.push(
        <blockquote key={`quote-${index}`}>
          {quoteLines.map((quoteLine, quoteIndex) => (
            <Fragment key={`quote-${index}-${quoteIndex}`}>
              {quoteIndex > 0 && <br />}
              {markdownInlineNodes(quoteLine, `quote-${index}-${quoteIndex}`)}
            </Fragment>
          ))}
        </blockquote>,
      )
      continue
    }

    if (/^[-*]\s+/.test(line)) {
      const items: string[] = []
      while (index < lines.length && /^[-*]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^[-*]\s+/, ''))
        index += 1
      }
      blocks.push(
        <ul key={`ul-${index}`}>
          {items.map((item, itemIndex) => (
            <li key={`ul-${index}-${itemIndex}`}>
              {markdownInlineNodes(item, `ul-${index}-${itemIndex}`)}
            </li>
          ))}
        </ul>,
      )
      continue
    }

    if (/^\d+\.\s+/.test(line)) {
      const items: string[] = []
      while (index < lines.length && /^\d+\.\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\d+\.\s+/, ''))
        index += 1
      }
      blocks.push(
        <ol key={`ol-${index}`}>
          {items.map((item, itemIndex) => (
            <li key={`ol-${index}-${itemIndex}`}>
              {markdownInlineNodes(item, `ol-${index}-${itemIndex}`)}
            </li>
          ))}
        </ol>,
      )
      continue
    }

    const paragraphLines: string[] = []
    while (
      index < lines.length &&
      lines[index].trim() !== '' &&
      !isBlockStart(lines[index])
    ) {
      paragraphLines.push(lines[index])
      index += 1
    }
    const paragraphText = paragraphLines.join(' ')
    blocks.push(
      <p key={`p-${index}`}>
        {markdownInlineNodes(paragraphText, `p-${index}`)}
      </p>,
    )
  }

  return blocks
}

function isMarkdownTableStart(lines: string[], index: number) {
  const headerCells = splitMarkdownTableRow(lines[index] ?? '')
  const separatorCells = splitMarkdownTableRow(lines[index + 1] ?? '')
  return (
    headerCells.length > 1 &&
    separatorCells.length === headerCells.length &&
    separatorCells.every((cell) => /^:?-{3,}:?$/.test(cell.trim()))
  )
}

function splitMarkdownTableRow(line: string) {
  const trimmed = line.trim()
  if (!trimmed.includes('|')) {
    return []
  }

  const withoutOuterPipes = trimmed.replace(/^\|/, '').replace(/\|$/, '')
  return withoutOuterPipes.split('|').map((cell) => cell.trim())
}

function StorageMarkdownPreview({
  status,
  text,
}: {
  status: 'idle' | 'loading' | 'loaded' | 'too-large' | 'failed'
  text: string | null
}) {
  if (status === 'loading') {
    return <p>{t('storage.preview.textLoading')}</p>
  }
  if (status === 'too-large') {
    return <p>{t('storage.preview.textTooLarge')}</p>
  }
  if (status === 'failed') {
    return <p>{t('storage.preview.textFailed')}</p>
  }
  if (status === 'loaded') {
    return (
      <article className="storage-markdown-preview">
        {renderMarkdownBlocks(text ?? '')}
      </article>
    )
  }
  return <p>{t('storage.preview.unavailable')}</p>
}

function parseDelimitedTable(text: string, delimiter: ',' | '\t') {
  const rows: string[][] = []
  let row: string[] = []
  let cell = ''
  let inQuotes = false
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index]
    if (inQuotes) {
      if (char === '"') {
        if (text[index + 1] === '"') {
          cell += '"'
          index += 1
        } else {
          inQuotes = false
        }
      } else {
        cell += char
      }
      continue
    }

    if (char === '"') {
      inQuotes = true
    } else if (char === delimiter) {
      row.push(cell)
      cell = ''
    } else if (char === '\n') {
      row.push(cell)
      rows.push(row)
      row = []
      cell = ''
    } else if (char !== '\r') {
      cell += char
    }
  }
  row.push(cell)
  if (row.some((value) => value !== '') || rows.length === 0) {
    rows.push(row)
  }
  return rows
}

function StorageDelimitedTablePreview({
  filename,
  partial,
  status,
  text,
}: {
  filename: string | null
  partial: boolean
  status: 'idle' | 'loading' | 'loaded' | 'too-large' | 'failed'
  text: string | null
}) {
  if (status === 'loading') {
    return <p>{t('storage.preview.textLoading')}</p>
  }
  if (status === 'too-large') {
    return <p>{t('storage.preview.textTooLarge')}</p>
  }
  if (status === 'failed') {
    return <p>{t('storage.preview.textFailed')}</p>
  }
  if (status !== 'loaded') {
    return <p>{t('storage.preview.unavailable')}</p>
  }

  const delimiter = fileExtension(filename) === 'tsv' ? '\t' : ','
  const rows = parseDelimitedTable(text ?? '', delimiter)
  const visibleRows = rows.slice(0, 200)
  const maxColumns = Math.min(50, Math.max(...visibleRows.map((row) => row.length), 0))
  const isTruncated = rows.length > visibleRows.length || rows.some((row) => row.length > maxColumns)

  return (
    <div className="storage-table-preview">
      <table>
        <tbody>
          {visibleRows.map((row, rowIndex) => (
            <tr key={`row-${rowIndex}`}>
              <th className="storage-table-row-number" scope="row">
                {rowIndex + 1}
              </th>
              {Array.from({ length: maxColumns }).map((_, columnIndex) => (
                <td key={`cell-${rowIndex}-${columnIndex}`}>
                  {row[columnIndex] ?? ''}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {partial && (
        <p className="storage-table-preview-note">
          {t('storage.preview.tablePartial')}
        </p>
      )}
      {isTruncated && (
        <p className="storage-table-preview-note">
          {t('storage.preview.tableTruncated')}
        </p>
      )}
    </div>
  )
}

function StorageTextPreview({
  status,
  text,
}: {
  status: 'idle' | 'loading' | 'loaded' | 'too-large' | 'failed'
  text: string | null
}) {
  if (status === 'loading') {
    return <p>{t('storage.preview.textLoading')}</p>
  }
  if (status === 'too-large') {
    return <p>{t('storage.preview.textTooLarge')}</p>
  }
  if (status === 'failed') {
    return <p>{t('storage.preview.textFailed')}</p>
  }
  if (status === 'loaded') {
    return (
      <pre className="storage-text-preview">
        <code>{text ?? ''}</code>
      </pre>
    )
  }
  return <p>{t('storage.preview.unavailable')}</p>
}

function StorageArchivePreview({
  status,
  text,
}: {
  status: 'idle' | 'loading' | 'loaded' | 'failed'
  text: string | null
}) {
  if (status === 'loading') {
    return <p>{t('storage.preview.archiveLoading')}</p>
  }
  if (status === 'failed') {
    return <p>{t('storage.preview.archiveFailed')}</p>
  }
  if (status === 'loaded') {
    return (
      <pre className="storage-text-preview">
        <code>{text ?? ''}</code>
      </pre>
    )
  }
  return <p>{t('storage.preview.unavailable')}</p>
}

function StorageEmlPreviewCard({
  preview,
  status,
}: {
  preview: StorageEmlPreview | null
  status: 'idle' | 'loading' | 'loaded' | 'failed'
}) {
  if (status === 'loading') {
    return <p>{t('storage.eml.loading')}</p>
  }
  if (status === 'failed') {
    return <p>{t('storage.eml.failed')}</p>
  }
  if (status !== 'loaded' || preview === null) {
    return <p>{t('storage.preview.unavailable')}</p>
  }
  const metaItems = [
    [t('storage.eml.to'), preview.to],
    [t('storage.eml.cc'), preview.cc],
    [t('storage.eml.replyTo'), preview.reply_to],
    [t('storage.eml.date'), preview.date],
    [t('storage.eml.messageId'), preview.message_id],
  ].filter(([, value]) => value !== null && value !== '')
  const senderLabel = preview.from ?? t('storage.eml.heading')
  const senderContact = preview.sender_contact
  return (
    <div className="storage-eml-preview mail-thread-item mail-thread-item-received">
      <aside className="mail-thread-sender-card storage-eml-sender-card">
        {senderContact?.avatar_url ? (
          <img
            alt=""
            className="storage-eml-sender-avatar"
            src={senderContact.avatar_url}
          />
        ) : (
          <span aria-hidden="true" className="storage-eml-sender-initial">
            {senderLabel.trim().charAt(0).toUpperCase()}
          </span>
        )}
        <strong>{senderLabel}</strong>
        <span>
          <small>{senderContact?.display_name ?? t('storage.eml.heading')}</small>
        </span>
      </aside>
      <article className="mail-panel mail-thread-message storage-eml-message">
        <header>
          <div>
            <span>{preview.date ?? t('time.unavailable')}</span>
            <h2>{preview.subject ?? t('mail.noSubject')}</h2>
          </div>
        </header>
        {metaItems.length > 0 && (
          <details className="mail-thread-head-details storage-eml-head-details">
            <summary>{t('mail.thread.head')}</summary>
            <div className="mail-thread-head">
              <dl className="mail-thread-meta storage-eml-meta">
                <div>
                  <dt>{t('storage.eml.from')}</dt>
                  <dd>{preview.from ?? t('common.none')}</dd>
                </div>
                {metaItems.map(([label, value]) => (
                  <div key={label}>
                    <dt>{label}</dt>
                    <dd>{value}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </details>
        )}
        {preview.body_html !== null && preview.body_html.trim() !== '' ? (
          <iframe
            className="mail-thread-html-body storage-eml-html-body"
            sandbox=""
            srcDoc={preview.body_html}
            title={preview.subject ?? t('storage.eml.heading')}
          />
        ) : (
          <pre className="mail-thread-body storage-eml-text-body">
            {preview.body_text ?? t('storage.eml.noBody')}
          </pre>
        )}
        {preview.attachments.length > 0 && (
          <section className="mail-thread-section storage-eml-attachments">
            <h3>{t('storage.eml.attachments')}</h3>
            <div className="mail-attachment-badges">
              {preview.attachments.map((attachment, index) => (
                <span className="mail-attachment-badge" key={`${attachment.filename}-${index}`}>
                  <span>{attachment.filename}</span>
                  <small>{formatBytes(attachment.byte_size)}</small>
                </span>
              ))}
            </div>
          </section>
        )}
      </article>
    </div>
  )
}

function FileSummaryCard({
  isStale,
  staleReason,
  summary,
  status,
}: {
  isStale: boolean
  staleReason: string | null
  summary: FileSummary | null
  status: 'idle' | 'loading' | 'loaded' | 'missing' | 'failed'
}) {
  return (
    <section className="storage-file-summary-card">
      <div className="section-heading">
        <div>
          <h2>{t('storage.llmDigest.cardHeading')}</h2>
        </div>
      </div>
      {status === 'loading' && <p>{t('storage.llmDigest.loading')}</p>}
      {status === 'failed' && <p>{t('storage.llmDigest.loadFailed')}</p>}
      {(status === 'idle' || status === 'missing') && (
        <p>{t('storage.llmDigest.empty')}</p>
      )}
      {summary !== null && (
        <div className="storage-file-summary-content">
          {isStale && (
            <p className="storage-file-summary-stale" title={staleReason ?? undefined}>
              {t('storage.llmDigest.stale')}
            </p>
          )}
          <p className="storage-file-description">{summary.file_description}</p>
          {summary.summary_points.length > 0 ? (
            <ul>
              {summary.summary_points.slice(0, 5).map((point, index) => (
                <li key={`${summary.id}-${index}`}>{point}</li>
              ))}
            </ul>
          ) : (
            <p>{t('storage.llmDigest.noSummaryPoints')}</p>
          )}
        </div>
      )}
    </section>
  )
}

function FileVersionDiffCard({ diff }: { diff: FileVersionDiff | null }) {
  const [isOpen, setIsOpen] = useState(false)
  if (diff === null) {
    return null
  }
  return (
    <section className="storage-file-summary-card storage-file-diff-card">
      <button
        aria-expanded={isOpen}
        className="storage-file-diff-toggle"
        onClick={() => setIsOpen((current) => !current)}
        type="button"
      >
        <div>
          <h2>{t('storage.diff.cardHeading')}</h2>
          <p>{diff.summary_text}</p>
        </div>
        <span>{isOpen ? '-' : '+'}</span>
      </button>
      {isOpen && diff.display_lines.length > 0 ? (
        <pre className="storage-file-diff-view">
          {diff.display_lines.map((line, index) => (
            <code
              className={`storage-file-diff-line is-${line.kind}`}
              key={`${diff.id}-display-${index}`}
            >
              <span>
                {line.kind === 'added'
                  ? '+'
                  : line.kind === 'removed'
                    ? '-'
                    : line.kind === 'ellipsis'
                      ? '...'
                      : ' '}
              </span>
              {line.text}
            </code>
          ))}
        </pre>
      ) : isOpen ? (
        <p className="storage-file-diff-empty">{t('storage.diff.none')}</p>
      ) : null}
    </section>
  )
}

function StorageListBrowserView() {
  const [currentDirectoryId, setCurrentDirectoryId] = useState<string | null>(
    directoryIdFromLocation,
  )
  const [searchQuery, setSearchQuery] = useState('')
  const [sortMode, setSortMode] = useState<'created_desc' | 'created_asc' | 'name'>(
    'created_desc',
  )
  const [extensionFilter, setExtensionFilter] = useState<string | null>(null)
  const [availableExtensions, setAvailableExtensions] = useState<string[]>([])

  useEffect(() => {
    const syncDirectoryFromLocation = () => setCurrentDirectoryId(directoryIdFromLocation())
    window.addEventListener('popstate', syncDirectoryFromLocation)
    return () => window.removeEventListener('popstate', syncDirectoryFromLocation)
  }, [])

  function updateDirectoryLocation(directoryId: string | null) {
    setCurrentDirectoryId(directoryId)
    if (directoryId === null) {
      navigateTo('/files')
      return
    }
    navigateTo(`/files?directory=${encodeURIComponent(directoryId)}`)
  }

  return (
    <main className="app-shell">
      <div className="mail-shell storage-shell">
        <header className="maintenance-header">
          <div>
            <p>{t('app.name')}</p>
            <h1>{t('storage.heading')}</h1>
          </div>
          <TopNav
            ariaLabelKey="storage.navigation"
            items={[
              { href: '/', labelKey: 'top.heading' },
              { href: '/cases', labelKey: 'nav.cases' },
              { href: '/tasks', labelKey: 'nav.tasks' },
              { href: '/mail', labelKey: 'nav.mail' },
              { href: '/maintenance', labelKey: 'nav.maintenance' },
            ]}
          />
        </header>

        <StorageBrowser
          body={t('storage.objectsBody')}
          currentDirectoryId={currentDirectoryId}
          extensionFilter={extensionFilter}
          extraHeadingActions={
            <AppLink
              aria-label={t('storage.fileIcons.configure')}
              className="case-icon-button"
              href="/file-icons"
              title={t('storage.fileIcons.configure')}
            >
              <img alt="" aria-hidden="true" src={settingsGearIconUrl} />
            </AppLink>
          }
          heading={t('storage.objects')}
          onAvailableExtensionsChange={setAvailableExtensions}
          onDirectoryChange={updateDirectoryLocation}
          onOpenObject={(object) => navigateTo(`/files/${encodeURIComponent(object.id)}`)}
          panelClassName="mail-panel storage-objects-panel"
          renderTopTools={({
            breadcrumbs,
            openRootDirectory,
            openDirectory,
            onDirectoryDragOver,
            onDirectoryDrop,
          }) => {
            const caseDirectory = breadcrumbs.find((directory) => directory.case_id !== null)
            return (
              <div className="storage-top-tools">
                <section className="storage-path-card" aria-label={t('storage.directory.path')}>
                  <div className="storage-path-heading">
                    <h3>{t('storage.directory.path')}</h3>
                    {caseDirectory?.case_id ? (
                      <AppLink
                        className="storage-path-case-link"
                        href={`/cases/${encodeURIComponent(caseDirectory.case_id)}`}
                      >
                        {t('storage.directory.openCase')}
                      </AppLink>
                    ) : null}
                  </div>
                  <nav aria-label={t('storage.directory.breadcrumb')} className="storage-breadcrumb">
                    <button
                      onClick={openRootDirectory}
                      onDragOver={onDirectoryDragOver}
                      onDrop={(event) => onDirectoryDrop(event, null)}
                      type="button"
                    >
                      {t('storage.directory.root')}
                    </button>
                    {breadcrumbs.map((directory) => (
                      <button
                        key={directory.id}
                        onClick={() => openDirectory(directory)}
                        onDragOver={onDirectoryDragOver}
                        onDrop={(event) => onDirectoryDrop(event, directory.id)}
                        type="button"
                      >
                        {directory.name}
                      </button>
                    ))}
                  </nav>
                </section>
              <section className="storage-search-tools" aria-label={t('storage.search.region')}>
                <div aria-label={t('storage.search.region')} role="search">
                  <label>
                    <span>{t('storage.search.label')}</span>
                    <input
                      aria-label={t('storage.search.label')}
                      onChange={(event) => setSearchQuery(event.target.value)}
                      placeholder={t('storage.search.placeholder')}
                      type="search"
                      value={searchQuery}
                    />
                  </label>
                </div>
                <label className="storage-sort-control">
                  <span>{t('storage.sort.label')}</span>
                  <select
                    aria-label={t('storage.sort.aria')}
                    onChange={(event) =>
                      setSortMode(event.target.value as 'created_desc' | 'created_asc' | 'name')
                    }
                    value={sortMode}
                  >
                    <option value="created_desc">{t('storage.sort.createdDesc')}</option>
                    <option value="created_asc">{t('storage.sort.createdAsc')}</option>
                    <option value="name">{t('storage.sort.name')}</option>
                  </select>
                </label>
                <div className="storage-extension-filters" aria-label={t('storage.extension.label')}>
                  <button
                    aria-pressed={extensionFilter === null}
                    onClick={() => setExtensionFilter(null)}
                    type="button"
                  >
                    {t('common.all')}
                  </button>
                  {availableExtensions.map((extension) => (
                    <button
                      aria-pressed={extensionFilter === extension}
                      key={extension}
                      onClick={() =>
                        setExtensionFilter((current) => (current === extension ? null : extension))
                      }
                      type="button"
                    >
                      .{extension}
                    </button>
                  ))}
                </div>
              </section>
              </div>
            )
          }}
          rootDirectoryId={null}
          rootLabel={t('storage.directory.root')}
          searchQuery={searchQuery}
          showBreadcrumb={false}
          sortMode={sortMode}
        />
      </div>
    </main>
  )
}

function StorageListView() {
  return <StorageListBrowserView />
}

export default function StorageView({ storageObjectId }: { storageObjectId?: string } = {}) {
  if (storageObjectId !== undefined) {
    return <StorageObjectDetailView storageObjectId={storageObjectId} />
  }
  return <StorageListView />
}
