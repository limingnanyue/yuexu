import request from './request'

export const listCharacters = (params) => request.get('/characters', { params })
export const getCharacter = (id) => request.get(`/characters/${id}`)
export const getDefaultCharacter = () => request.get('/characters/default')
export const createCharacter = (data) => request.post('/characters', data)
export const updateCharacter = (id, data) => request.put(`/characters/${id}`, data)
export const deleteCharacter = (id) => request.delete(`/characters/${id}`)
export const setDefaultCharacter = (id) => request.post(`/characters/${id}/default`)
export const previewCharacter = (id) => request.get(`/characters/${id}/preview`)
export const exportCharacter = (id) => request.get(`/characters/${id}/export`)
export const importCharacter = (data) => request.post('/characters/import', data)
