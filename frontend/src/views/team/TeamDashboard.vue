<template>
  <el-card>
    <template #header>
      <div class="head">
        <b>我的工单</b>
        <el-button type="primary" size="small" @click="$router.push('/team/submit')">提交材料</el-button>
      </div>
    </template>

    <el-table :data="list" v-loading="loading">
      <el-table-column prop="submit_round" label="提交序号" width="90">
        <template #default="{ row }">第 {{ row.submit_round }} 次提交</template>
      </el-table-column>
      <el-table-column label="提交时间">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="状态" width="120">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.status)">{{ row.user_status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="附件">
        <template #default="{ row }">
          <el-button link type="primary" @click="download(row.id, row.file_stored_name)">{{ row.file_stored_name }}</el-button>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200">
        <template #default="{ row }">
          <el-button link type="primary" @click="$router.push(`/team/submissions/${row.id}`)">查看详情</el-button>
          <el-button v-if="row.can_withdraw" link type="danger" @click="onWithdraw(row)">撤回</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api'
import { formatTime, statusTagType } from '@/utils/format'

const list = ref<any[]>([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const { data } = await http.get('/team/submissions')
    list.value = data
  } finally {
    loading.value = false
  }
}

async function download(id: number, name: string) {
  const resp = await http.get(`/files/${id}`, { responseType: 'blob' })
  const url = URL.createObjectURL(resp.data)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
}

async function onWithdraw(row: any) {
  await ElMessageBox.confirm(
    row.status === 'passed'
      ? '确认撤回本次提交吗？撤回后需重新提交材料并重走审核流程，原有审核意见将作废但会留档。'
      : '确认撤回本次提交吗？已完成的审核意见将作废但会留档。',
    '撤回确认',
    { type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' },
  )
  await http.post(`/team/submissions/${row.id}/withdraw`, { version: row.version })
  ElMessage.success('已撤回')
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
</style>
