import test from 'node:test'
import assert from 'node:assert/strict'
import { formatDeadlineLabel } from '../src/deadlineFormatting.js'

test('single-day deadline uses one ISO-backed date and preserves the source time', () => {
  const label = formatDeadlineLabel({
    date: '2026-10-16',
    day: '16-16',
    time: '23:00',
    evidence: 'Last Date for Registration: 16th October 2026, 11:00 PM.',
  })

  assert.equal(label, '16 Oct 2026 · 11:00 PM')
})

test('festival date ranges remain distinct from a single-day deadline', () => {
  const label = formatDeadlineLabel({
    date: '2026-11-01',
    end_date: '2026-11-04',
    title: 'Festival dates',
    evidence: 'Dates: 1st–4th November 2026',
  })

  assert.equal(label, '01–04 Nov 2026')
})

test('a 24-hour time is converted when source evidence has no time wording', () => {
  assert.equal(formatDeadlineLabel({ date: '2026-10-16', time: '23:00' }), '16 Oct 2026 · 11:00 PM')
})
