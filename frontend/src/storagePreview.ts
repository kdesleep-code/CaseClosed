export const previewableImageExtensions = [
  'apng',
  'avif',
  'bmp',
  'gif',
  'heic',
  'heif',
  'ico',
  'jpg',
  'jpeg',
  'png',
  'svg',
  'webp',
] as const

export const previewableTextExtensions = [
  'bat',
  'bib',
  'c',
  'cc',
  'cfg',
  'cmd',
  'conf',
  'cpp',
  'cs',
  'css',
  'csv',
  'env',
  'go',
  'h',
  'hpp',
  'htm',
  'html',
  'ini',
  'java',
  'js',
  'json',
  'jsonl',
  'jsx',
  'log',
  'm',
  'markdown',
  'md',
  'ps1',
  'py',
  'r',
  'rb',
  'rs',
  'sh',
  'sql',
  'tex',
  'toml',
  'ts',
  'tsx',
  'tsv',
  'txt',
  'xml',
  'yaml',
  'yml',
] as const

const blockedImageContentTypes = new Set([
  'image/tiff',
  'image/x-tiff',
])

const textContentTypes = new Set([
  'application/javascript',
  'application/json',
  'application/ld+json',
  'application/sql',
  'application/toml',
  'application/typescript',
  'application/xml',
  'application/x-sh',
  'application/x-yaml',
  'image/svg+xml',
])

export function fileExtension(filename: string | null) {
  if (filename === null || filename.trim() === '') {
    return 'file'
  }
  const parts = filename.split('.')
  return parts.length > 1 ? parts.at(-1)?.toLowerCase() ?? 'file' : 'file'
}

export function isPreviewableImageFile({
  contentType,
  filename,
}: {
  contentType: string | null
  filename: string | null
}) {
  const normalizedContentType = contentType?.toLowerCase().split(';', 1)[0].trim()
  if (
    normalizedContentType !== undefined &&
    blockedImageContentTypes.has(normalizedContentType)
  ) {
    return false
  }
  if (normalizedContentType?.startsWith('image/')) {
    return true
  }
  return previewableImageExtensions.includes(
    fileExtension(filename) as (typeof previewableImageExtensions)[number],
  )
}

export function storageImagePreviewUrl({
  contentType,
  filename,
  url,
}: {
  contentType: string | null
  filename: string | null
  url: string
}) {
  const normalizedContentType = contentType?.toLowerCase().split(';', 1)[0].trim()
  const requiresConversion =
    normalizedContentType === 'image/heic' ||
    normalizedContentType === 'image/heic-sequence' ||
    normalizedContentType === 'image/heif' ||
    normalizedContentType === 'image/heif-sequence' ||
    fileExtension(filename) === 'heic' ||
    fileExtension(filename) === 'heif'
  if (!requiresConversion) return url

  const [path, query] = url.split('?', 2)
  if (!path.endsWith('/content')) return url
  return `${path.slice(0, -'/content'.length)}/image-preview${query ? `?${query}` : ''}`
}

export function isPreviewableTextFile({
  contentType,
  filename,
}: {
  contentType: string | null
  filename: string | null
}) {
  const normalizedContentType = contentType?.toLowerCase().split(';', 1)[0].trim()
  if (
    normalizedContentType?.startsWith('text/') ||
    (normalizedContentType !== undefined && textContentTypes.has(normalizedContentType))
  ) {
    return true
  }
  return previewableTextExtensions.includes(
    fileExtension(filename) as (typeof previewableTextExtensions)[number],
  )
}

export function isPreviewablePdfFile({
  contentType,
  filename,
}: {
  contentType: string | null
  filename: string | null
}) {
  const normalizedContentType = contentType?.toLowerCase().split(';', 1)[0].trim()
  return normalizedContentType === 'application/pdf' || fileExtension(filename) === 'pdf'
}

export function isPreviewableVideoFile({
  contentType,
  filename,
}: {
  contentType: string | null
  filename: string | null
}) {
  const normalizedContentType = contentType?.toLowerCase().split(';', 1)[0].trim()
  return normalizedContentType === 'video/mp4' || fileExtension(filename) === 'mp4'
}

export function isPreviewableMarkdownFile({
  contentType,
  filename,
}: {
  contentType: string | null
  filename: string | null
}) {
  const normalizedContentType = contentType?.toLowerCase().split(';', 1)[0].trim()
  const extension = fileExtension(filename)
  return (
    normalizedContentType === 'text/markdown' ||
    extension === 'md' ||
    extension === 'markdown'
  )
}

export function isPreviewableDelimitedTableFile({
  contentType,
  filename,
}: {
  contentType: string | null
  filename: string | null
}) {
  const normalizedContentType = contentType?.toLowerCase().split(';', 1)[0].trim()
  const extension = fileExtension(filename)
  return (
    normalizedContentType === 'text/csv' ||
    normalizedContentType === 'text/tab-separated-values' ||
    extension === 'csv' ||
    extension === 'tsv'
  )
}

export function isPreviewableZipFile({
  contentType,
  filename,
}: {
  contentType: string | null
  filename: string | null
}) {
  const normalizedContentType = contentType?.toLowerCase().split(';', 1)[0].trim()
  return (
    normalizedContentType === 'application/zip' ||
    normalizedContentType === 'application/x-zip-compressed' ||
    normalizedContentType === 'multipart/x-zip' ||
    fileExtension(filename) === 'zip'
  )
}

export function isPreviewableEmlFile({
  contentType,
  filename,
}: {
  contentType: string | null
  filename: string | null
}) {
  const normalizedContentType = contentType?.toLowerCase().split(';', 1)[0].trim()
  return (
    normalizedContentType === 'message/rfc822' ||
    normalizedContentType === 'application/eml' ||
    fileExtension(filename) === 'eml'
  )
}
