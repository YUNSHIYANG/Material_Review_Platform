<template>
  <router-view v-if="isPlain" />
  <el-container v-else class="layout">
    <el-aside width="220px" class="aside">
      <div class="brand">材料审核平台</div>
      <el-menu :default-active="$route.path" router background-color="#001529" text-color="#c0c4cc"
        active-text-color="#ffffff">
        <template v-if="role === 'team'">
          <el-menu-item index="/team/submit">提交材料</el-menu-item>
          <el-menu-item index="/team">我的工单</el-menu-item>
        </template>
        <template v-else-if="role === 'staff'">
          <el-menu-item index="/staff">我的待办</el-menu-item>
        </template>
        <template v-else-if="role === 'admin'">
          <el-menu-item index="/admin">终审待办</el-menu-item>
        </template>
        <template v-else-if="role === 'super_admin'">
          <el-menu-item index="/super">后台概览与告警</el-menu-item>
          <el-menu-item index="/super/users">用户管理</el-menu-item>
          <el-menu-item index="/super/submissions">工单管理</el-menu-item>
          <el-menu-item index="/super/emails">邮件日志</el-menu-item>
          <el-menu-item index="/super/config">系统配置</el-menu-item>
          <el-menu-item index="/super/load">负载监控</el-menu-item>
          <el-menu-item index="/super/audit">操作审计</el-menu-item>
        </template>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header">
        <el-alert v-if="mailBanner" type="error" :closable="false" show-icon class="mail-banner">
          <template #title>
            系统邮件服务异常，部分通知发送失败，请检查邮件服务器配置并查看邮件日志。
            <el-button size="small" type="danger" @click="dismissBanner">已处理</el-button>
          </template>
        </el-alert>
        <div class="user-info">
          <span class="role-tag" :class="'role-' + role">{{ roleLabel }}</span>
          <span>{{ user?.real_name || user?.username }}</span>
          <el-button link type="primary" @click="router.push('/change-password')">修改密码</el-button>
          <el-button link type="primary" @click="onLogout">退出登录</el-button>
        </div>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import http from '@/api'

const auth = useAuthStore()
const router = useRouter()

const role = computed(() => auth.role)
const user = computed(() => auth.user)
const isPlain = computed(() => ['/login', '/change-password'].includes(router.currentRoute.value.path))

const roleLabel = computed(() => {
  const map: Record<string, string> = {
    team: '提交人',
    staff: '审核员',
    admin: '管理员',
    super_admin: '超级管理员',
  }
  return map[role.value] || role.value
})

const mailBanner = ref(false)

async function loadBanner() {
  if (role.value !== 'super_admin') return
  try {
    const { data } = await http.get('/super/dashboard')
    mailBanner.value = !!data.mail_banner
  } catch { /* ignore */ }
}

async function dismissBanner() {
  await http.post('/super/emails/banner/dismiss')
  mailBanner.value = false
}

onMounted(async () => {
  await auth.fetchMe()
  await loadBanner()
})

async function onLogout() {
  await ElMessageBox.confirm('确认退出登录吗？', '提示', { type: 'warning' }).catch(() => 'cancel').then((v) => {
    if (v === 'cancel') return
    auth.logout()
    router.push('/login')
  })
}
</script>

<style scoped>
.layout {
  height: 100vh;
}
.aside {
  background: #001529;
}
.brand {
  color: #fff;
  font-weight: 700;
  text-align: center;
  padding: 18px 0;
  font-size: 16px;
}
.aside :deep(.el-menu) {
  border-right: none;
}
.header {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  border-bottom: 1px solid #eee;
  background: #fff;
  height: 56px;
  padding: 0 16px;
}
.mail-banner {
  position: fixed;
  top: 0;
  left: 220px;
  right: 0;
  z-index: 100;
}
.user-info {
  display: flex;
  align-items: center;
  gap: 12px;
}
.role-tag {
  padding: 2px 10px;
  border-radius: 10px;
  font-size: 12px;
  color: #fff;
}
.role-team { background: #67c23a; }
.role-staff { background: #409eff; }
.role-admin { background: #e6a23c; }
.role-super_admin { background: #f56c6c; }
.main {
  background: #f5f7fa;
}
</style>
