import { useEffect, useMemo, useState } from 'react'
import type { CSSProperties, FormEvent } from 'react'
import settingsGearIconUrl from './assets/settings-gear.svg'
import { t } from './i18n'
import { navigateTo, TopNav } from './navigation'

const bookshelfTagHierarchyStorageKey = 'caseclosed.bookshelf.tagHierarchy'

type TagTreeNode = {
  tag: string
  children: TagTreeNode[]
}

function normalizeTag(tag: string) {
  return tag.trim().toLowerCase()
}

function readStoredTagHierarchy() {
  try {
    const rawValue = window.localStorage.getItem(bookshelfTagHierarchyStorageKey)
    if (rawValue === null) return {}
    const parsed = JSON.parse(rawValue)
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) return {}
    const result: Record<string, string> = {}
    Object.entries(parsed).forEach(([childTag, parentTag]) => {
      if (typeof parentTag !== 'string') return
      const normalizedChild = normalizeTag(childTag)
      const trimmedParent = parentTag.trim()
      if (normalizedChild === '' || trimmedParent === '' || normalizedChild === normalizeTag(trimmedParent)) return
      result[normalizedChild] = trimmedParent
    })
    return result
  } catch {
    return {}
  }
}

function writeStoredTagHierarchy(tagParents: Record<string, string>) {
  window.localStorage.setItem(bookshelfTagHierarchyStorageKey, JSON.stringify(tagParents))
}

function buildTagTree(tagParents: Record<string, string>) {
  const nodes = new Map<string, TagTreeNode>()
  const childKeys = new Set<string>()
  function nodeFor(tag: string) {
    const key = normalizeTag(tag)
    const existing = nodes.get(key)
    if (existing !== undefined) return existing
    const node = { tag, children: [] }
    nodes.set(key, node)
    return node
  }

  Object.entries(tagParents).forEach(([childTag, parentTag]) => {
    const childNode = nodeFor(childTag)
    const parentNode = nodeFor(parentTag)
    parentNode.children.push(childNode)
    childKeys.add(normalizeTag(childTag))
  })

  const roots = [...nodes.entries()]
    .filter(([key]) => !childKeys.has(key))
    .map(([, node]) => node)
    .sort((left, right) => left.tag.localeCompare(right.tag))

  function sortChildren(node: TagTreeNode) {
    node.children.sort((left, right) => left.tag.localeCompare(right.tag))
    node.children.forEach(sortChildren)
  }
  roots.forEach(sortChildren)
  return roots
}

function TagNodeView({ node, depth = 0 }: { node: TagTreeNode; depth?: number }) {
  return (
    <li>
      <div className="bookshelf-tag-tree-node" style={{ '--tag-depth': depth } as CSSProperties}>
        <span>{node.tag}</span>
      </div>
      {node.children.length > 0 && (
        <ul>
          {node.children.map((child) => <TagNodeView depth={depth + 1} key={normalizeTag(child.tag)} node={child} />)}
        </ul>
      )}
    </li>
  )
}

export default function BookshelfTagHierarchyView() {
  const [tagParents, setTagParents] = useState<Record<string, string>>(() => readStoredTagHierarchy())
  const [childTag, setChildTag] = useState('')
  const [parentTag, setParentTag] = useState('')
  const [isEditing, setIsEditing] = useState(false)
  const [feedback, setFeedback] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    writeStoredTagHierarchy(tagParents)
  }, [tagParents])

  const tree = useMemo(() => buildTagTree(tagParents), [tagParents])
  const relationships = useMemo(
    () => Object.entries(tagParents).sort((left, right) => left[0].localeCompare(right[0])),
    [tagParents],
  )

  function saveRelationship(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const child = childTag.trim()
    const parent = parentTag.trim()
    if (child === '' || parent === '') {
      setError(t('bookshelf.tagHierarchy.required'))
      return
    }
    const normalizedChild = normalizeTag(child)
    const normalizedParent = normalizeTag(parent)
    if (normalizedChild === normalizedParent) {
      setError(t('bookshelf.tagHierarchy.sameTag'))
      return
    }
    setTagParents((current) => ({ ...current, [normalizedChild]: parent }))
    setChildTag('')
    setParentTag('')
    setError(null)
    setFeedback(t('bookshelf.tagHierarchy.saved'))
  }

  function deleteRelationship(child: string) {
    setTagParents((current) => {
      const next = { ...current }
      delete next[child]
      return next
    })
    setFeedback(t('bookshelf.tagHierarchy.deleted'))
  }

  return (
    <main className="app-shell">
      <div className="contacts-shell bookshelf-shell bookshelf-tag-hierarchy-page">
        <header className="contacts-header">
          <div>
            <p>{t('bookshelf.heading')}</p>
            <h1>{t('bookshelf.tagHierarchy.heading')}</h1>
          </div>
          <TopNav
            ariaLabelKey="bookshelf.tagHierarchy.navigation"
            items={[
              { href: '/bookshelf', labelKey: 'bookshelf.heading' },
              { href: '/', labelKey: 'top.heading' },
            ]}
          />
        </header>

        {error !== null && <p className="contact-error" role="alert">{error}</p>}
        {feedback !== null && <p className="contact-notice">{feedback}</p>}

        {isEditing && (
          <section className="contact-panel bookshelf-tag-hierarchy-form-panel">
            <div className="section-heading">
              <h2>{t('bookshelf.tagHierarchy.add')}</h2>
            </div>
            <form className="bookshelf-tag-pair-form" onSubmit={saveRelationship}>
              <label>
                <span>{t('bookshelf.tagHierarchy.child')}</span>
                <input
                  onChange={(event) => setChildTag(event.target.value)}
                  placeholder={t('bookshelf.tagHierarchy.childPlaceholder')}
                  value={childTag}
                />
              </label>
              <label>
                <span>{t('bookshelf.tagHierarchy.parent')}</span>
                <input
                  onChange={(event) => setParentTag(event.target.value)}
                  placeholder={t('bookshelf.tagHierarchy.parentPlaceholder')}
                  value={parentTag}
                />
              </label>
              <button type="submit">{t('bookshelf.tagHierarchy.save')}</button>
            </form>
          </section>

        )}

        <section className="contact-list-workspace bookshelf-tag-hierarchy-workspace">
          <div className="contact-list-panel-surface">
            <div className={`contact-list-panel bookshelf-tag-hierarchy-layout${isEditing ? " is-editing" : ""}`}>
              <section aria-labelledby="bookshelf-tag-tree-heading">
                <div className="section-heading bookshelf-tag-tree-heading-row">
                  <h2 id="bookshelf-tag-tree-heading">{t('bookshelf.tagHierarchy.tree')}</h2>
                  <button
                    aria-label={isEditing ? t('bookshelf.tagHierarchy.done') : t('bookshelf.tagHierarchy.editMode')}
                    aria-pressed={isEditing}
                    className="bookshelf-tag-hierarchy-edit-button"
                    onClick={() => setIsEditing((current) => !current)}
                    title={isEditing ? t('bookshelf.tagHierarchy.done') : t('bookshelf.tagHierarchy.editMode')}
                    type="button"
                  >
                    <img alt="" src={settingsGearIconUrl} />
                  </button>
                </div>
                {tree.length === 0 ? (
                  <p className="empty-state">{t('bookshelf.tagHierarchy.empty')}</p>
                ) : (
                  <ul className="bookshelf-tag-tree">
                    {tree.map((node) => <TagNodeView key={normalizeTag(node.tag)} node={node} />)}
                  </ul>
                )}
              </section>

              {isEditing && (
                <section aria-labelledby="bookshelf-tag-relations-heading">
                  <div className="section-heading">
                    <h2 id="bookshelf-tag-relations-heading">{t('bookshelf.tagHierarchy.relations')}</h2>
                  </div>
                  {relationships.length === 0 ? (
                    <p className="empty-state">{t('bookshelf.tagHierarchy.empty')}</p>
                  ) : (
                    <div className="bookshelf-tag-relations">
                      {relationships.map(([child, parent]) => (
                        <div className="bookshelf-tag-relation-row" key={child}>
                          <span>{child}</span>
                          <span aria-hidden="true">→</span>
                          <span>{parent}</span>
                          <button onClick={() => deleteRelationship(child)} type="button">{t('common.delete')}</button>
                        </div>
                      ))}
                    </div>
                  )}
                </section>
              )}
            </div>
          </div>
        </section>

        <div className="bookshelf-tag-hierarchy-footer-actions">
          <button onClick={() => navigateTo('/bookshelf')} type="button">{t('bookshelf.reader.back')}</button>
        </div>
      </div>
    </main>
  )
}
