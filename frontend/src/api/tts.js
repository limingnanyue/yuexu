import request from './request'

export const getTtsSettings = () => request.get('/tts/settings')
export const updateTtsSettings = (data) => request.put('/tts/settings', data)
export const listVoices = () => request.get('/tts/voices')
export const synthesize = (data, timeout = 30) => request.post('/tts/synthesize', data, { timeout: Math.max(60000, (timeout + 15) * 1000) })
export const getTtsCache = () => request.get('/tts/cache')
export const cleanupTtsCache = () => request.post('/tts/cleanup')
export const clearTtsCache = () => request.delete('/tts/cache')
