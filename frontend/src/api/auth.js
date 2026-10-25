import request from './request'

export const login = (data) => request.post('/auth/login', data)
export const getMe = () => request.get('/auth/me')
export const changePassword = (data) => request.post('/auth/change-password', data)
export const listUsers = () => request.get('/auth/users')
export const createUser = (data) => request.post('/auth/users', data)
export const updateUser = (id, data) => request.put(`/auth/users/${id}`, data)
export const deleteUser = (id) => request.delete(`/auth/users/${id}`)
