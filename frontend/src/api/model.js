import request from './request'

export const listModels = () => request.get('/models')
export const discoverModels = (data) => request.post('/models/discover', data, { timeout: 45000, silent: true })
export const createModel = (data) => request.post('/models', data)
export const updateModel = (id, data) => request.put(`/models/${id}`, data)
export const deleteModel = (id) => request.delete(`/models/${id}`)
export const setDefaultModel = (id) => request.post(`/models/${id}/default`)
export const testModel = (id) => request.post(`/models/${id}/test`)
