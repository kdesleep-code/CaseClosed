const attachmentMentionPattern =
  /添付|送付|attach(?:ed|ment)?|enclos(?:e|ed|ure)/i

const originalMessageSeparatorPattern =
  /^\s*-{2,}\s*(?:original message|元のメッセージ)\s*-{2,}\s*$/i

export function authoredBodyForAttachmentReminder(
  manualBody: string,
  autoBody: string,
): string {
  let candidate = manualBody.replace(/\r\n?/g, '\n')
  const normalizedAutoBody = autoBody.replace(/\r\n?/g, '\n').trim()
  if (normalizedAutoBody !== '') {
    candidate = candidate.split(normalizedAutoBody).join('')
  }

  const authoredLines: string[] = []
  for (const line of candidate.split('\n')) {
    if (originalMessageSeparatorPattern.test(line)) {
      break
    }
    if (/^\s*>/.test(line)) {
      continue
    }
    authoredLines.push(line)
  }
  return authoredLines.join('\n')
}

export function authoredBodyMentionsAttachment(
  manualBody: string,
  autoBody: string,
): boolean {
  return attachmentMentionPattern.test(
    authoredBodyForAttachmentReminder(manualBody, autoBody),
  )
}
