const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/
const SOURCE_TIME = /\b(?:0?[1-9]|1[0-2]):[0-5]\d\s?[ap]\.?m\.?|(?:[01]?\d|2[0-3]):[0-5]\d\b/i

function formatIsoDate(value) {
  const match = typeof value === 'string' ? ISO_DATE.exec(value) : null
  if (!match) return null
  const [, year, month, day] = match
  const monthName = new Intl.DateTimeFormat('en', { month: 'short', timeZone: 'UTC' })
    .format(new Date(Date.UTC(Number(year), Number(month) - 1, Number(day))))
  return { year, month, day, monthName }
}

function format24HourTime(value) {
  const match = /^(\d{1,2}):(\d{2})$/.exec(String(value || '').trim())
  if (!match) return value || ''
  const hours = Number(match[1])
  const minutes = Number(match[2])
  if (hours > 23 || minutes > 59) return value
  const suffix = hours >= 12 ? 'PM' : 'AM'
  const displayHours = hours % 12 || 12
  return `${displayHours}:${String(minutes).padStart(2, '0')} ${suffix}`
}

export function formatDeadlineDate(item = {}) {
  const start = formatIsoDate(item.date)
  const end = formatIsoDate(item.end_date)
  if (start && end && start.year === end.year && start.month === end.month) {
    return `${start.day}–${end.day} ${start.monthName} ${start.year}`
  }
  if (start && end && start.year === end.year) {
    return `${start.day} ${start.monthName}–${end.day} ${end.monthName} ${start.year}`
  }
  if (start && end) {
    return `${start.day} ${start.monthName} ${start.year}–${end.day} ${end.monthName} ${end.year}`
  }
  if (start) return `${start.day} ${start.monthName} ${start.year}`
  return item.date || item.deadline || 'Date to confirm'
}

export function formatDeadlineDay(item = {}) {
  const start = formatIsoDate(item.date)
  const end = formatIsoDate(item.end_date)
  if (!start) return item.day || ''
  if (end && start.year === end.year && start.month === end.month) return `${start.day}–${end.day}`
  return start.day
}

export function formatDeadlineTime(item = {}) {
  const evidence = item.evidence || item.source_excerpt || item.excerpt || ''
  const sourceTime = SOURCE_TIME.exec(evidence)?.[0]
  if (sourceTime) return sourceTime.replace(/\s+/g, ' ').trim().replace(/[.,;]+$/, '')
  return format24HourTime(item.time)
}

export function formatDeadlineLabel(item = {}) {
  const date = formatDeadlineDate(item)
  const time = formatDeadlineTime(item)
  return `${date}${time ? ` · ${time}` : ''}`
}
