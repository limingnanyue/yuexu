# 前端（Vue 3 + Vite + Element Plus）

## 开发

```bash
npm install
npm run dev        # http://127.0.0.1:5173，/api 与 /static 自动代理到 127.0.0.1:8000
```

## 构建

```bash
npm run build      # 产物在 frontend/dist，由后端自动托管
```

## 目录

```text
src
├── api          # Axios 接口封装（与后端 routers 一一对应）
├── assets       # 月叙 SVG 标志与月面 WebP，由 Vite 统一打包
├── components   # PageHeader / StatCard / SideNavigation
├── layouts      # AppLayout 控制台外壳
├── router       # 路由 + 登录守卫
├── stores       # Pinia：auth / app
├── styles       # 全局主题与 Element Plus 覆盖
├── utils        # 日期、状态格式化与四种通道资料
└── views        # 登录与 16 个控制台页面
```

## 约定

- 统一使用 `<script setup>` + Composition API，不用 TypeScript；
- 页面顶层结构：`div.yx-page` + `PageHeader` + `div.yx-card`；
- 普通接口错误由 `src/api/request.js` 统一提示；扫码使用 silent 请求，在弹窗内保留错误和重试入口；
- 登录态存 `localStorage`（`yuexu_token` / `yuexu_user`），401 自动跳转登录页；
- 主题变量集中在 `src/styles/index.css`，请优先复用现有类而不是新增全局样式。
- 760px 及以下使用抽屉导航，表格保留横向滚动；弹窗限制在视口以内。
- 图标仅在 `main.js` 注册动态引用的集合，局部图标优先使用具名导入。
