<template>
  <div class="login-page">
    <section class="login-visual" aria-labelledby="brand-title">
      <div class="visual-brand"><img :src="logo" width="34" height="34" alt="" /><span>月叙 · 对话工作台</span></div>
      <div class="login-orbit" aria-hidden="true"></div>
      <img :src="moon" class="login-moon" width="420" height="420" alt="" fetchpriority="high" />
      <div class="visual-copy">
        <h1 id="brand-title">月叙</h1>
        <p class="tagline">月下叙话，记忆留存。</p>
        <p class="visual-intro">让每一段相遇，在对话中慢慢生长。</p>
        <ul class="features"><li>QQ 与微信，账号与机器人</li><li>独立人设，让回应拥有自己的语气</li><li>上下文与长期记忆，留住对话的线索</li></ul>
      </div>
      <p class="disclaimer">个人学习与测试使用 · 个人账号接入请勿使用主号</p>
    </section>
    <section class="login-panel">
      <img :src="moon" class="login-panel-moon" width="260" height="260" alt="" />
      <div class="login-card">
        <div class="login-brand"><img :src="logo" width="32" height="32" alt="" /><span>月叙控制台</span></div>
        <h2>欢迎回来</h2>
        <p class="login-sub">登录你的工作台，让下一段对话开始。</p>
        <el-alert v-if="loginError" :title="loginError" type="error" :closable="false" show-icon class="login-error" />
        <el-form :model="form" label-position="top" :aria-busy="loading" @submit.prevent="submit">
          <el-form-item label="账号" for="login-username"><el-input id="login-username" v-model="form.username" size="large" placeholder="请输入后台账号" :prefix-icon="User" autocomplete="username" /></el-form-item>
          <el-form-item label="密码" for="login-password"><el-input id="login-password" v-model="form.password" size="large" type="password" show-password placeholder="请输入密码" :prefix-icon="Lock" autocomplete="current-password" /></el-form-item>
          <el-button type="primary" native-type="submit" size="large" class="login-submit" :loading="loading">进入月叙<el-icon class="el-icon--right"><ArrowRight /></el-icon></el-button>
        </el-form>
        <details class="login-hint"><summary>首次使用？查看登录说明</summary><p>初始账号在 <code>config.yaml</code> 的 <code>security.admin</code> 中配置，默认 <code>admin / admin123</code>，登录后请修改。</p></details>
      </div>
      <p class="login-footer">月叙 · 月下叙话，记忆留存。</p>
    </section>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowRight, Lock, User } from '@element-plus/icons-vue'
import logo from '@/assets/yuexu.svg'
import moon from '@/assets/lunar-moon.webp'
import { useAuthStore } from '@/stores/auth'

const router=useRouter()
const route=useRoute()
const auth=useAuthStore()
const form=reactive({username:'',password:''})
const loading=ref(false)
const loginError=ref('')
async function submit() {
  if(loading.value) return
  loginError.value=''
  if(!form.username || !form.password) { ElMessage.warning('请输入账号与密码'); return }
  loading.value=true
  try {
    await auth.login({username:form.username,password:form.password})
    ElMessage.success(`欢迎回来，${auth.displayName}`)
    router.push(String(route.query.redirect || '/dashboard'))
  } catch(error) {
    const message=error.response?.data?.message || error.message
    loginError.value=typeof message==='string'?message:'登录失败，请核对账号与密码后重试'
  } finally { loading.value=false }
}
</script>

<style scoped>
.login-page { display:grid;grid-template-columns:minmax(0,1fr) minmax(360px,480px);gap:32px;min-height:100vh;min-height:100dvh;padding:32px;background:var(--yx-night); }
.login-visual { position:relative;overflow:hidden;min-height:680px;padding:36px 48px 76px;display:flex;flex-direction:column;border:1px solid var(--yx-line);border-radius:16px;background:#121c2b;color:var(--yx-text); }
.visual-brand { display:flex;align-items:center;gap:12px;font-size:12px;letter-spacing:.1em;color:#c5c4c1;position:relative;z-index:1; }
.login-moon { position:absolute;right:10%;top:8%;width:min(360px,52%,38vh);height:auto;pointer-events:none; }
.login-orbit { position:absolute;right:-19%;top:3%;width:650px;height:410px;border:1px solid rgb(195 178 142 / 20%);border-radius:50%;transform:rotate(-31deg); }
.visual-copy { position:relative;z-index:1;margin-top:auto;padding-top:260px;max-width:450px; }
.visual-copy h1 { font-family:var(--yx-heading-font);font-size:64px;line-height:1.2;letter-spacing:.24em;font-weight:400;margin:0; }
.tagline { margin:22px 0 0;font-family:var(--yx-heading-font);font-size:19px;letter-spacing:.12em;color:#ddc6a0; }
.visual-intro { margin:24px 0 16px;font-size:13px;line-height:1.8;color:var(--yx-text-2); }
.features { list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:10px;color:var(--yx-text-2);font-size:13px; }
.features li { display:flex;align-items:center;gap:12px; }
.features li::before { content:'';width:4px;height:4px;flex:none;border-radius:50%;background:#b9a581; }
.disclaimer { position:absolute;left:48px;right:40px;bottom:20px;font-size:12px;line-height:1.8;color:var(--yx-muted); }
.login-panel { position:relative;display:flex;flex-direction:column;align-items:center;justify-content:center;min-width:0;overflow:hidden;padding:48px 32px;background:var(--yx-night); }
.login-panel-moon { display:none; }
.login-card { width:100%;max-width:368px;position:relative;z-index:1; }
.login-brand { display:flex;align-items:center;gap:12px;font-size:13px;color:var(--yx-text-2);letter-spacing:.08em; }
.login-card h2 { margin:32px 0 10px;font-family:var(--yx-heading-font);font-size:30px;font-weight:400;letter-spacing:.03em;color:var(--yx-text); }
.login-sub { font-size:13px;color:var(--yx-muted);line-height:1.8;margin:0 0 32px; }
.login-card :deep(.el-input__wrapper) { min-height:48px;background:var(--yx-bg); }
.login-card :deep(.el-input__prefix) { margin-right:4px;color:var(--yx-muted); }
.login-card :deep(.el-form-item) { margin-bottom:24px; }
.login-card :deep(.el-form-item__label) { font-size:13px;color:var(--yx-text-2); }
.login-submit { width:100%;height:48px;margin-top:8px;font-size:14px; }
.login-hint { margin-top:24px;padding-top:20px;border-top:1px solid var(--yx-line);font-size:12px;line-height:1.9;color:var(--yx-muted); }
.login-hint summary { cursor:pointer;width:fit-content;transition:color .15s ease; }
.login-hint summary:hover { color:var(--yx-accent); }
.login-hint p { padding:12px 0;margin:0;overflow-wrap:anywhere; }
.login-hint code { color:#d7c49f;font-size:12px; }
.login-footer { margin:40px 0 0;font-size:12px;letter-spacing:.04em;color:var(--yx-muted); }
.login-error { margin:0 0 20px; }
@media (max-width:1100px) { .login-page { gap:16px;padding:20px; } .login-visual { padding:32px 32px 76px; } .visual-copy h1 { font-size:56px; } .login-moon { right:0;top:70px;width:min(300px,38vh); } .disclaimer { left:32px; } .login-panel { padding:40px 24px; } }
@media (max-width:900px) { .login-page { grid-template-columns:1fr;padding:0;gap:0; } .login-visual { display:none; } .login-panel { min-height:100dvh;padding:64px 28px; } .login-panel-moon { position:absolute;display:block;top:-100px;right:-100px;width:260px;height:260px;opacity:.55; } .login-card { max-width:360px; } }
@media (max-width:420px) { .login-panel { padding:40px 24px; } .login-card h2 { margin-top:28px; } .login-sub { margin-bottom:28px; } .login-footer { margin-top:32px; } }
</style>
