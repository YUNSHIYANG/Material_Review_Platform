<template>
  <el-card v-loading="loading">
    <template #header><b>工单详情与干预 #{{ route.params.id }}</b></template>

    <template v-if="detail">
      <el-alert v-if="detail.status === 'pending_admin_intervention'" type="error" :closable="false" class="mb">
        工单 #{{ detail.id }} 已挂起（同人循环 / 全局重分配 / 交替循环 / 管理员不足），请立即人工干预。
      </el-alert>
      <el-alert v-else-if="detail.status === 'returned'" type="warning" :closable="false" class="mb">
        该工单已被超管打回（{{ detail.returned_at ? formatTime(detail.returned_at) : '' }}）。打回意见：{{ detail.return_comment }}
      </el-alert>

      <el-descriptions :column="2" border>
        <el-descriptions-item label="提交团队">{{ detail.team_name }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ statusText(detail.status) }}</el-descriptions-item>
        <el-descriptions-item label="提交序号">第 {{ detail.submit_round }} 次提交</el-descriptions-item>
        <el-descriptions-item label="初审跳过原因">{{ skipReasonText(detail.first_review_skip_reason) }}</el-descriptions-item>
        <el-descriptions-item label="当前管理员">{{ detail.assigned_admin_name || '未派发' }}</el-descriptions-item>
        <el-descriptions-item label="是否已扣减待办">{{ detail.is_admin_pending_deducted ? '是' : '否' }}</el-descriptions-item>
        <el-descriptions-item label="同人循环次数">{{ detail.cycle_count }}</el-descriptions-item>
        <el-descriptions-item label="全局重分配次数">{{ detail.total_reassign_count }}</el-descriptions-item>
        <el-descriptions-item label="派发历史" :span="2">{{ detail.reassign_history_names.join(' → ') || '-' }}</el-descriptions-item>
        <el-descriptions-item label="干预重置次数">{{ detail.intervention_reset_count }}</el-descriptions-item>
        <el-descriptions-item label="附件" :span="2">
          <el-button link type="primary" @click="download">{{ detail.file_stored_name }}</el-button>
        </el-descriptions-item>
      </el-descriptions>

      <el-divider content-position="left">初审记录</el-divider>
      <el-table :data="detail.staff_reviews" size="small">
        <el-table-column prop="reviewer_name" label="审核员" width="110" />
        <el-table-column label="结果" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.is_timeout" type="info" size="small">超时</el-tag>
            <el-tag v-else-if="row.is_withdrawn" type="info" size="small">已撤回</el-tag>
            <span v-else>{{ row.result === null ? '-' : row.result ? '通过' : '不通过' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="comment" label="意见" />
        <el-table-column label="截止时间" width="170">
          <template #default="{ row }">{{ formatTime(row.personal_deadline) }}</template>
        </el-table-column>
      </el-table>

      <div v-if="detail.admin_review" class="mt">
        <el-alert type="success" :closable="false">
          终审裁定：{{ detail.admin_review.final_result ? '通过' : '驳回' }}（
          {{ detail.admin_review.admin_name }}，系统强制：{{ detail.admin_review.is_system_forced ? '是' : '否' }}）
          <div>意见：{{ detail.admin_review.admin_comment }}</div>
        </el-alert>
      </div>

      <el-divider content-position="left">人工干预</el-divider>
      <el-form label-width="120px">
        <el-form-item label="操作">
          <el-radio-group v-model="action">
            <el-radio-button value="force_pass">强制通过</el-radio-button>
            <el-radio-button value="force_reject">强制驳回</el-radio-button>
            <el-radio-button value="reassign">重新派发管理员</el-radio-button>
            <el-radio-button value="supplement">补充初审</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="action === 'force_pass' || action === 'force_reject'" label="终审意见">
          <el-input v-model="comment" type="textarea" :rows="3" placeholder="强制终结的意见（将记录到审计快照）" />
        </el-form-item>
        <el-form-item v-if="action === 'reassign'" label="指定管理员">
          <el-select v-model="newAdminId" clearable placeholder="留空则按双重排序算法自动选择" style="width: 100%">
            <el-option v-for="a in admins" :key="a.id" :label="`${a.real_name}（待办${a.current_pending_count}）`" :value="a.id" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="action === 'supplement'" label="补审审核员">
          <el-select v-model="staffIds" multiple :multiple-limit="2" style="width: 100%">
            <el-option v-for="s in staffs" :key="s.id" :label="`${s.real_name}（待办${s.current_pending_count}）`" :value="s.id" />
          </el-select>
          <div class="tip">系统推荐（按双重排序算法）：{{ recommended.join('、') }}（可覆盖选择）</div>
        </el-form-item>
        <el-form-item label="身份确认">
          <el-input v-model="password" type="password" show-password placeholder="二次输入您的登录密码" />
        </el-form-item>
        <el-form-item>
          <el-button type="danger" :loading="submitting" @click="doIntervene">执行干预</el-button>
        </el-form-item>
      </el-form>

      <template v-if="detail.status === 'passed'">
        <el-divider content-position="left">打回已通过材料</el-divider>
        <el-form label-width="120px">
          <el-form-item label="打回意见">
            <el-input v-model="returnComment" type="textarea" :rows="3" placeholder="必填：说明需要修改的问题，团队将据此重新提交" />
          </el-form-item>
          <el-form-item label="身份确认">
            <el-input v-model="returnPassword" type="password" show-password placeholder="二次输入您的登录密码" />
          </el-form-item>
          <el-form-item>
            <el-button type="warning" :loading="returning" @click="doReturn">打回材料</el-button>
          </el-form-item>
        </el-form>
      </template>
    </template>
  </el-card>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api'
import { formatTime } from '@/utils/format'

const route = useRoute()
const detail = ref<any>(null)
const loading = ref(false)
const submitting = ref(false)
const action = ref('force_pass')
const comment = ref('')
const password = ref('')
const returnComment = ref('')
const returnPassword = ref('')
const returning = ref(false)
const newAdminId = ref<number | undefined>()
const staffIds = ref<number[]>([])
const admins = ref<any[]>([])
const staffs = ref<any[]>([])
const recommended = ref<number[]>([])

function statusText(s: string) {
  return (
    {
      pending: '待分配',
      first_reviewing: '初审中',
      admin_reviewing: '再审中',
      pending_admin_intervention: '待超管介入',
      passed: '已通过',
      rejected: '未通过',
      returned: '已打回',
      withdrawn: '已撤回',
    }[s] || s
  )
}

function skipReasonText(reason: string | null) {
  return (
    {
      timeout: '初审员审核超时，已转交管理员复核',
      insufficient_staff: '初审审核员不足，直接进入管理员终审',
    }[reason || ''] || '正常'
  )
}

async function load() {
  loading.value = true
  try {
    const { data } = await http.get(`/super/submissions/${route.params.id}`)
    detail.value = data
  } finally {
    loading.value = false
  }
  const [{ data: u }, { data: r }] = await Promise.all([
    http.get('/super/users'),
    http.get(`/super/submissions/${route.params.id}/recommend-staff`),
  ])
  admins.value = u.filter((x: any) => x.role === 'admin')
  staffs.value = u.filter((x: any) => x.role === 'staff')
  recommended.value = r.recommended_ids
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

async function doIntervene() {
  if (!password.value) {
    ElMessage.warning('请输入您的登录密码进行身份确认')
    return
  }
  const payload: any = {
    action: action.value === 'supplement' ? 'supplement_first_review' : action.value,
    version: detail.value.version,
    password: password.value,
    comment: comment.value,
  }
  if (action.value === 'reassign') payload.new_admin_id = newAdminId.value
  if (action.value === 'supplement') payload.staff_ids = staffIds.value

  const confirmText =
    action.value === 'force_pass'
      ? '强制通过该工单？（工作量不计入任何人）'
      : action.value === 'force_reject'
        ? '强制驳回该工单？（工作量不计入任何人）'
        : action.value === 'reassign'
          ? '确认重新派发管理员？（将重置循环计数器）'
          : '确认指定2名审核员补充初审？'
  await ElMessageBox.confirm(confirmText, '干预确认', { type: 'warning' })
  submitting.value = true
  try {
    await http.post(`/super/submissions/${detail.value.id}/intervene`, payload)
    ElMessage.success('干预成功')
    load()
  } finally {
    submitting.value = false
  }
}

async function doReturn() {
  if (!returnComment.value.trim()) {
    ElMessage.warning('请填写打回意见')
    return
  }
  if (!returnPassword.value) {
    ElMessage.warning('请输入您的登录密码进行身份确认')
    return
  }
  await ElMessageBox.confirm(
    '确认打回该已通过材料？团队将收到打回意见并需重新提交、重走审核流程，原有工作量计数将回退。',
    '打回确认',
    { type: 'warning', confirmButtonText: '打回', cancelButtonText: '取消' },
  )
  returning.value = true
  try {
    await http.post(`/super/submissions/${detail.value.id}/return`, {
      comment: returnComment.value,
      password: returnPassword.value,
      version: detail.value.version,
    })
    ElMessage.success('已打回')
    load()
  } finally {
    returning.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.mb {
  margin-bottom: 16px;
}
.mt {
  margin-top: 16px;
}
.tip {
  color: #909399;
  font-size: 12px;
  margin-top: 4px;
}
</style>
