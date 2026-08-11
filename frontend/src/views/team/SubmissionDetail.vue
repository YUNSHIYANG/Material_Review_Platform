<template>
  <el-card v-loading="loading">
    <template #header>
      <div class="head">
        <b>工单详情 #{{ detail?.id }}</b>
        <el-tag v-if="detail" :type="statusTagType(detail.status)">{{ detail.user_status }}</el-tag>
      </div>
    </template>

    <template v-if="detail">
      <el-alert v-if="detail.pending_admin_intervention_note" type="warning" :closable="false" class="mb">
        {{ detail.pending_admin_intervention_note }}
      </el-alert>
      <el-alert v-else-if="detail.returned_note" type="danger" :closable="false" class="mb">
        {{ detail.returned_note }}
      </el-alert>
      <el-alert v-else-if="detail.first_review_skip_hint" type="info" :closable="false" class="mb gray">
        {{ detail.first_review_skip_hint }}
      </el-alert>

      <el-descriptions :column="1" border>
        <el-descriptions-item label="提交序号">第 {{ detail.submit_round }} 次提交</el-descriptions-item>
        <el-descriptions-item label="提交时间">{{ formatTime(detail.created_at) }}</el-descriptions-item>
        <el-descriptions-item label="附件">
          <el-button link type="primary" @click="download">{{ detail.file_stored_name }}</el-button>
        </el-descriptions-item>
        <el-descriptions-item label="备注">{{ detail.remark || '无' }}</el-descriptions-item>
        <el-descriptions-item v-if="detail.withdrawn_at" label="撤回时间">{{ formatTime(detail.withdrawn_at) }}</el-descriptions-item>
      </el-descriptions>

      <el-divider content-position="left">审核反馈</el-divider>
      <template v-if="detail.review_chain && detail.review_chain.length">
        <el-timeline>
          <el-timeline-item v-for="(item, i) in detail.review_chain" :key="i" :type="item.result ? 'success' : 'danger'">
            <div><b>{{ item.reviewer_label }}</b>：{{ resultText(item.result) }}</div>
            <div v-if="item.comment" class="comment">{{ item.comment }}</div>
            <div class="time">{{ formatTime(item.submitted_at) }}</div>
          </el-timeline-item>
        </el-timeline>
      </template>
      <el-empty v-else description="暂无审核反馈（审核完成后可见）" />

      <div class="actions">
        <el-button v-if="detail.can_withdraw" type="danger" @click="onWithdraw">撤回本次提交</el-button>
        <span v-if="detail.status === 'passed'" class="withdraw-hint">已通过材料撤回后将重新进入审核流程</span>
        <el-button @click="$router.push('/team')">返回</el-button>
      </div>
    </template>
  </el-card>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api'
import { formatTime, resultText, statusTagType } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const detail = ref<any>(null)
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const { data } = await http.get(`/team/submissions/${route.params.id}`)
    detail.value = data
  } finally {
    loading.value = false
  }
}

async function download() {
  const resp = await http.get(`/files/${detail.value.id}`, { responseType: 'blob' })
  const url = URL.createObjectURL(resp.data)
  const a = document.createElement('a')
  a.href = url
  a.download = detail.value.file_stored_name
  a.click()
  URL.revokeObjectURL(url)
}

async function onWithdraw() {
  const isPassed = detail.value.status === 'passed'
  await ElMessageBox.confirm(
    isPassed
      ? '确认撤回本次提交吗？撤回后需重新提交材料并重走审核流程，原有审核意见将作废但会留档。'
      : '确认撤回本次提交吗？已完成的审核意见将作废但会留档。',
    '撤回确认',
    { type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' },
  )
  await http.post(`/team/submissions/${detail.value.id}/withdraw`, { version: detail.value.version })
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
.mb {
  margin-bottom: 16px;
}
.gray :deep(.el-alert__description) {
  color: #999;
  font-size: 12px;
}
.comment {
  color: #606266;
}
.time {
  color: #999;
  font-size: 12px;
}
.actions {
  margin-top: 20px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.withdraw-hint {
  color: #e6a23c;
  font-size: 12px;
}
</style>
