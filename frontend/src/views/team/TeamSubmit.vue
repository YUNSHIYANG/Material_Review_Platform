<template>
  <el-card>
    <template #header><b>提交审核材料</b></template>

    <el-alert v-if="rejectHint" type="warning" :closable="false" class="mb">
      检测到您此前提交的工单（#{{ rejectHint.id }}）未通过，管理员可在此次新提交中查看历史驳回记录。
    </el-alert>

    <el-form label-width="100px">
      <el-form-item label="材料附件" required>
        <el-upload drag :auto-upload="false" :limit="1" :on-change="onFileChange" :on-remove="onFileRemove"
          accept=".zip,.rar,.7z,.tar,.gz,.tgz" class="uploader">
          <div class="upload-hint">
            <el-icon size="40"><UploadFilled /></el-icon>
            <div>将压缩包拖到此处，或 <em>点击选择文件</em></div>
            <div class="sub">支持 .zip / .rar / .7z / .tar.gz / .tgz 等，单文件不超过 50MB</div>
          </div>
        </el-upload>
        <div v-if="selectedFile" class="file-name">已选择：{{ selectedFile.name }}</div>
      </el-form-item>
      <el-form-item label="说明备注">
        <el-input v-model="remark" type="textarea" :rows="4" placeholder="可选，用于补充说明本次提交背景" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="submitting" @click="onSubmit">提交</el-button>
        <el-button @click="$router.push('/team')">返回</el-button>
      </el-form-item>
    </el-form>
  </el-card>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import http from '@/api'

const router = useRouter()
const remark = ref('')
const selectedFile = ref<File | null>(null)
const submitting = ref(false)
const rejectHint = ref<{ id: number } | null>(null)

function onFileChange(file: any) {
  selectedFile.value = file.raw
}
function onFileRemove() {
  selectedFile.value = null
}

async function onSubmit() {
  if (!selectedFile.value) {
    ElMessage.warning('请选择材料附件')
    return
  }
  submitting.value = true
  const fd = new FormData()
  fd.append('file', selectedFile.value)
  fd.append('remark', remark.value)
  try {
    const { data } = await http.post('/team/submissions', fd)
    ElMessage.success('提交成功')
    router.push('/team')
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  const { data } = await http.get('/team/submissions')
  // 最近一次提交为“未通过”时提示关联追溯
  if (data.length) {
    const last = data[0]
    if (last.status === 'rejected') rejectHint.value = { id: last.id }
  }
})
</script>

<style scoped>
.uploader {
  width: 100%;
}
.upload-hint {
  padding: 8px 0;
}
.sub {
  color: #999;
  font-size: 12px;
}
.file-name {
  color: #606266;
  margin-top: 8px;
}
.mb {
  margin-bottom: 16px;
}
</style>
