import request from './request'

export const getVitalitySettings = () => request.get('/vitality/settings')
export const updateVitalitySettings = data => request.put('/vitality/settings', data)

export const listVitalitySessions = params => request.get('/vitality/sessions', { params })
export const patchVitalitySession = (id, data) => request.patch(`/vitality/sessions/${id}`, data)

export const listVitalityLogs = params => request.get('/vitality/logs', { params })

export const listTopics = () => request.get('/vitality/topics')
export const createTopic = data => request.post('/vitality/topics', data)
export const updateTopic = (id, data) => request.put(`/vitality/topics/${id}`, data)
export const deleteTopic = id => request.delete(`/vitality/topics/${id}`)

export const previewVitality = data => request.post('/vitality/preview', data)
