<template>
  <el-card>
    <template #header>
      <div class="head">
        <b>全部工单管理</b>
        <div class="tools">
          <el-input v-model="keyword" size="small" placeholder="搜索团队名 / #ID" clearable style="width: 200px" />
          <el-select v-model="statusFilter" size="small" clearable placeholder="状态" style="width: 160px" @change="load">
            <el-option label="待分配" value="pending" />
            <el-option label="初审中" value="first_reviewing" />
            <el-option label="再审中" value="admin_reviewing" />
            <el-option label="待超管介入" value="pending_admin_intervention" />
            <el-option label="已通过" value="passed" />
            <el-option label="未通过" value="rejected" />
            <el-option label="已打回" value="returned" />
            <el-option label="已撤回" value="withdrawn" />
          </el-select>
          <el-select v-model="downloadStatus" size="small" style="width: 160px" placeholder="下载筛选">
            <el-option label="全部阶段材料" value="" />
            <el-option label="仅已通过材料" value="passed" />
          </el-select>
          <el-button size="small" type="primary" :loading="downloading" @click="downloadAll">下载全部材料(zip)</el-button>
          <el-button size="small" class="ml" @click="load">刷新</el-button>
        </div>
      </div>
    </template>

    <el-table :data="filteredList" v-loading="loading" @sort-change="onSortChange">
      <el-table-column prop="id" label="#ID" width="70" sortable="custom" />
      <el-table-column prop="team_name" label="提交团队" sortable="custom" />
      <el-table-column prop="submit_round" label="提交序号" width="110" sortable="custom">
        <template #default="{ row }">第 {{ row.submit_round }} 次提交</template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="110" sortable="custom">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.status)">{{ statusText(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="提交时间" sortable="custom">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="重分配" width="80">
        <template #default="{ row }">{{ row.total_reassign_count }}次</template>
      </el-table-column>
      <el-table-column label="操作" width="130">
        <template #default="{ row }">
          <el-button link type="primary" @click="$router.push(`/super/submissions/${row.id}`)">查看/干预</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api'
import { formatTime, statusTagType } from '@/utils/format'

const list = ref<any[]>([])
const loading = ref(false)
const statusFilter = ref('')
const keyword = ref('')

const filteredList = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return list.value
  return list.value.filter((r: any) =>
    String(r.team_name || '').toLowerCase().includes(kw) || String(r.id).includes(kw),
  )
})

// 本地排序：与用户管理一致（#ID/团队名/序号/状态/提交时间）
function onSortChange({ prop, order }: { prop: string; order: 'ascending' | 'descending' | null }) {
  if (!prop || !order) return
  const dir = order === 'ascending' ? 1 : -1
  list.value = [...list.value].sort((a, b) => {
    const av = a[prop]
    const bv = b[prop]
    if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir
    return String(av ?? '').localeCompare(String(bv ?? ''), 'zh-Hans-CN') * dir
  })
}
const downloadStatus = ref('')
const downloading = ref(false)

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

async function load() {
  loading.value = true
  try {
    const { data } = await http.get('/super/submissions', {
      params: { status: statusFilter.value || undefined },
    })
    list.value = data
  } finally {
    loading.value = false
  }
}

async function downloadAll() {
  const label = downloadStatus.value ? '仅已通过材料' : '全部阶段材料'
  await ElMessageBox.confirm(
    `确认打包下载${label}？（每支队伍仅取最新一次提交，按团队名称分目录）`,
    '批量下载',
    { type: 'warning', confirmButtonText: '下载', cancelButtonText: '取消' },
  )
  downloading.value = true
  try {
    const resp = await http.get('/super/submissions/download', {
      params: { status: downloadStatus.value || undefined },
      responseType: 'blob',
    })
    const url = URL.createObjectURL(resp.data)
    const a = document.createElement('a')
    a.href = url
    a.download = `materials_${new Date().toISOString().slice(0, 19).replace(/[-:T]/g, '')}.zip`
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('打包下载已开始')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '下载失败')
  } finally {
    downloading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.tools {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.ml {
  margin-left: 4px;
}
</style>
