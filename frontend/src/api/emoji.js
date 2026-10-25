import request from './request'

export const listEmojis = (params) => request.get('/emojis', { params })
export const createEmoji = (data) => request.post('/emojis', data)
export const updateEmoji = (id, data) => request.put(`/emojis/${id}`, data)
export const deleteEmoji = (id) => request.delete(`/emojis/${id}`)
export const testSendEmoji = (id, data) => request.post(`/emojis/${id}/test-send`, data)

export const uploadEmoji = (formData) =>
  request.post('/emojis/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
