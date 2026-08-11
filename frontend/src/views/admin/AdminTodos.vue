<template>
  <el-card>
    <template #header>
      <div class="head">
        <b>终审待办（再审）</b>
        <div>
          排序：
          <el-radio-group v-model="sort" size="small" @change="load">
            <el-radio-button value="desc">最新优先</el-radio-button>
            <el-radio-button value="asc">最早优先</el-radio-button>
          </el-radio-group>
        </div>
      </div>
    </template>

    <el-table :data="list" v-loading="loading">
      <el-table-column prop="team_name" label="提交团队" />
      <el-table-column label="提交序号" width="110">
        <template #default="{ row }">第 {{ row.submit_round }} 次提交</template>
      </el-table-column>
      <el-table-column label="提交时间">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="初审状态" width="170">
        <template #default="{ row }">
          <span>{{ row.first_review_marker || '-' }}</span>
          <el-tag v-if="row.urgent" type="danger" size="small" class="urgent-tag">即将超时</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="140">
        <template #default="{ row }">
          <el-button link type="primary" @click="$router.push(`/admin/submissions/${row.submission_id}`)">去裁定</el-button>
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
const sort = ref('desc')

async function load() {
  loading.value = true
  try {
    const { data } = await http.get('/admin/todos', { params: { sort: sort.value } })
    list.value = data
  } finally {
    loading.value = false
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
.urgent-tag {
  margin-left: 6px;
}
</style>
