<template>
  <el-card v-loading="loading">
    <template #header><b>再审工单 #{{ detail?.submission_id }}</b></template>

    <template v-if="detail">
      <!-- 顶部：工单信息 -->
      <el-descriptions :column="2" border>
        <el-descriptions-item label="提交团队">{{ detail.team_name }}</el-descriptions-item>
        <el-descriptions-item label="提交序号">第 {{ detail.submit_round }} 次提交</el-descriptions-item>
        <el-descriptions-item label="提交时间">{{ formatTime(detail.created_at) }}</el-descriptions-item>
        <el-descriptions-item label="派发时间">{{ formatTime(detail.admin_assigned_at) }}</el-descriptions-item>
        <el-descriptions-item label="备注" :span="2">{{ detail.remark || '无' }}</el-descriptions-item>
        <el-descriptions-item label="附件" :span="2">
          <el-button link type="primary" @click="download">{{ detail.file_stored_name }}</el-button>
        </el-descriptions-item>
      </el-descriptions>

      <el-alert v-if="detail.parent_submission_id" type="warning" :closable="false" class="mt">
        该团队此前有未通过的工单（#{{ detail.parent_submission_id }}），点击展开查看全部历史驳回记录。
        <el-button link type="primary" @click="showHistory = !showHistory">{{ showHistory ? '收起' : '展开' }}</el-button>
        <div v-if="showHistory" class="history">
          <el-table :data="detail.parent_history" size="small">
            <el-table-column label="工单 #ID" prop="id" width="90" />
            <el-table-column label="提交序号" width="110">
              <template #default="{ row }">第 {{ row.submit_round }} 次提交</template>
            </el-table-column>
            <el-table-column label="驳回时间">
              <template #default="{ row }">{{ formatTime(row.rejected_at) }}</template>
            </el-table-column>
            <el-table-column label="驳回意见" prop="admin_comment" />
          </el-table>
        </div>
      </el-alert>

      <!-- 中部：初审意见墙（完全透明） -->
      <el-divider content-position="left">初审意见墙（完成度：{{ detail.completion }}）</el-divider>
      <el-row :gutter="12">
        <el-col v-for="(w, i) in detail.wall" :key="i" :span="12">
          <el-card shadow="never" class="wall-card">
            <template #header>
              <b>{{ w.reviewer_name }}</b>
              <el-tag v-if="w.timeout" type="info" size="small">超时未审</el-tag>
            </template>
            <template v-if="w.hidden || (!w.result && w.result !== false)">
              <el-empty description="该审核员尚未提交意见" :image-size="40" />
            </template>
            <template v-else>
              <el-tag :type="w.result ? 'success' : 'danger'">{{ w.result ? '通过' : '不通过' }}</el-tag>
              <div class="comment">{{ w.comment || '（无文字意见）' }}</div>
              <div class="time">{{ formatTime(w.submitted_at) }}</div>
            </template>
          </el-card>
        </el-col>
      </el-row>

      <!-- 底部：裁定操作区 -->
      <el-divider content-position="left">终审裁定</el-divider>
      <el-input v-model="comment" type="textarea" :rows="4" placeholder="终审意见（驳回时必填）" />
      <div class="actions">
        <el-button type="success" @click="finalize(true)">通过</el-button>
        <el-button type="danger" @click="finalize(false)">驳回</el-button>
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
const showHistory = ref(false)

async function load() {
  loading.value = true
  try {
    const { data } = await http.get(`/admin/submissions/${route.params.id}`)
    detail.value = data
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

async function finalize(result: boolean) {
  if (!result && !comment.value.trim()) {
    ElMessage.warning('驳回必须填写终审意见')
    return
  }
  const text = result ? '确认通过该工单吗？' : '确认驳回该工单吗？'
  await ElMessageBox.confirm(text, '二次确认', { type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' })
  await http.post(`/admin/submissions/${detail.value.submission_id}/review`, {
    final_result: result,
    admin_comment: comment.value,
    version: detail.value.version,
  })
  ElMessage.success('裁定成功')
  router.push('/admin')
}

onMounted(load)
</script>

<style scoped>
.wall-card {
  margin-bottom: 12px;
}
.comment {
  margin-top: 8px;
  color: #606266;
}
.time {
  margin-top: 4px;
  color: #999;
  font-size: 12px;
}
.actions {
  margin-top: 16px;
  display: flex;
  gap: 12px;
}
.mt {
  margin-top: 16px;
}
.history {
  margin-top: 8px;
}
</style>
