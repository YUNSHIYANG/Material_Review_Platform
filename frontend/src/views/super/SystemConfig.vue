<template>
  <el-card v-loading="loading">
    <template #header><b>系统配置</b></template>
    <el-alert type="info" :closable="false" class="mb">
      配置修改仅对新派发工单生效；已派发工单的截止时间基于派发时的阈值快照存储，不受影响。修改前需二次输入密码确认。
    </el-alert>
    <el-form :model="form" label-width="220px" style="max-width: 560px">
      <el-form-item label="超时时长（小时）">
        <el-input-number v-model="form.timeout_hours" :min="1" :max="720" />
      </el-form-item>
      <el-form-item label="同人循环挂起阈值（次）">
        <el-input-number v-model="form.cycle_threshold" :min="1" :max="20" />
      </el-form-item>
      <el-form-item label="全局重分配挂起阈值（次）">
        <el-input-number v-model="form.global_reassign_threshold" :min="1" :max="50" />
      </el-form-item>
      <el-form-item label="分配候选倍数（待办<平均×倍数）">
        <el-input-number v-model="form.assignment_pending_multiplier" :min="1" :max="10" :step="0.5" />
      </el-form-item>
      <el-form-item label="二次确认密码">
        <el-input v-model="password" type="password" show-password placeholder="请输入您的登录密码" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="saving" @click="save">保存配置</el-button>
      </el-form-item>
    </el-form>
  </el-card>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '@/api'

const loading = ref(false)
const saving = ref(false)
const password = ref('')
const form = reactive({ timeout_hours: 72, cycle_threshold: 3, global_reassign_threshold: 5, assignment_pending_multiplier: 2 })

async function load() {
  loading.value = true
  try {
    const { data } = await http.get('/super/config')
    Object.assign(form, data)
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!password.value) {
    ElMessage.warning('请输入您的登录密码')
    return
  }
  saving.value = true
  try {
    await http.put('/super/config', { ...form, password: password.value })
    ElMessage.success('配置已更新')
    password.value = ''
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.mb {
  margin-bottom: 16px;
}
</style>
