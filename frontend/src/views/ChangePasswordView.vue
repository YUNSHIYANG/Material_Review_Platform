<template>
  <div class="login-page">
    <el-card class="login-card">
      <h2 class="title">修改密码</h2>
      <el-alert type="warning" :closable="false" class="notice">
        请妥善保管新密码。密码长度不少于8位，须同时包含大写字母、小写字母、数字和特殊字符。
      </el-alert>
      <el-form :model="form" label-width="90px" class="form">
        <el-form-item label="原密码">
          <el-input v-model="form.old_password" type="password" show-password />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="form.new_password" type="password" show-password />
        </el-form-item>
        <el-form-item label="确认密码">
          <el-input v-model="form.confirm" type="password" show-password />
        </el-form-item>
        <el-button type="primary" style="width: 100%" :loading="loading" @click="onSubmit">确认修改</el-button>
        <el-button link type="primary" style="width: 100%; margin-top: 8px" @click="back">返回首页</el-button>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import http from '@/api'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()
const form = reactive({ old_password: '', new_password: '', confirm: '' })
const loading = ref(false)

const roleHome: Record<string, string> = {
  team: '/team',
  staff: '/staff',
  admin: '/admin',
  super_admin: '/super',
}

function back() {
  router.push(auth.role ? roleHome[auth.role] || '/' : '/login')
}

async function onSubmit() {
  if (!form.old_password || !form.new_password) {
    ElMessage.warning('请填写完整')
    return
  }
  if (form.new_password !== form.confirm) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }
  loading.value = true
  try {
    await http.post('/auth/change-password', {
      old_password: form.old_password,
      new_password: form.new_password,
    })
    ElMessage.success('密码修改成功')
    await auth.fetchMe()
    router.push(roleHome[auth.role] || '/')
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
  width: 440px;
  padding: 12px 8px;
}
.title {
  text-align: center;
  margin-bottom: 20px;
  color: #1f3b73;
}
.notice {
  margin-bottom: 16px;
}
.form {
  margin-top: 8px;
}
</style>
