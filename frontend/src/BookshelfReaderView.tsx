import { useEffect, useRef, useState } from 'react'
import type { MouseEvent } from 'react'
import * as pdfjsLib from 'pdfjs-dist'
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.mjs?url'
import type { PDFDocumentProxy, PDFPageProxy } from 'pdfjs-dist'
import { getStorageObject } from './phase3Api'
import type { StorageObject } from './phase3Api'
import { t } from './i18n'
import { navigateTo, TopNav } from './navigation'

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl

type RenderTask = { cancel: () => void; promise: Promise<unknown> }
type TextLayerTask = InstanceType<typeof pdfjsLib.TextLayer>

function bookshelfContentUrl(storageObjectId: string) {
  return `/api/v1/storage/objects/${encodeURIComponent(storageObjectId)}/content`
}

function pdfPageKey(storageObjectId: string) {
  return `caseclosed.bookshelf.reader.pdfPage.${storageObjectId}`
}

function displayTitle(storageObject: StorageObject | null) {
  const filename = storageObject?.original_filename?.trim()
  return filename === undefined || filename === '' ? t('bookshelf.reader.heading') : filename.replace(/\.pdf$/i, '')
}

function isExpectedPdfCancellation(error: unknown) {
  if (!(error instanceof Error)) return false
  const message = error.message.toLowerCase()
  return (
    error.name === 'AbortException'
    || error.name === 'RenderingCancelledException'
    || message.includes('loading aborted')
    || message.includes('aborted')
    || message.includes('cancelled')
  )
}

function spreadStartForPage(pageNumber: number) {
  return Math.max(1, pageNumber % 2 === 0 ? pageNumber - 1 : pageNumber)
}

function textContentToString(textContent: Awaited<ReturnType<PDFPageProxy['getTextContent']>>) {
  return textContent.items
    .map((item) => ('str' in item && typeof item.str === 'string' ? item.str : ''))
    .join(' ')
    .replace(/\s+/g, ' ')
    .trim()
}

export default function BookshelfReaderView({ storageObjectId }: { storageObjectId: string }) {
  const leftPageRef = useRef<HTMLDivElement | null>(null)
  const rightPageRef = useRef<HTMLDivElement | null>(null)
  const leftCanvasRef = useRef<HTMLCanvasElement | null>(null)
  const rightCanvasRef = useRef<HTMLCanvasElement | null>(null)
  const leftTextLayerRef = useRef<HTMLDivElement | null>(null)
  const rightTextLayerRef = useRef<HTMLDivElement | null>(null)
  const pdfRef = useRef<PDFDocumentProxy | null>(null)
  const renderTasksRef = useRef<RenderTask[]>([])
  const textLayerTasksRef = useRef<TextLayerTask[]>([])
  const [storageObject, setStorageObject] = useState<StorageObject | null>(null)
  const [pdfPageNumber, setPdfPageNumber] = useState(1)
  const [pdfPageCount, setPdfPageCount] = useState(0)
  const [pageTexts, setPageTexts] = useState<string[]>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [searchMatches, setSearchMatches] = useState<number[]>([])
  const [selectedSearchIndex, setSelectedSearchIndex] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isReady, setIsReady] = useState(false)
  const [isIndexing, setIsIndexing] = useState(false)

  const title = displayTitle(storageObject)

  useEffect(() => {
    setIsLoading(true)
    setIsReady(false)
    setError(null)
    setStorageObject(null)
    setPageTexts([])
    setSearchQuery('')
    setSearchMatches([])
    getStorageObject(storageObjectId)
      .then((nextObject) => setStorageObject(nextObject))
      .catch((caught) => {
        setError(caught instanceof Error ? caught.message : t('app.requestFailed'))
        setIsLoading(false)
      })
  }, [storageObjectId])

  useEffect(() => {
    if (storageObject === null) return undefined
    let isCancelled = false
    setIsLoading(true)
    setIsReady(false)
    setError(null)
    setPdfPageCount(0)
    setPageTexts([])
    const savedPage = Number(window.localStorage.getItem(pdfPageKey(storageObjectId)) ?? '1')

    const loadingTask = pdfjsLib.getDocument({
      url: bookshelfContentUrl(storageObjectId),
      cMapUrl: '/pdfjs/cmaps/',
      cMapPacked: true,
      standardFontDataUrl: '/pdfjs/standard_fonts/',
    })
    loadingTask.promise
      .then((pdf) => {
        if (isCancelled) return
        pdfRef.current = pdf
        setPdfPageCount(pdf.numPages)
        setPdfPageNumber(spreadStartForPage(Math.min(Math.max(Number.isFinite(savedPage) ? savedPage : 1, 1), pdf.numPages)))
        setIsReady(true)
      })
      .catch((caught: unknown) => {
        if (isCancelled && isExpectedPdfCancellation(caught)) return
        setError(caught instanceof Error ? caught.message : t('app.requestFailed'))
      })
      .finally(() => {
        if (!isCancelled) setIsLoading(false)
      })

    return () => {
      isCancelled = true
      void loadingTask.destroy()
      renderTasksRef.current.forEach((task) => task.cancel())
      textLayerTasksRef.current.forEach((task) => task.cancel())
      renderTasksRef.current = []
      textLayerTasksRef.current = []
      pdfRef.current = null
    }
  }, [storageObject, storageObjectId])

  useEffect(() => {
    if (pdfRef.current === null || pdfPageCount === 0) return undefined
    let isCancelled = false
    const pdf = pdfRef.current
    setIsIndexing(true)
    Promise.all(Array.from({ length: pdfPageCount }, async (_, index) => {
      const page = await pdf.getPage(index + 1)
      const textContent = await page.getTextContent()
      return textContentToString(textContent)
    }))
      .then((texts) => {
        if (!isCancelled) setPageTexts(texts)
      })
      .catch((caught: unknown) => {
        if (!isExpectedPdfCancellation(caught)) {
          setError(caught instanceof Error ? caught.message : t('app.requestFailed'))
        }
      })
      .finally(() => {
        if (!isCancelled) setIsIndexing(false)
      })
    return () => {
      isCancelled = true
    }
  }, [pdfPageCount])

  useEffect(() => {
    const normalizedQuery = searchQuery.trim().toLowerCase()
    if (normalizedQuery === '') {
      setSearchMatches([])
      setSelectedSearchIndex(0)
      return
    }
    const nextMatches = pageTexts.flatMap((textValue, index) => (
      textValue.toLowerCase().includes(normalizedQuery) ? [index + 1] : []
    ))
    setSearchMatches(nextMatches)
    setSelectedSearchIndex(0)
    if (nextMatches.length > 0) {
      setPdfPageNumber(spreadStartForPage(nextMatches[0]))
    }
  }, [pageTexts, searchQuery])

  useEffect(() => {
    if (pdfRef.current === null || leftCanvasRef.current === null || pdfPageCount === 0) return undefined
    let isCancelled = false
    const leftCanvas = leftCanvasRef.current
    const rightCanvas = rightCanvasRef.current
    const leftPage = leftPageRef.current
    const rightPage = rightPageRef.current
    const leftTextLayer = leftTextLayerRef.current
    const rightTextLayer = rightTextLayerRef.current
    const container = leftPage?.parentElement

    renderTasksRef.current.forEach((task) => task.cancel())
    textLayerTasksRef.current.forEach((task) => task.cancel())
    renderTasksRef.current = []
    textLayerTasksRef.current = []

    function clearPage(pageElement: HTMLDivElement | null, canvas: HTMLCanvasElement | null, textLayer: HTMLDivElement | null) {
      if (pageElement !== null) {
        pageElement.style.display = 'none'
        pageElement.style.width = '0px'
        pageElement.style.height = '0px'
      }
      if (textLayer !== null) textLayer.replaceChildren()
      if (canvas === null) return
      const context = canvas.getContext('2d')
      if (context === null) return
      context.setTransform(1, 0, 0, 1, 0, 0)
      context.clearRect(0, 0, canvas.width, canvas.height)
      canvas.width = 1
      canvas.height = 1
      canvas.style.width = '0px'
      canvas.style.height = '0px'
    }

    const visiblePageNumbers = [pdfPageNumber, pdfPageNumber + 1].filter((pageNumber) => pageNumber <= pdfPageCount)
    Promise.all(visiblePageNumbers.map((pageNumber) => pdfRef.current?.getPage(pageNumber)))
      .then((pages) => {
        if (isCancelled) return undefined
        const validPages = pages.filter((page): page is PDFPageProxy => page !== undefined)
        const baseViewports = validPages.map((page) => page.getViewport({ scale: 1 }))
        const gap = validPages.length > 1 ? 24 : 0
        const availableWidth = Math.max(320, (container?.clientWidth ?? window.innerWidth) - 72)
        const availableHeight = Math.max(320, (container?.clientHeight ?? window.innerHeight) - 72)
        const totalWidth = baseViewports.reduce((sum, viewport) => sum + viewport.width, 0) + gap
        const maxHeight = Math.max(...baseViewports.map((viewport) => viewport.height), 1)
        const scale = Math.min(availableWidth / Math.max(totalWidth, 1), availableHeight / maxHeight)
        const outputScale = window.devicePixelRatio || 1
        const slots = [
          { pageElement: leftPage, canvas: leftCanvas, textLayer: leftTextLayer },
          { pageElement: rightPage, canvas: rightCanvas, textLayer: rightTextLayer },
        ]

        clearPage(rightPage, rightCanvas, rightTextLayer)
        validPages.forEach((page, index) => {
          const slot = slots[index]
          if (slot.pageElement === null || slot.canvas === null || slot.textLayer === null) return
          const context = slot.canvas.getContext('2d')
          if (context === null) return
          const viewport = page.getViewport({ scale })
          const width = Math.floor(viewport.width)
          const height = Math.floor(viewport.height)
          slot.pageElement.style.display = 'block'
          slot.pageElement.style.width = `${width}px`
          slot.pageElement.style.height = `${height}px`
          slot.canvas.width = Math.floor(viewport.width * outputScale)
          slot.canvas.height = Math.floor(viewport.height * outputScale)
          slot.canvas.style.width = `${width}px`
          slot.canvas.style.height = `${height}px`
          slot.textLayer.replaceChildren()
          slot.textLayer.style.width = `${width}px`
          slot.textLayer.style.height = `${height}px`
          slot.textLayer.style.setProperty('--total-scale-factor', String(scale))
          context.setTransform(outputScale, 0, 0, outputScale, 0, 0)
          const renderTask = page.render({ canvas: slot.canvas, canvasContext: context, viewport }) as RenderTask
          const textLayerTask = new pdfjsLib.TextLayer({
            textContentSource: page.streamTextContent({ includeMarkedContent: true, disableNormalization: true }),
            container: slot.textLayer,
            viewport,
          })
          renderTasksRef.current.push(renderTask)
          textLayerTasksRef.current.push(textLayerTask)
        })
        return Promise.all([
          ...renderTasksRef.current.map((task) => task.promise),
          ...textLayerTasksRef.current.map((task) => task.render()),
        ])
      })
      .catch((caught: unknown) => {
        if (isExpectedPdfCancellation(caught)) return
        setError(caught instanceof Error ? caught.message : t('app.requestFailed'))
      })

    window.localStorage.setItem(pdfPageKey(storageObjectId), String(pdfPageNumber))
    return () => {
      isCancelled = true
    }
  }, [pdfPageCount, pdfPageNumber, storageObjectId])

  function goPrevious() {
    setPdfPageNumber((current) => Math.max(1, current - 2))
  }

  function goNext() {
    setPdfPageNumber((current) => Math.min(spreadStartForPage(pdfPageCount || current), current + 2))
  }

  function goToSearchMatch(direction: 1 | -1) {
    if (searchMatches.length === 0) return
    const nextIndex = (selectedSearchIndex + direction + searchMatches.length) % searchMatches.length
    setSelectedSearchIndex(nextIndex)
    setPdfPageNumber(spreadStartForPage(searchMatches[nextIndex]))
  }

  function handleBookClick(event: MouseEvent<HTMLDivElement>) {
    const selection = window.getSelection()?.toString() ?? ''
    if (selection.trim() !== '') return
    const rect = event.currentTarget.getBoundingClientRect()
    const x = event.clientX - rect.left
    if (x < rect.width * 0.18) {
      goPrevious()
    } else if (x > rect.width * 0.82) {
      goNext()
    }
  }

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      const target = event.target
      if (event.ctrlKey && event.key.toLowerCase() === 'f') {
        const searchInput = document.querySelector<HTMLInputElement>('.bookshelf-reader-search input')
        if (searchInput !== null) {
          event.preventDefault()
          searchInput.focus()
          searchInput.select()
        }
        return
      }
      if (
        target instanceof HTMLInputElement
        || target instanceof HTMLSelectElement
        || target instanceof HTMLTextAreaElement
      ) {
        return
      }
      const key = event.key.toLowerCase()
      if (event.key === 'ArrowLeft' || key === 'a') {
        event.preventDefault()
        goPrevious()
      } else if (event.key === 'ArrowRight' || key === 'd') {
        event.preventDefault()
        goNext()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  })

  const pdfEndPageNumber = Math.min(pdfPageNumber + 1, pdfPageCount)
  const progressText = pdfPageCount > 0
    ? `${pdfPageNumber}${pdfEndPageNumber > pdfPageNumber ? `-${pdfEndPageNumber}` : ''} / ${pdfPageCount}`
    : ''
  const searchStatus = searchQuery.trim() === ''
    ? ''
    : searchMatches.length === 0
      ? '0 / 0'
      : `${selectedSearchIndex + 1} / ${searchMatches.length}`

  return (
    <main className="app-shell bookshelf-reader-page">
      <div className="bookshelf-reader-shell">
        <header className="bookshelf-reader-topbar">
          <button onClick={() => navigateTo('/bookshelf')} type="button">
            {t('bookshelf.reader.back')}
          </button>
          <div>
            <p>{t('app.name')}</p>
            <h1>{title}</h1>
          </div>
          <TopNav
            ariaLabelKey="bookshelf.reader.navigation"
            items={[
              { href: '/bookshelf', labelKey: 'bookshelf.heading' },
              { href: '/', labelKey: 'top.heading' },
            ]}
          />
        </header>

        {error !== null && <p className="contact-error bookshelf-reader-error" role="alert">{error}</p>}

        <section className="bookshelf-reader-stage" aria-label={t('bookshelf.reader.heading')}>
          <div className="bookshelf-reader-chrome" aria-live="polite">
            <span className="bookshelf-reader-page-count-left">{progressText}</span>
            <label className="bookshelf-reader-search">
              <input
                aria-label={t('bookshelf.reader.search')}
                disabled={!isReady}
                onChange={(event) => setSearchQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault()
                    goToSearchMatch(event.shiftKey ? -1 : 1)
                  }
                }}
                placeholder={isIndexing ? t('bookshelf.reader.indexing') : t('bookshelf.reader.search')}
                type="search"
                value={searchQuery}
              />
              <button disabled={searchMatches.length === 0} onClick={() => goToSearchMatch(-1)} type="button">Prev</button>
              <button disabled={searchMatches.length === 0} onClick={() => goToSearchMatch(1)} type="button">Next</button>
              {searchStatus !== '' && <small>{searchStatus}</small>}
            </label>
            <span className="bookshelf-reader-page-count-right">{isLoading ? t('common.loading') : progressText}</span>
          </div>
          <div className="bookshelf-reader-book" onClick={handleBookClick}>
            <button
              aria-label={t('bookshelf.reader.previous')}
              className="bookshelf-reader-turn bookshelf-reader-turn-left"
              disabled={!isReady || pdfPageNumber <= 1}
              onClick={(event) => { event.stopPropagation(); goPrevious() }}
              type="button"
            />
            <div className="bookshelf-reader-frame bookshelf-pdf-frame">
              <div className="bookshelf-pdf-spread">
                <div className="bookshelf-pdf-page" ref={leftPageRef}>
                  <canvas ref={leftCanvasRef} />
                  <div className="textLayer bookshelf-pdf-text-layer" ref={leftTextLayerRef} />
                </div>
                <div className="bookshelf-pdf-page" ref={rightPageRef}>
                  <canvas ref={rightCanvasRef} />
                  <div className="textLayer bookshelf-pdf-text-layer" ref={rightTextLayerRef} />
                </div>
              </div>
            </div>
            <button
              aria-label={t('bookshelf.reader.next')}
              className="bookshelf-reader-turn bookshelf-reader-turn-right"
              disabled={!isReady || (pdfPageCount > 0 && pdfPageNumber >= pdfPageCount - 1)}
              onClick={(event) => { event.stopPropagation(); goNext() }}
              type="button"
            />
          </div>
        </section>
      </div>
    </main>
  )
}
