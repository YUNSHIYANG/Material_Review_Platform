<template>
  <div>
    <el-card class="mb" v-loading="loading">
      <template #header><b>后台概览</b></template>
      <el-alert
        v-if="!smtpConfigured"
        class="mb"
        type="warning"
        :closable="false"
        title="邮件服务未配置"
        description="系统当前未配置 SMTP 邮箱，所有通知邮件（任务指派/审核结果/告警）将发送失败。请在服务器环境变量中配置 SMTP_HOST、SMTP_PORT、SMTP_USER、SMTP_PASSWORD、MAIL_FROM 后重启服务。"
      />
      <el-row :gutter="16">
        <el-col v-for="(cnt, st) in statusCounts" :key="st" :span="4">
          <el-statistic :title="statusLabel(st)" :value="cnt" />
        </el-col>
      </el-row>
    </el-card>

    <el-card>
      <template #header>
        <b class="red">待超管介入工单（红色告警）</b>
      </template>
      <el-table :data="pendingIntervention">
        <el-table-column prop="id" label="工单 #ID" width="90" />
        <el-table-column prop="team_name" label="提交团队" />
        <el-table-column label="提交序号" width="110">
          <template #default="{ row }">第 {{ row.submit_round }} 次提交</template>
        </el-table-column>
        <el-table-column label="挂起原因" width="240">
          <template #default="{ row }">
            <span v-if="row.total_reassign_count >= 5">全局重分配耗尽（{{ row.total_reassign_count }}次）</span>
            <span v-else-if="row.cycle_count >= 3">同人循环（{{ row.cycle_count }}次）</span>
            <span v-else>交替循环/管理员不足</span>
          </template>
        </el-table-column>
        <el-table-column label="派发历史">
          <template #default="{ row }">{{ row.reassign_history_names.join(' → ') }}</template>
        </el-table-column>
        <el-table-column label="操作" width="140">
          <template #default="{ row }">
            <el-button type="danger" size="small" @click="$router.push(`/super/submissions/${row.id}`)">人工干预</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!pendingIntervention.length" description="暂无待超管介入工单" />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import http from '@/api'

const loading = ref(false)
const pendingIntervention = ref<any[]>([])
const statusCounts = ref<Record<string, number>>({})
const smtpConfigured = ref(true)

function statusLabel(st: string): string {
  const map: Record<string, string> = {
    pending: '待分配',
    first_reviewing: '初审中',
    admin_reviewing: '再审中',
    pending_admin_intervention: '待超管介入',
    passed: '已通过',
    rejected: '未通过',
    returned: '已打回',
    withdrawn: '已撤回',
  }
  return map[st] || st
}

async function load() {
  loading.value = true
  try {
    const { data } = await http.get('/super/dashboard')
    pendingIntervention.value = data.pending_intervention
    const allStatus = [
      'pending', 'first_reviewing', 'admin_reviewing', 'pending_admin_intervention',
      'passed', 'rejected', 'returned', 'withdrawn',
    ]
    const counts = data.status_counts || {}
    // 各阶段始终显示，0 就显示 0，不隐藏
    statusCounts.value = Object.fromEntries(allStatus.map((s) => [s, counts[s] ?? 0]))
    smtpConfigured.value = data.smtp_configured
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.red {
  color: #f56c6c;
}
.mb {
  margin-bottom: 16px;
}
</style>
