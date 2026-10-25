import request from './request'

export const getHealth = () => request.get('/system/health', { silent: true })
export const getDashboard = () => request.get('/system/dashboard')
export const getSystemInfo = () => request.get('/system/info')
export const getConfig = () => request.get('/system/config')
export const updateConfig = (patch) => request.put('/system/config', patch)
export const listJobs = () => request.get('/system/jobs')
export const listBackups = () => request.get('/system/backups')
export const createBackup = () => request.post('/system/backups')
export const restoreBackup = (name) => request.post('/system/backups/restore', { name })
export const getCacheStats = () => request.get('/system/cache')
