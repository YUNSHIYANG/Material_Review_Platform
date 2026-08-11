<template>
  <el-card>
    <template #header><b>超管操作审计日志</b></template>
    <el-table :data="list" v-loading="loading">
      <el-table-column prop="id" label="#ID" width="70" />
      <el-table-column label="操作时间" width="170">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作类型" width="200">
        <template #default="{ row }">{{ opText(row.operation_type) }}</template>
      </el-table-column>
      <el-table-column prop="target_submission_id" label="工单" width="80" />
      <el-table-column prop="target_user_id" label="目标用户" width="90" />
      <el-table-column prop="remark" label="备注" min-width="200" show-overflow-tooltip />
      <el-table-column prop="ip_address" label="IP" width="130" />
    </el-table>
  </el-card>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import http from '@/api'
import { formatTime } from '@/utils/format'

const list = ref<any[]>([])
const loading = ref(false)

function opText(t: string) {
  return (
    {
      RESET_PWD: '重置密码',
      INTERVENE: '干预工单',
      CONFIG_UPDATE: '修改系统配置',
      EXPORT_ACCOUNTS: '导出账密',
      IMPORT_USERS: '批量导入用户',
      MANUAL_UNLOCK: '手动解锁',
      RETURN_PASSED: '打回已通过材料',
      EXPORT_MATERIALS: '批量下载材料',
    }[t] || t
  )
}

async function load() {
  loading.value = true
  try {
    const { data } = await http.get('/super/audit-logs')
    list.value = data
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>
