import { describe, expect, it } from 'vitest'

import { authoredBodyMentionsAttachment } from './mailAttachmentReminder'

describe('authoredBodyMentionsAttachment', () => {
  it('detects an attachment mention in the newly written message', () => {
    expect(authoredBodyMentionsAttachment('資料を添付します。', '')).toBe(true)
  })

  it('ignores an attachment mention that exists only in Auto Body', () => {
    expect(
      authoredBodyMentionsAttachment(
        '確認しました。',
        '以前のメールで資料を添付しますと書かれていました。',
      ),
    ).toBe(false)
  })

  it('ignores quoted lines mixed into the manual body', () => {
    expect(
      authoredBodyMentionsAttachment(
        '確認しました。\n\nOn August 25, sender@example.com wrote:\n> 資料を添付します。',
        '',
      ),
    ).toBe(false)
  })

  it('ignores the original-message section mixed into the manual body', () => {
    expect(
      authoredBodyMentionsAttachment(
        '確認しました。\n\n-----Original Message-----\n資料を添付します。',
        '',
      ),
    ).toBe(false)
  })
})
