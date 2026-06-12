import { useEffect, useId, useMemo, useRef, useState } from 'react'

export type SuggestInputOption = {
  key: string
  value: string
  label?: string
  badgeLabel?: string
}

function splitValue(value: string) {
  return value
    .split(/[,;]/)
    .map((item) => item.trim())
    .filter((item) => item !== '')
}

function serializeValue(tokens: string[], draft: string) {
  return [...tokens, draft.trim()].filter((item) => item !== '').join(', ')
}

export default function SuggestInput({
  ariaLabel,
  autoComplete,
  className,
  disabled = false,
  maxItems,
  options,
  placeholder,
  value,
  onChange,
  onBlur,
}: {
  ariaLabel: string
  autoComplete?: string
  className?: string
  disabled?: boolean
  maxItems?: number
  options: SuggestInputOption[]
  placeholder?: string
  value: string
  onChange: (value: string) => void
  onBlur?: () => void
}) {
  const datalistId = useId()
  const [tokens, setTokens] = useState<string[]>([])
  const [draft, setDraft] = useState('')
  const lastSerializedRef = useRef('')
  const optionByValue = useMemo(() => {
    const map = new Map<string, SuggestInputOption>()
    for (const option of options) {
      map.set(option.value, option)
    }
    return map
  }, [options])

  useEffect(() => {
    if (value === lastSerializedRef.current) return
    setTokens(splitValue(value).slice(0, maxItems))
    setDraft('')
    lastSerializedRef.current = value
  }, [maxItems, value])

  function commitToken(nextValue: string) {
    const normalized = nextValue.trim()
    if (normalized === '' || !optionByValue.has(normalized)) return false
    const nextTokens =
      maxItems === 1
        ? [normalized]
        : tokens.includes(normalized)
          ? tokens
          : [...tokens, normalized].slice(0, maxItems)
    const nextSerialized = serializeValue(nextTokens, '')
    setTokens(nextTokens)
    setDraft('')
    lastSerializedRef.current = nextSerialized
    onChange(nextSerialized)
    return true
  }

  function updateDraft(nextDraft: string) {
    if (commitToken(nextDraft)) return
    setDraft(nextDraft)
    const nextSerialized = serializeValue(tokens, nextDraft)
    lastSerializedRef.current = nextSerialized
    onChange(nextSerialized)
  }

  function removeToken(token: string) {
    const nextTokens = tokens.filter((item) => item !== token)
    const nextSerialized = serializeValue(nextTokens, draft)
    setTokens(nextTokens)
    lastSerializedRef.current = nextSerialized
    onChange(nextSerialized)
  }

  const isFull = maxItems !== undefined && tokens.length >= maxItems

  return (
    <div className={`suggest-input ${className ?? ''}`.trim()}>
      {tokens.map((token) => {
        const option = optionByValue.get(token)
        return (
          <button
            aria-label={`Remove ${option?.badgeLabel ?? token}`}
            className="suggest-input-token"
            disabled={disabled}
            key={token}
            onClick={() => removeToken(token)}
            type="button"
          >
            <span>{option?.badgeLabel ?? token}</span>
            <strong aria-hidden="true">x</strong>
          </button>
        )
      })}
      {!isFull && (
        <input
          aria-label={ariaLabel}
          autoComplete={autoComplete}
          disabled={disabled}
          list={datalistId}
          onBlur={onBlur}
          onChange={(event) => updateDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key !== 'Enter') return
            event.preventDefault()
            commitToken(draft)
          }}
          placeholder={tokens.length === 0 ? placeholder : undefined}
          type="text"
          value={draft}
        />
      )}
      <datalist id={datalistId}>
        {options.map((option) => (
          <option key={option.key} label={option.label} value={option.value} />
        ))}
      </datalist>
    </div>
  )
}
