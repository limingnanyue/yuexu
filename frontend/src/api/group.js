import request from './request'

export const listRules = (params) => request.get('/groups', { params })
export const lookupRule = (params) => request.get('/groups/lookup', { params })
export const createRule = (data) => request.post('/groups', data)
export const updateRule = (id, data) => request.put(`/groups/${id}`, data)
export const deleteRule = (id) => request.delete(`/groups/${id}`)
export const muteMember = (data) => request.post('/groups/actions/mute', data)
export const kickMember = (data) => request.post('/groups/actions/kick', data)
