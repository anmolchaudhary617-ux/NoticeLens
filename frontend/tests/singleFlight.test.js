import assert from 'node:assert/strict'
import test from 'node:test'
import { runSingleFlight } from '../src/singleFlight.js'

test('drops a second analysis request while the first is active', async () => {
  const lock = { current: false }
  let release
  let calls = 0
  const first = runSingleFlight(lock, () => new Promise((resolve) => {
    calls += 1
    release = resolve
  }))
  const second = await runSingleFlight(lock, async () => { calls += 1 })

  assert.equal(second, false)
  assert.equal(calls, 1)
  release()
  assert.equal(await first, true)
  assert.equal(lock.current, false)
})

test('releases the analysis lock when the request fails', async () => {
  const lock = { current: false }
  await assert.rejects(runSingleFlight(lock, async () => { throw new Error('offline') }), /offline/)
  assert.equal(lock.current, false)
})
