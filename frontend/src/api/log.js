import request from './request'

export const listLogs = (logType, params) => request.get(`/logs/${logType}`, { params })
export const cleanupLogs = (days) => request.post('/logs/cleanup', null, { params: { days } })

export const exportLogs = (logType, params) =>
  request.get(`/logs/${logType}/export`, { params, responseType: 'blob' })

export function downloadBlob(data, filename) {
  const url = window.URL.createObjectURL(new Blob([data]))
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  window.URL.revokeObjectURL(url)
}
