import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { t } from './i18n'
import { AppLink, navigateTo } from './navigation'
import { loadMobileQuickSlot, readMobileQuickSlot, saveMobileQuickSlot } from './mobileQuickSlot'
import './MobileTopView.css'

export default function MobileSettingsView() {
  const [label, setLabel] = useState(() => readMobileQuickSlot()?.label ?? '')
  const [href, setHref] = useState(() => readMobileQuickSlot()?.href ?? '')
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isBusy, setIsBusy] = useState(false)

  useEffect(() => {
    let canceled = false
    void loadMobileQuickSlot()
      .then((slot) => {
        if (canceled) return
        setLabel(slot?.label ?? '')
        setHref(slot?.href ?? '')
      })
      .catch((requestError) => {
        if (!canceled) {
          setError(requestError instanceof Error ? requestError.message : t('mobile.top.loadFailed'))
        }
      })
    return () => {
      canceled = true
    }
  }, [])

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setIsBusy(true)
    setError(null)
    setNotice(null)
    try {
      const trimmedLabel = label.trim()
      const trimmedHref = href.trim()
      const slot = await saveMobileQuickSlot(
        trimmedLabel === '' || trimmedHref === ''
          ? null
          : { label: trimmedLabel, href: trimmedHref },
      )
      setLabel(slot?.label ?? '')
      setHref(slot?.href ?? '')
      setNotice(t('mobile.settings.saved'))
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('mobile.top.loadFailed'))
    } finally {
      setIsBusy(false)
    }
  }

  async function handleClear() {
    setIsBusy(true)
    setError(null)
    setNotice(null)
    try {
      await saveMobileQuickSlot(null)
      setLabel('')
      setHref('')
      setNotice(t('mobile.settings.cleared'))
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('mobile.top.loadFailed'))
    } finally {
      setIsBusy(false)
    }
  }

  return (
    <main className="mobile-shell">
      <header className="mobile-topbar">
        <div>
          <p>C@seClosed</p>
          <h1>{t('mobile.settings.heading')}</h1>
        </div>
        <AppLink className="mobile-topbar-link" href="/m">
          {t('common.backToList')}
        </AppLink>
      </header>

      {notice !== null && <p className="mobile-alert mobile-notice">{notice}</p>}
      {error !== null && <p className="mobile-alert" role="alert">{error}</p>}

      <section className="mobile-panel mobile-settings-panel">
        <div>
          <h2>{t('mobile.settings.quickSlotHeading')}</h2>
          <p>{t('mobile.settings.quickSlotBody')}</p>
        </div>
        <form className="mobile-settings-form" onSubmit={handleSubmit}>
          <label>
            <span>{t('mobile.settings.quickSlotLabel')}</span>
            <input
              autoComplete="off"
              maxLength={24}
              onChange={(event) => setLabel(event.target.value)}
              value={label}
            />
          </label>
          <label>
            <span>{t('mobile.settings.quickSlotHref')}</span>
            <input
              autoComplete="off"
              inputMode="url"
              onChange={(event) => setHref(event.target.value)}
              placeholder="/files"
              value={href}
            />
          </label>
          <div className="mobile-settings-actions">
            <button disabled={isBusy} type="submit">{t('common.save')}</button>
            <button disabled={isBusy} type="button" onClick={() => void handleClear()}>{t('common.clear')}</button>
          </div>
        </form>
      </section>

      <button className="mobile-secondary-button" type="button" onClick={() => navigateTo('/m')}>
        {t('mobile.settings.backToTop')}
      </button>
    </main>
  )
}
