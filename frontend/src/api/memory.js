import request from './request'

export const listMemories = (params) => request.get('/memory', { params })
export const createMemory = (data) => request.post('/memory', data)
export const updateMemory = (id, data) => request.put(`/memory/${id}`, data)
export const memoryStats = (params) => request.get('/memory/stats', { params })
export const deleteMemory = (id) => request.delete(`/memory/${id}`)
export const resetMemory = (data) => request.post('/memory/reset', data)
export const exportMemory = (params) => request.get('/memory/export', { params })
export const confirmMemories = (ids) => request.post('/memory/confirm', { ids })
export const rejectMemories = (ids) => request.post('/memory/reject', { ids })
export const getMemorySettings = () => request.get('/memory/settings')
export const updateMemorySettings = (data) => request.put('/memory/settings', data)
export const runMemoryMaintenance = (action) =>
  request.post('/memory/maintenance', { action })

export const listContexts = (params) => request.get('/contexts', { params })
export const contextDetail = (params) => request.get('/contexts/detail', { params })
export const clearContext = (data) => request.post('/contexts/clear', data)
export const freezeContext = (data) => request.post('/contexts/freeze', data)
export const unfreezeContext = (data) => request.post('/contexts/unfreeze', data)
export const cleanupContexts = () => request.post('/contexts/cleanup')
export const clearAllContexts = () => request.delete('/contexts')
