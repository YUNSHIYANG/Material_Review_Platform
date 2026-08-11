<template>
  <el-card>
    <template #header><b>负载监控面板（审核员与管理员）</b></template>
    <el-table :data="list" v-loading="loading">
      <el-table-column prop="real_name" label="姓名" width="150" />
      <el-table-column label="角色" width="90">
        <template #default="{ row }">
          <el-tag :type="row.role === 'admin' ? 'warning' : 'primary'" size="small">
            {{ row.role === 'admin' ? '管理员' : '审核员' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="当前待办" width="160">
        <template #default="{ row }">
          <div class="bar-row">
            <div class="bar" :style="{ width: barWidth(row.current_pending_count, 'pending'), background: '#409eff' }"></div>
            <span class="bar-val">{{ row.current_pending_count }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="累计完成" width="160">
        <template #default="{ row }">
          <div class="bar-row">
            <div class="bar" :style="{ width: barWidth(row.total_completed_count, 'completed'), background: '#67c23a' }"></div>
            <span class="bar-val">{{ row.total_completed_count }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="timeout_count" label="超时权重" width="100" />
      <el-table-column prop="system_forced_penalty" label="强制惩罚因子" width="120" />
    </el-table>
    <p class="tip">负载不均衡时可结合工单管理主动干预。</p>
  </el-card>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import http from '@/api'

const list = ref<any[]>([])
const loading = ref(false)

function barWidth(value: number, kind: 'pending' | 'completed'): string {
  const max = kind === 'pending' ? 10 : 30
  return `${Math.min(100, (value / max) * 100)}%`
}

async function load() {
  loading.value = true
  try {
    const { data } = await http.get('/super/load')
    list.value = data
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.bar-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.bar {
  height: 14px;
  border-radius: 4px;
  max-width: 180px;
}
.bar-val {
  font-size: 13px;
}
.tip {
  color: #909399;
  font-size: 12px;
  margin-top: 12px;
}
</style>
