import request from './request'

export const getSearchSettings = () => request.get('/search/settings')
export const updateSearchSettings = (data) => request.put('/search/settings', data)
export const testSearch = (query) => request.post('/search/test', { query })
