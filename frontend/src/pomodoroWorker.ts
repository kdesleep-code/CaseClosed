type WorkerCommand =
  | { type: 'start'; intervalMs?: number }
  | { type: 'stop' }
  | { type: 'syncNow' }

type WorkerEvent =
  | { type: 'tick' }
  | { type: 'sync' }

let tickTimerId: ReturnType<typeof setInterval> | null = null
let syncTimerId: ReturnType<typeof setInterval> | null = null
let intervalMs = 1000

function post(event: WorkerEvent) {
  self.postMessage(event)
}

function stopTimers() {
  if (tickTimerId !== null) {
    clearInterval(tickTimerId)
    tickTimerId = null
  }
  if (syncTimerId !== null) {
    clearInterval(syncTimerId)
    syncTimerId = null
  }
}

function startTimers() {
  stopTimers()
  tickTimerId = setInterval(() => post({ type: 'tick' }), 1000)
  syncTimerId = setInterval(() => post({ type: 'sync' }), intervalMs)
}

self.addEventListener('message', (event: MessageEvent<WorkerCommand>) => {
  const command = event.data
  if (command.type === 'start') {
    intervalMs = Math.max(250, command.intervalMs ?? 1000)
    startTimers()
    post({ type: 'tick' })
    post({ type: 'sync' })
    return
  }
  if (command.type === 'stop') {
    stopTimers()
    return
  }
  if (command.type === 'syncNow') {
    post({ type: 'sync' })
  }
})

export {}
