<template>
  <el-card>
    <template #header><b>我的待办（初审）</b></template>
    <el-table :data="list" v-loading="loading">
      <el-table-column prop="team_name" label="提交团队" />
      <el-table-column label="提交序号" width="110">
        <template #default="{ row }">第 {{ row.submit_round }} 次提交</template>
      </el-table-column>
      <el-table-column label="提交时间">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="截止时间" width="200">
        <template #default="{ row }">
          <span :class="{ urgent: row.urgent }">{{ formatTime(row.personal_deadline) }}</span>
          <el-tag v-if="row.urgent" type="danger" size="small" class="urgent-tag">即将超时</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="140">
        <template #default="{ row }">
          <el-button link type="primary" @click="$router.push(`/staff/submissions/${row.submission_id}`)">去审核</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import http from '@/api'
import { formatTime } from '@/utils/format'

const list = ref<any[]>([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const { data } = await http.get('/staff/todos')
    list.value = data
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.urgent {
  color: #f56c6c;
  font-weight: 600;
}
.urgent-tag {
  margin-left: 6px;
}
</style>
