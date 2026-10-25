export const CHANNELS = [
  {
    value: 'wechat_clawbot', label: '微信 ClawBot', kind: 'bot', method: 'qr',
    icon: 'ChatDotRound', note: '扫码直连',
    description: '微信扫码，连接你的 ClawBot。',
    guide: '在手机微信中启用 ClawBot 后扫码确认，无需填写连接配置。当前支持微信私聊文本对话。',
    baseUrl: 'https://ilinkai.weixin.qq.com', media: false, groups: false, contacts: false,
  },
  {
    value: 'qq_bot', label: 'QQ 官方机器人', kind: 'bot', method: 'credentials',
    icon: 'Cpu', note: '官方接口',
    description: '使用 AppID 与 AppSecret 连接。',
    guide: '在 QQ 开放平台创建机器人并开通群聊、单聊事件权限。默认使用长连接，无需公网回调地址；也可选择 HTTPS 事件回调。当前发送文本。',
    baseUrl: 'https://api.bot.qq.com', media: false, groups: true, contacts: false,
  },
  {
    value: 'qq', label: 'QQ 个人账号', kind: 'account', method: 'qr',
    icon: 'Iphone', note: '自动配置',
    description: '自动准备登录环境，手机扫码即可。',
    guide: '月叙会自动准备登录环境并配置消息收发。首次需要下载组件；服务器会拉取镜像。下载中断可重试，完成后扫码即可。',
    baseUrl: 'http://127.0.0.1:3000', media: true, groups: true, contacts: true,
  },
  {
    value: 'wechat', label: '微信个人账号', kind: 'account', method: 'qr',
    icon: 'User', note: '已有服务接入', action: '连接已有服务',
    description: '连接你已经部署的 Gewechat 服务。',
    guide: '仅供已有可用 Gewechat 服务接入。上游已停止维护，月叙暂不提供自动安装；填写 API 地址后扫码，连接令牌与 AppID 可自动获取。',
    baseUrl: 'http://127.0.0.1:2531/v2/api', media: true, groups: true, contacts: true,
  },
]

export function channelInfo(platform) {
  return CHANNELS.find((item) => item.value === platform) || {
    label: platform || '未知接入', kind: 'account', method: 'qr', media: false, groups: false, contacts: false,
  }
}
