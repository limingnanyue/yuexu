import request from './request'

export const listPushUsers = params => request.get('/push-tasks/users', { params })
export const listPushRecords = params => request.get('/push-tasks/records', { params })
export const stopUserPush = (botId, userId) => request.put(
  `/push-tasks/users/${encodeURIComponent(botId)}/${encodeURIComponent(userId)}`,
  { user_push_switch: false },
)
