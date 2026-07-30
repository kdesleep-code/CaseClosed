import { describe, expect, it } from 'vitest'
import { isPreviewableImageFile, storageImagePreviewUrl } from './storagePreview'

describe('Storage image previews', () => {
  it('routes HEIC content through the server-side image preview', () => {
    expect(
      storageImagePreviewUrl({
        contentType: 'image/heic',
        filename: 'photo.heic',
        url: '/api/v1/storage/objects/object-1/content?v=sha',
      }),
    ).toBe('/api/v1/storage/objects/object-1/image-preview?v=sha')
  })

  it('recognizes a HEIF filename when the browser supplies a generic content type', () => {
    expect(
      isPreviewableImageFile({
        contentType: 'application/octet-stream',
        filename: 'photo.HEIF',
      }),
    ).toBe(true)
    expect(
      storageImagePreviewUrl({
        contentType: 'application/octet-stream',
        filename: 'photo.HEIF',
        url: '/api/v1/storage/objects/object-1/versions/version-1/content?v=sha',
      }),
    ).toBe(
      '/api/v1/storage/objects/object-1/versions/version-1/image-preview?v=sha',
    )
  })

  it('keeps browser-native image URLs unchanged', () => {
    const url = '/api/v1/storage/objects/object-1/content?v=sha'
    expect(
      storageImagePreviewUrl({
        contentType: 'image/png',
        filename: 'photo.png',
        url,
      }),
    ).toBe(url)
  })
})
