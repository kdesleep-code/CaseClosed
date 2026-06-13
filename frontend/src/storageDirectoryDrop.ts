import {
  createStorageDirectory,
  listStorageDirectories,
  uploadManagedStorageFile,
  type StorageDirectory,
} from './phase3Api'

type DroppedStorageFile = {
  file: File
  path: string[]
}

type BrowserFileSystemEntry = {
  isDirectory: boolean
  isFile: boolean
  name: string
}

type BrowserFileSystemFileEntry = BrowserFileSystemEntry & {
  file: (success: (file: File) => void, failure?: (error: DOMException) => void) => void
}

type BrowserFileSystemDirectoryEntry = BrowserFileSystemEntry & {
  createReader: () => BrowserFileSystemDirectoryReader
}

type BrowserFileSystemDirectoryReader = {
  readEntries: (
    success: (entries: BrowserFileSystemEntry[]) => void,
    failure?: (error: DOMException) => void,
  ) => void
}

type BrowserDataTransferItem = DataTransferItem & {
  webkitGetAsEntry?: () => BrowserFileSystemEntry | null
}

function isFileEntry(entry: BrowserFileSystemEntry): entry is BrowserFileSystemFileEntry {
  return entry.isFile
}

function isDirectoryEntry(entry: BrowserFileSystemEntry): entry is BrowserFileSystemDirectoryEntry {
  return entry.isDirectory
}

function entryFile(entry: BrowserFileSystemFileEntry): Promise<File> {
  return new Promise((resolve, reject) => {
    entry.file(resolve, reject)
  })
}

function readDirectoryEntries(
  reader: BrowserFileSystemDirectoryReader,
): Promise<BrowserFileSystemEntry[]> {
  return new Promise((resolve, reject) => {
    const entries: BrowserFileSystemEntry[] = []
    const readBatch = () => {
      reader.readEntries((batch) => {
        if (batch.length === 0) {
          resolve(entries)
          return
        }
        entries.push(...batch)
        readBatch()
      }, reject)
    }
    readBatch()
  })
}

async function collectEntryFiles(
  entry: BrowserFileSystemEntry,
  parentPath: string[],
): Promise<DroppedStorageFile[]> {
  if (isFileEntry(entry)) {
    return [{ file: await entryFile(entry), path: parentPath }]
  }
  if (!isDirectoryEntry(entry)) {
    return []
  }
  const childPath = [...parentPath, entry.name]
  const children = await readDirectoryEntries(entry.createReader())
  const nested = await Promise.all(
    children.map((child) => collectEntryFiles(child, childPath)),
  )
  return nested.flat()
}

export async function droppedStorageFilesFromDataTransfer(
  dataTransfer: DataTransfer,
): Promise<DroppedStorageFile[]> {
  const itemEntries: BrowserFileSystemEntry[] = []
  for (const item of Array.from(dataTransfer.items)) {
    const entry =
      (item as BrowserDataTransferItem).webkitGetAsEntry?.() ?? null
    if (entry !== null) {
      itemEntries.push(entry)
    }
  }

  if (itemEntries.length > 0) {
    const nested = await Promise.all(itemEntries.map((entry) => collectEntryFiles(entry, [])))
    return nested.flat()
  }

  return Array.from(dataTransfer.files).map((file) => ({
    file,
    path: [],
  }))
}

async function ensureChildDirectory(
  parentId: string | null,
  name: string,
): Promise<StorageDirectory> {
  const existing = await listStorageDirectories(parentId)
  const match = existing.items.find((directory) => directory.name === name)
  if (match !== undefined) {
    return match
  }
  try {
    const created = await createStorageDirectory({ name, parent_id: parentId })
    return created.directory
  } catch (error) {
    const refreshed = await listStorageDirectories(parentId)
    const refreshedMatch = refreshed.items.find((directory) => directory.name === name)
    if (refreshedMatch !== undefined) {
      return refreshedMatch
    }
    throw error
  }
}

async function ensureDirectoryPath(
  rootDirectoryId: string | null,
  path: string[],
  cache: Map<string, StorageDirectory>,
): Promise<string | null> {
  let directoryId = rootDirectoryId
  for (const name of path) {
    const key = `${directoryId ?? 'root'}\u0000${name}`
    let directory = cache.get(key)
    if (directory === undefined) {
      directory = await ensureChildDirectory(directoryId, name)
      cache.set(key, directory)
    }
    directoryId = directory.id
  }
  return directoryId
}

export async function uploadDroppedStorageFiles(
  files: DroppedStorageFile[],
  rootDirectoryId: string | null,
): Promise<{ count: number; lastUploadedName: string }> {
  const directoryCache = new Map<string, StorageDirectory>()
  let lastUploadedName = ''
  for (const item of files) {
    const directoryId = await ensureDirectoryPath(rootDirectoryId, item.path, directoryCache)
    const response = await uploadManagedStorageFile(item.file, directoryId)
    lastUploadedName = response.storage_object.original_filename ?? response.storage_object.id
  }
  return { count: files.length, lastUploadedName }
}
