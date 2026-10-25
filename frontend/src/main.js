import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import {
  AlarmClock, ArrowDown, Brush, ChatDotRound, ChatLineSquare, CircleClose,
  Cloudy, Coin, Collection, CopyDocument, Cpu, Delete, Document, Iphone,
  MagicStick, Microphone, Moon, Odometer, Picture, RefreshRight, Search, Setting, Sunny,
  TrendCharts, User,
} from '@element-plus/icons-vue'

import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import '@/styles/index.css'

import App from './App.vue'
import router from './router'
import pinia from './stores'

const app = createApp(App)

const icons = {
  AlarmClock, ArrowDown, Brush, ChatDotRound, ChatLineSquare, CircleClose,
  Cloudy, Coin, Collection, CopyDocument, Cpu, Delete, Document, Iphone,
  MagicStick, Microphone, Moon, Odometer, Picture, RefreshRight, Search, Setting, Sunny,
  TrendCharts, User,
}
for (const [key, component] of Object.entries(icons)) {
  app.component(key, component)
}

app.use(pinia)
app.use(router)
app.use(ElementPlus, { locale: zhCn })
app.mount('#app')
