import { useState } from 'react'
import type { FormEvent } from 'react'
import { t } from './i18n'
import { AppLink, navigateTo } from './navigation'
import { readMobileQuickSlot, writeMobileQuickSlot } from './mobileQuickSlot'
import './MobileTopView.css'

export default function MobileSettingsView() {
  const [label, setLabel] = useState(() => readMobileQuickSlot()?.label ?? '')
  const [href, setHref] = useState(() => readMobileQuickSlot()?.href ?? '')
  const [notice, setNotice] = useState<string | null>(null)

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const trimmedLabel = label.trim()
    const trimmedHref = href.trim()
    writeMobileQuickSlot(
      trimmedLabel === '' || trimmedHref === ''
        ? null
        : { label: trimmedLabel, href: trimmedHref },
    )
    setNotice(t('mobile.settings.saved'))
  }

  function handleClear() {
    setLabel('')
    setHref('')
    writeMobileQuickSlot(null)
    setNotice(t('mobile.settings.cleared'))
  }

  return (
    <main className="mobile-shell">
      <header className="mobile-topbar">
        <div>
          <p>CaseClosed</p>
          <h1>{t('mobile.settings.heading')}</h1>
        </div>
        <AppLink className="mobile-topbar-link" href="/m">
          {t('common.backToList')}
        </AppLink>
      </header>

      {notice !== null && <p className="mobile-alert mobile-notice">{notice}</p>}

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
            <button type="submit">{t('common.save')}</button>
            <button type="button" onClick={handleClear}>{t('common.clear')}</button>
          </div>
        </form>
      </section>

      <button className="mobile-secondary-button" type="button" onClick={() => navigateTo('/m')}>
        {t('mobile.settings.backToTop')}
      </button>
    </main>
  )
}
