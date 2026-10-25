import { channelInfo } from './channels'

export function formatDateTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value).replace('T', ' ')
  const pad = (n) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

export function formatDate(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  const pad = (n) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

export function formatBytes(size) {
  const value = Number(size || 0)
  if (!value) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let result = value
  let index = 0
  while (result >= 1024 && index < units.length - 1) {
    result /= 1024
    index += 1
  }
  return `${result.toFixed(1)} ${units[index]}`
}

export function truncate(text, limit = 60) {
  if (!text) return ''
  const value = String(text)
  return value.length > limit ? `${value.slice(0, limit)}…` : value
}

export function platformLabel(platform) {
  return channelInfo(platform).label
}

export function accountStatusType(status) {
  return (
    {
      online: 'success',
      connecting: 'warning',
      waiting_qr: 'info',
      scanning: 'warning',
      offline: 'info',
      risk: 'danger',
      error: 'danger',
    }[status] || 'info'
  )
}

export function logStatusType(status) {
  return { ok: 'success', blocked: 'warning', failed: 'danger' }[status] || 'info'
}
