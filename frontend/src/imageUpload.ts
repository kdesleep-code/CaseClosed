export const imageUploadAccept =
  'image/png,image/jpeg,image/gif,image/webp,image/svg+xml,image/heic,image/heif,.heic,.heif'

export function imageUploadContentType(file: File) {
  if (file.type.trim() !== '') return file.type
  if (/\.heic$/i.test(file.name)) return 'image/heic'
  if (/\.heif$/i.test(file.name)) return 'image/heif'
  return 'application/octet-stream'
}
