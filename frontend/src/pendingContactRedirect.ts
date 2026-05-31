import { listUnresolvedFromAddresses } from './phase3Api'

export const pendingContactRedirectEventName = 'caseclosed:pending-contact-redirect'

export type PendingContactRedirectEvent = CustomEvent<{
  count: number
}>

export async function notifyPendingContactsIfAny() {
  const pendingContacts = await listUnresolvedFromAddresses()
  if (pendingContacts.length === 0) {
    return
  }
  window.dispatchEvent(
    new CustomEvent(pendingContactRedirectEventName, {
      detail: { count: pendingContacts.length },
    }),
  )
}
