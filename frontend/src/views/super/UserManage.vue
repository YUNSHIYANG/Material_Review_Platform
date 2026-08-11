<template>
  <el-card>
    <template #header>
      <div class="head">
        <b>用户管理</b>
        <div>
          <el-radio-group v-model="roleFilter" size="small" @change="load">
            <el-radio-button value="">全部</el-radio-button>
            <el-radio-button value="team">提交人</el-radio-button>
            <el-radio-button value="staff">审核员</el-radio-button>
            <el-radio-button value="admin">管理员</el-radio-button>
            <el-radio-button value="super_admin">超管</el-radio-button>
          </el-radio-group>
          <el-button type="primary" size="small" class="ml" @click="openCreate">新建用户</el-button>
          <el-button size="small" class="ml" @click="downloadTemplate">下载导入模板</el-button>
          <el-upload :show-file-list="false" :http-request="doImport" accept=".xlsx" class="ml-upload">
            <el-button size="small" type="success">导入Excel</el-button>
          </el-upload>
          <el-button size="small" type="warning" class="ml" @click="exportAccounts">导出账密</el-button>
        </div>
      </div>
    </template>

    <el-table :data="list" v-loading="loading" @sort-change="onSortChange">
      <el-table-column prop="username" label="用户名" width="130" sortable="custom" />
      <el-table-column prop="role" label="角色" width="100" sortable="custom">
        <template #default="{ row }">{{ roleText(row.role) }}</template>
      </el-table-column>
      <el-table-column prop="real_name" label="姓名/团队" sortable="custom" />
      <el-table-column prop="student_id" label="学工号" width="110" sortable="custom" />
      <el-table-column prop="email" label="邮箱" sortable="custom" />
      <el-table-column prop="current_pending_count" label="待办/完成" width="110" sortable="custom">
        <template #default="{ row }">{{ row.current_pending_count }} / {{ row.total_completed_count }}</template>
      </el-table-column>
      <el-table-column label="锁定" width="80">
        <template #default="{ row }">
          <el-tag v-if="row.locked_until" type="danger" size="small">锁定中</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="260">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button v-if="row.locked_until" link type="warning" @click="unlock(row)">解锁</el-button>
          <el-button link type="danger" @click="resetPwd(row)">重置密码</el-button>
          <el-button link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="editing ? '编辑用户' : '新建用户'" width="640px">
      <el-form :model="form" label-width="120px">
        <el-form-item label="用户名" required>
          <el-input v-model="form.username" :disabled="!!editing" />
        </el-form-item>
        <el-form-item label="角色" required>
          <el-select v-model="form.role" style="width: 100%" :disabled="!!editing">
            <el-option label="提交人（团队）" value="team" />
            <el-option label="审核员" value="staff" />
            <el-option label="管理员" value="admin" />
            <el-option label="超级管理员" value="super_admin" />
          </el-select>
        </el-form-item>
        <el-form-item label="姓名/团队名" required>
          <el-input v-model="form.real_name" :placeholder="form.role === 'team' ? '团队名称' : '真实姓名'" />
        </el-form-item>
        <el-form-item v-if="form.role !== 'team'" label="学工号" required>
          <el-input v-model="form.student_id" />
        </el-form-item>
        <el-form-item label="邮箱" required>
          <el-input v-model="form.email" placeholder="通知邮箱" />
        </el-form-item>
        <template v-if="form.role === 'team'">
          <el-form-item label="成员姓名" required>
            <el-input v-model="membersText" type="textarea" :rows="2" placeholder="JSON数组，如 [&quot;张三&quot;,&quot;李四&quot;]" />
          </el-form-item>
          <el-form-item label="成员学工号" required>
            <el-input v-model="sidsText" type="textarea" :rows="2" placeholder="JSON数组，与姓名一一对应，如 [&quot;2024001&quot;,&quot;2024002&quot;]" />
          </el-form-item>
        </template>
        <el-form-item v-if="!editing" label="初始密码">
          <el-input v-model="form.password" placeholder="留空则由系统生成8位临时密码" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="importVisible" title="导入结果" width="640px">
      <el-alert type="success" :closable="false" :title="`成功导入 ${importCreated} 个用户`" class="mb" />
      <el-alert v-if="importErrors.length" type="error" :closable="false" title="以下行导入失败（已跳过，不影响其他行）" class="mb" />
      <el-table v-if="importErrors.length" :data="importErrors" size="small" max-height="300">
        <el-table-column prop="row" label="行号" width="70" />
        <el-table-column prop="username" label="用户名" width="150" />
        <el-table-column prop="error" label="失败原因" />
      </el-table>
      <template #footer>
        <el-button @click="importVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadRequestOptions } from 'element-plus'
import http from '@/api'

const list = ref<any[]>([])
const loading = ref(false)
const roleFilter = ref('')
const dialogVisible = ref(false)
const editing = ref<any>(null)
const membersText = ref('')
const sidsText = ref('')
const importVisible = ref(false)
const importCreated = ref(0)
const importErrors = ref<any[]>([])
const form = reactive({
  username: '',
  role: 'team',
  real_name: '',
  student_id: '',
  email: '',
  password: '',
})

function roleText(r: string) {
  return { team: '提交人', staff: '审核员', admin: '管理员', super_admin: '超管' }[r] || r
}

// 除时间外均支持排序：本地排序（用户名/角色/姓名/学工号/邮箱/待办数）
function onSortChange({ prop, order }: { prop: string; order: 'ascending' | 'descending' | null }) {
  if (!prop || !order) {
    load() // 取消排序时恢复服务端默认顺序
    return
  }
  const dir = order === 'ascending' ? 1 : -1
  list.value = [...list.value].sort((a, b) => {
    const av = a[prop]
    const bv = b[prop]
    if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir
    return String(av ?? '').localeCompare(String(bv ?? ''), 'zh-Hans-CN') * dir
  })
}

async function load() {
  loading.value = true
  try {
    const { data } = await http.get('/super/users', { params: { role: roleFilter.value || undefined } })
    list.value = data
  } finally {
    loading.value = false
  }
}

function parseJsonArray(text: string, field: string): string[] | null {
  try {
    const v = JSON.parse(text)
    if (!Array.isArray(v)) throw new Error()
    return v
  } catch {
    ElMessage.error(`${field} 必须是JSON数组格式`)
    return null
  }
}

function openCreate() {
  editing.value = null
  Object.assign(form, { username: '', role: 'team', real_name: '', student_id: '', email: '', password: '' })
  membersText.value = ''
  sidsText.value = ''
  dialogVisible.value = true
}

function openEdit(row: any) {
  editing.value = row
  Object.assign(form, {
    username: row.username,
    role: row.role,
    real_name: row.real_name || '',
    student_id: row.student_id || '',
    email: row.email || '',
    password: '',
  })
  membersText.value = JSON.stringify(row.member_names || [])
  sidsText.value = JSON.stringify(row.member_student_ids || [])
  dialogVisible.value = true
}

async function save() {
  const payload: any = {
    username: form.username,
    role: form.role,
    real_name: form.real_name,
    student_id: form.student_id,
    email: form.email,
  }
  if (form.role === 'team') {
    const names = parseJsonArray(membersText.value, '成员姓名')
    const sids = parseJsonArray(sidsText.value, '成员学工号')
    if (!names || !sids) return
    payload.member_names = names
    payload.member_student_ids = sids
  }
  if (!editing.value) payload.password = form.password
  if (editing.value) {
    await http.put(`/super/users/${editing.value.id}`, payload)
    ElMessage.success('更新成功')
  } else {
    const { data } = await http.post('/super/users', payload)
    if (data.temp_password) {
      ElMessageBox.alert(`临时密码：${data.temp_password}`, '创建成功，请记录并告知用户', { type: 'warning' })
    } else {
      ElMessage.success('创建成功')
    }
  }
  dialogVisible.value = false
  load()
}

async function unlock(row: any) {
  await http.post(`/super/users/${row.id}/unlock`)
  ElMessage.success('已解锁')
  load()
}

async function resetPwd(row: any) {
  const { value } = await ElMessageBox.prompt('请二次输入您的登录密码以确认身份', '重置密码', {
    inputType: 'password',
    confirmButtonText: '确认',
    cancelButtonText: '取消',
  })
  const { data } = await http.post(`/super/users/${row.id}/reset-password`, { password: value })
  ElMessageBox.alert(`新临时密码：${data.temp_password}`, '密码已重置', { type: 'warning' })
}

async function remove(row: any) {
  await ElMessageBox.confirm(`确认删除用户 ${row.username} 吗？（软删除）`, '删除确认', { type: 'warning' })
  await http.delete(`/super/users/${row.id}`)
  ElMessage.success('已删除')
  load()
}

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

async function downloadTemplate() {
  const resp = await http.get('/super/users/template', { responseType: 'blob' })
  saveBlob(resp.data, '用户导入模板.xlsx')
}

async function exportAccounts() {
  await ElMessageBox.confirm('确认导出全部用户账号与密码？请妥善保管导出的文件。', '导出账密', {
    type: 'warning',
    confirmButtonText: '导出',
    cancelButtonText: '取消',
  })
  const resp = await http.get('/super/users/export', { responseType: 'blob' })
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  saveBlob(resp.data, `账号密码导出_${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}.xlsx`)
  ElMessage.success('已导出账密文件')
}

async function doImport(options: UploadRequestOptions) {
  const fd = new FormData()
  fd.append('file', options.file)
  try {
    const { data } = await http.post('/super/users/import', fd)
    importCreated.value = data.created_count
    importErrors.value = data.errors || []
    importVisible.value = true
    load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '导入失败，请检查文件格式')
  }
}

onMounted(load)
</script>

<style scoped>
.head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.ml {
  margin-left: 12px;
}
.ml-upload {
  display: inline-block;
  margin-left: 12px;
}
.mb {
  margin-bottom: 12px;
}
</style>
