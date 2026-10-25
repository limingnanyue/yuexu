import request from './request'

export const listEmotions = (params) => request.get('/emotions', { params })
export const getEmotion = (id) => request.get(`/emotions/${id}`)
export const updateEmotion = (id, data) => request.put(`/emotions/${id}`, data)
export const resetEmotion = (id) => request.delete(`/emotions/${id}`)
export const clearEmotions = () => request.post('/emotions/clear')
