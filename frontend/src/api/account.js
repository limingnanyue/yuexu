import request from './request'

export const listAccounts = () => request.get('/accounts')
export const listMemoryLibraries = () => request.get('/accounts/memory-libraries')
export const getAccount = (id) => request.get(`/accounts/${id}`)
export const createAccount = (data) => request.post('/accounts', data)
export const updateAccount = (id, data) => request.put(`/accounts/${id}`, data)
export const deleteAccount = (id) => request.delete(`/accounts/${id}`)
export const prepareAccount = (id) => request.post(`/accounts/${id}/prepare`, null, { silent: true })
export const pollAccountPreparation = (id) => request.get(`/accounts/${id}/prepare`, { silent: true })
export const requestQrcode = (id, refresh = false) => request.post(`/accounts/${id}/qrcode`, null, { params: { refresh }, silent: true })
export const submitLoginCode = (id, verify_code) => request.post(`/accounts/${id}/login-code`, { verify_code }, { silent: true })
export const pollLoginStatus = (id) =>
  request.get(`/accounts/${id}/login-status`, { silent: true })
export const logoutAccount = (id) => request.post(`/accounts/${id}/logout`)
export const reconnectAccount = (id) => request.post(`/accounts/${id}/reconnect`)
export const fetchGroups = (id) => request.get(`/accounts/${id}/groups`)
export const fetchFriends = (id) => request.get(`/accounts/${id}/friends`)
