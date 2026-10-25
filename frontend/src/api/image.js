import request from './request'

export const getImageSettings = () => request.get('/images/settings')
export const updateImageSettings = (data) => request.put('/images/settings', data)
export const generateImage = (data, timeout = 120) => request.post('/images/generate', data, { timeout: (timeout + 15) * 1000 })
