<template>
  <el-card v-loading="loading">
    <template #header><b>初审工单 #{{ detail?.submission_id }}</b></template>

    <template v-if="detail">
      <el-alert v-if="detail.withdrawn_banner" type="warning" :closable="false" class="mb">
        {{ detail.withdrawn_banner }}
      </el-alert>

      <el-descriptions :column="1" border>
        <el-descriptions-item label="提交团队">{{ detail.team_name }}</el-descriptions-item>
        <el-descriptions-item label="提交序号">第 {{ detail.submit_round }} 次提交</el-descriptions-item>
        <el-descriptions-item label="提交时间">{{ formatTime(detail.created_at) }}</el-descriptions-item>
        <el-descriptions-item label="提交人备注">{{ detail.remark || '无' }}</el-descriptions-item>
        <el-descriptions-item label="附件">
          <el-button link type="primary" @click="download">{{ detail.file_stored_name }}</el-button>
        </el-descriptions-item>
        <el-descriptions-item label="我的截止时间">
          {{ formatTime(detail.personal_deadline) }}
          <el-tag v-if="!detail.my_submitted && !detail.is_timeout" type="danger" size="small">请按时完成</el-tag>
        </el-descriptions-item>
      </el-descriptions>

      <el-divider content-position="left">审核操作区</el-divider>
      <p class="hint">材料齐全请点击通过，材料不齐全/错误或存疑请点击不通过</p>
      <el-input v-model="comment" type="textarea" :rows="4" :disabled="detail.my_submitted || detail.is_timeout"
        :placeholder="detail.my_submitted ? '您已提交意见，等待管理员终审；如需修改可撤回后重新提交' : '意见说明（不通过时必填）'" />

      <div class="actions">
        <el-button type="success" :disabled="detail.my_submitted || detail.is_timeout" @click="submitReview(true)">通过</el-button>
        <el-button type="danger" :disabled="detail.my_submitted || detail.is_timeout" @click="submitReview(false)">不通过</el-button>
        <el-button v-if="detail.my_submitted" type="warning" @click="withdrawReview">撤回意见</el-button>
      </div>
    </template>
  </el-card>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api'
import { formatTime } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const detail = ref<any>(null)
const loading = ref(false)
const comment = ref('')

async function load() {
  loading.value = true
  try {
    const { data } = await http.get(`/staff/submissions/${route.params.id}`)
    detail.value = data
    comment.value = ''
  } finally {
    loading.value = false
  }
}

async function download() {
  const resp = await http.get(`/files/${detail.value.submission_id}`, { responseType: 'blob' })
  const url = URL.createObjectURL(resp.data)
  const a = document.createElement('a')
  a.href = url
  a.download = detail.value.file_stored_name
  a.click()
  URL.revokeObjectURL(url)
}

async function submitReview(result: boolean) {
  if (!result && !comment.value.trim()) {
    ElMessage.warning('不通过必须填写意见内容')
    return
  }
  const text = result ? '确认通过该材料吗？' : `确认不通过该材料吗？意见内容：${comment.value.trim()}`
  await ElMessageBox.confirm(text, '二次确认', { type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' })
  await http.post(`/staff/submissions/${detail.value.submission_id}/review`, {
    result,
    comment: comment.value,
    version: detail.value.version,
  })
  ElMessage.success('意见提交成功，已返回待办列表')
  router.push('/staff')
}

async function withdrawReview() {
  await ElMessageBox.confirm('撤回后您可重新提交意见。确认撤回？', '撤回确认', {
    type: 'warning',
    confirmButtonText: '确定',
    cancelButtonText: '取消',
  })
  const { data } = await http.post(`/staff/submissions/${detail.value.submission_id}/withdraw-review`)
  ElMessage.success(data.message)
  load()
}

onMounted(load)
</script>

<style scoped>
.hint {
  color: #606266;
  background: #f0f2f5;
  padding: 8px 12px;
  border-radius: 4px;
  margin-bottom: 12px;
}
.actions {
  margin-top: 16px;
  display: flex;
  gap: 12px;
}
.mb {
  margin-bottom: 16px;
}
</style>
