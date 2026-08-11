<template>
  <div class="login-page">
    <el-card class="login-card">
      <h2 class="title">材料协同审核平台</h2>
      <el-form :model="form" @submit.prevent="onLogin">
        <el-form-item>
          <el-input v-model="form.username" placeholder="用户名" size="large" />
        </el-form-item>
        <el-form-item>
          <el-input v-model="form.password" type="password" placeholder="密码" size="large" show-password
            @keyup.enter="onLogin" />
        </el-form-item>
        <el-button type="primary" size="large" style="width: 100%" :loading="loading" @click="onLogin">
          登 录
        </el-button>
      </el-form>
      <p class="tip">账号由管理员预置，如遗忘请联系负责人</p>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const form = reactive({ username: '', password: '' })
const loading = ref(false)

const roleHome: Record<string, string> = {
  team: '/team',
  staff: '/staff',
  admin: '/admin',
  super_admin: '/super',
}

async function onLogin() {
  if (!form.username || !form.password) return
  loading.value = true
  try {
    const data = await auth.login(form.username, form.password)
    if (data.need_password_change) {
      router.push('/change-password')
    } else {
      router.push(roleHome[data.role] || '/')
    }
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1f3b73 0%, #2b5aa0 100%);
}
.login-card {
  width: 380px;
  padding: 12px 8px;
}
.title {
  text-align: center;
  margin-bottom: 24px;
  color: #1f3b73;
}
.tip {
  text-align: center;
  color: #999;
  font-size: 12px;
  margin-top: 12px;
}
</style>
