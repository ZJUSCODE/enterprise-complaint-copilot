<template>
  <div class="document-manager">
    <header class="dm-header">
      <div>
        <p class="eyebrow">知识库管理</p>
        <h2>文档处理中心</h2>
        <p>上传、解析、管理企业文档，支持 PDF、Word、Excel、图片格式。</p>
      </div>
      <StatusBadge :label="loading ? '加载中...' : `${documents.length} 个文档`" :tone="loading ? 'warn' : 'ok'" />
    </header>

    <!-- Upload Section -->
    <div class="dm-upload">
      <el-upload
        drag
        :auto-upload="false"
        :on-change="handleFileSelect"
        :show-file-list="false"
        accept=".pdf,.docx,.doc,.xlsx,.xls,.png,.jpg,.jpeg,.bmp,.tiff"
      >
        <div class="upload-area">
          <p><strong>拖拽文件到此处</strong></p>
          <p>或点击选择文件 · 支持 PDF / Word / Excel / 图片</p>
        </div>
      </el-upload>
      <div v-if="selectedFile" class="upload-actions">
        <span>{{ selectedFile.name }} ({{ formatSize(selectedFile.size) }})</span>
        <el-button type="primary" size="small" :loading="uploading" @click="uploadFile">上传并解析</el-button>
        <el-button size="small" @click="selectedFile = null">取消</el-button>
      </div>
    </div>

    <!-- Upload Result -->
    <div v-if="uploadResult" class="dm-result">
      <p><strong>{{ uploadResult.filename }}</strong> 解析完成</p>
      <p>解析段落: {{ uploadResult.sections_parsed }} · 清洗后: {{ uploadResult.sections_after_cleaning }} · 分块: {{ uploadResult.chunks_created }}</p>
    </div>

    <!-- Document List -->
    <div class="dm-list">
      <div class="dm-list-header">
        <h3>已索引文档</h3>
        <el-button size="small" @click="refreshDocuments">刷新</el-button>
      </div>
      <el-table :data="documents" stripe size="small" max-height="400">
        <el-table-column prop="filename" label="文件名" min-width="200" />
        <el-table-column prop="extension" label="类型" width="80">
          <template #default="{ row }">
            <el-tag size="small">{{ row.extension }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="100">
          <template #default="{ row }">{{ formatSize(row.size_bytes) }}</template>
        </el-table-column>
        <el-table-column label="更新时间" width="180">
          <template #default="{ row }">{{ formatDate(row.modified_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="viewLineage(row.filename)">溯源</el-button>
            <el-popconfirm title="确认删除？" @confirm="removeDocument(row.filename)">
              <template #reference>
                <el-button size="small" type="danger">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- Lineage Dialog -->
    <el-dialog v-model="lineageVisible" title="文档溯源" width="700px">
      <div v-if="lineageData">
        <p><strong>{{ lineageData.filename }}</strong> · {{ lineageData.chunks }} 个分块</p>
        <el-collapse>
          <el-collapse-item v-for="item in lineageData.lineages" :key="item.chunk_id" :title="item.chunk_id">
            <p>来源: {{ item.source_section || '(无标题)' }} · 第{{ item.source_page || '?' }}页</p>
            <p>创建: {{ formatDate(item.created_at) }}</p>
            <div v-for="step in item.processing_steps" :key="step.step_name" class="lineage-step">
              <el-tag size="small">{{ step.step_name }}</el-tag>
              <span>{{ formatDate(step.timestamp) }} · {{ step.duration_ms.toFixed(1) }}ms</span>
            </div>
          </el-collapse-item>
        </el-collapse>
      </div>
    </el-dialog>

    <!-- Version Management -->
    <div class="dm-versions">
      <div class="dm-list-header">
        <h3>版本管理</h3>
        <div>
          <el-button size="small" :loading="creatingVersion" @click="createSnapshot">创建快照</el-button>
          <el-button size="small" @click="refreshVersions">刷新</el-button>
        </div>
      </div>
      <el-table :data="versions" stripe size="small" max-height="300">
        <el-table-column prop="version_id" label="版本" width="160" />
        <el-table-column prop="branch" label="分支" width="100" />
        <el-table-column prop="message" label="说明" min-width="200" />
        <el-table-column prop="chunk_count" label="分块数" width="80" />
        <el-table-column prop="author" label="作者" width="100" />
        <el-table-column label="时间" width="180">
          <template #default="{ row }">{{ formatDate(row.timestamp) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-popconfirm title="确认回滚到此版本？" @confirm="doRollback(row.version_id)">
              <template #reference>
                <el-button size="small" type="warning">回滚</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- Audit Log -->
    <div class="dm-audit">
      <div class="dm-list-header">
        <h3>审计日志</h3>
        <el-button size="small" @click="refreshAudit">刷新</el-button>
      </div>
      <el-table :data="auditEvents" stripe size="small" max-height="300">
        <el-table-column prop="event_id" label="事件ID" width="140" />
        <el-table-column prop="category" label="类别" width="80">
          <template #default="{ row }">
            <el-tag :type="categoryTagType(row.category)" size="small">{{ row.category }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="action" label="操作" width="120" />
        <el-table-column prop="actor" label="执行者" width="100" />
        <el-table-column prop="target" label="目标" min-width="150" />
        <el-table-column prop="result" label="结果" width="80">
          <template #default="{ row }">
            <el-tag :type="row.result === 'success' ? 'success' : 'danger'" size="small">{{ row.result }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="时间" width="180">
          <template #default="{ row }">{{ formatDate(row.timestamp) }}</template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { ElMessage } from 'element-plus';
import StatusBadge from './StatusBadge.vue';
import {
  listDocuments,
  uploadDocument,
  deleteDocument,
  getDocumentLineage,
  listVersions,
  createVersion,
  rollbackVersion,
  getDocumentAudit,
} from '@/api/client';
import type {
  DocumentInfo,
  DocumentUploadResponse,
  DocumentLineageResponse,
  VersionRecord,
  DocumentAuditEvent,
} from '@/types/api';

const loading = ref(false);
const uploading = ref(false);
const creatingVersion = ref(false);
const selectedFile = ref<File | null>(null);
const uploadResult = ref<DocumentUploadResponse | null>(null);
const documents = ref<DocumentInfo[]>([]);
const versions = ref<VersionRecord[]>([]);
const auditEvents = ref<DocumentAuditEvent[]>([]);
const lineageVisible = ref(false);
const lineageData = ref<DocumentLineageResponse | null>(null);

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(iso: string) {
  if (!iso) return '-';
  return new Date(iso).toLocaleString('zh-CN');
}

function categoryTagType(category: string) {
  if (category === 'document') return 'primary';
  if (category === 'query') return 'success';
  if (category === 'sensitive') return 'danger';
  return 'info';
}

async function refreshDocuments() {
  loading.value = true;
  try {
    const res = await listDocuments();
    documents.value = res.items;
  } catch (e: any) {
    ElMessage.error(e.message);
  } finally {
    loading.value = false;
  }
}

async function refreshVersions() {
  try {
    const res = await listVersions();
    versions.value = res.items;
  } catch (e: any) {
    ElMessage.error(e.message);
  }
}

async function refreshAudit() {
  try {
    const res = await getDocumentAudit({ limit: 50 });
    auditEvents.value = res.items;
  } catch (e: any) {
    ElMessage.error(e.message);
  }
}

function handleFileSelect(file: any) {
  selectedFile.value = file.raw || file;
}

async function uploadFile() {
  if (!selectedFile.value) return;
  uploading.value = true;
  try {
    const res = await uploadDocument(selectedFile.value);
    if (res.error) {
      ElMessage.error(res.error.message);
    } else {
      uploadResult.value = res;
      ElMessage.success(`${res.filename} 上传成功，生成 ${res.chunks_created} 个分块`);
      selectedFile.value = null;
      refreshDocuments();
    }
  } catch (e: any) {
    ElMessage.error(e.message);
  } finally {
    uploading.value = false;
  }
}

async function removeDocument(filename: string) {
  try {
    await deleteDocument(filename);
    ElMessage.success(`${filename} 已删除`);
    refreshDocuments();
  } catch (e: any) {
    ElMessage.error(e.message);
  }
}

async function viewLineage(filename: string) {
  try {
    lineageData.value = await getDocumentLineage(filename);
    lineageVisible.value = true;
  } catch (e: any) {
    ElMessage.error(e.message);
  }
}

async function createSnapshot() {
  creatingVersion.value = true;
  try {
    const res = await createVersion();
    ElMessage.success(`版本 ${res.version.version_id} 创建成功`);
    refreshVersions();
  } catch (e: any) {
    ElMessage.error(e.message);
  } finally {
    creatingVersion.value = false;
  }
}

async function doRollback(versionId: string) {
  try {
    const res = await rollbackVersion(versionId);
    ElMessage.success(`已回滚到 ${res.restored}，恢复 ${res.chunks} 个分块`);
    refreshVersions();
  } catch (e: any) {
    ElMessage.error(e.message);
  }
}

onMounted(() => {
  refreshDocuments();
  refreshVersions();
  refreshAudit();
});
</script>

<style scoped>
.document-manager {
  display: flex;
  flex-direction: column;
  gap: 24px;
  padding: 24px;
}

.dm-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.eyebrow {
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--color-primary);
  margin-bottom: 4px;
}

.dm-upload {
  border: 2px dashed var(--border-color, #dcdfe6);
  border-radius: 8px;
  padding: 16px;
}

.upload-area {
  text-align: center;
  padding: 24px;
}

.upload-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--border-color, #eee);
}

.dm-result {
  background: var(--color-success-light-9, #f0f9eb);
  border: 1px solid var(--color-success-light-5, #c2e7b0);
  border-radius: 8px;
  padding: 12px 16px;
}

.dm-list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.dm-list-header h3 {
  margin: 0;
}

.lineage-step {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 4px 0;
}

.dm-versions, .dm-audit {
  margin-top: 8px;
}
</style>
