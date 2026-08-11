<template>
  <el-card>
    <template #header>
      <div class="head">
        <b>邮件日志</b>
        <el-button size="small" @click="load">刷新</el-button>
      </div>
    </template>
    <el-table :data="list" v-loading="loading">
      <el-table-column prop="id" label="#ID" width="60" />
      <el-table-column prop="recipient" label="收件人" width="200" show-overflow-tooltip />
      <el-table-column prop="subject" label="主题" min-width="340" show-overflow-tooltip />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.status === 'success' ? 'success' : row.status === 'pending' ? 'warning' : 'danger'" size="small">
            {{ row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="retry_count" label="尝试次数" width="80" />
      <el-table-column prop="submission_id" label="工单" width="70" />
      <el-table-column label="创建/发送" width="200">
        <template #default="{ row }">
          <div>{{ formatTime(row.created_at) }}</div>
          <div class="sub">{{ formatTime(row.sent_at) }}</div>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="90">
        <template #default="{ row }">
          <el-button v-if="row.status === 'failed'" link type="danger" @click="resend(row)">重发</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '@/api'
import { formatTime } from '@/utils/format'

const list = ref<any[]>([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const { data } = await http.get('/super/emails')
    list.value = data
  } finally {
    loading.value = false
  }
}

async function resend(row: any) {
  const { data } = await http.post(`/super/emails/${row.id}/resend`)
  ElMessage[data.ok ? 'success' : 'error'](data.message)
  load()
}

onMounted(load)
</script>

<style scoped>
.head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.sub {
  color: #999;
  font-size: 12px;
}
</style>
