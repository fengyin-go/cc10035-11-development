<template>
  <section class="page probe-evidence">
    <header class="page-head">
      <div>
        <h2>探针证据工作台</h2>
        <p class="page-desc">
          分站点采样许可与探针证据：同页可被多站模板引用，证据按站点归属、按许可版本成批，
          超权限原值在探针处拦截。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn ghost" type="button" data-testid="refresh-all" @click="loadAll">刷新全部</button>
      </div>
    </header>

    <p v-if="errorMessage" class="error-text" data-testid="global-error">{{ errorMessage }}</p>

    <!-- 板块一：模板与采样页归属 -->
    <article class="panel">
      <h3>① 模板登记与采样页归属（同一采样页可被两个站的模板引用）</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>模板</th><th>适用站点</th><th>采样页</th><th>样本版本</th>
            <th>待试跑字段 / 选择器</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="tpl in templates" :key="tpl.template_id" :data-testid="`tpl-row-${tpl.template_id}`">
            <td>{{ tpl.template_id }} · {{ tpl.name }}</td>
            <td><span class="site-tag">{{ tpl.site }}</span></td>
            <td>{{ tpl.page_id }}</td>
            <td>{{ tpl.sample_version }}</td>
            <td>
              <span v-for="(selector, name) in tpl.fields" :key="name" class="field-chip">
                {{ name }} → {{ selector }}
              </span>
            </td>
            <td class="row-actions">
              <button class="btn primary" type="button"
                      :data-testid="`trial-${tpl.template_id}`"
                      :disabled="busy" @click="runTrial(tpl.template_id)">
                发起试跑
              </button>
              <button class="btn" type="button"
                      :data-testid="`check-${tpl.template_id}`" @click="loadPublishCheck(tpl.template_id)">
                发布核对
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      <p class="hint" v-if="pages.length">
        采样页目录：
        <span v-for="page in pages" :key="page.page_id" class="page-ref">
          {{ page.page_id }}（归属：{{ page.page_owner }}；可用字段：{{ page.available_fields.join('、') }}）
        </span>
      </p>
    </article>

    <!-- 板块二：分站点采样许可 -->
    <article class="panel">
      <h3>② 分站点采样许可（精确到字段，变更只追加新版本）</h3>
      <table class="data-table">
        <thead>
          <tr><th>站点</th><th>当前版本</th><th>已授权字段</th><th>版本历史</th><th>补/收许可</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in permissionRows" :key="item.site">
            <td><span class="site-tag">{{ item.site }}</span></td>
            <td>v{{ item.current.version }}</td>
            <td>
              <span v-for="name in item.current.allowed_fields" :key="name" class="perm-chip">{{ name }}</span>
              <span v-if="!item.current.allowed_fields.length" class="muted">暂无授权字段</span>
            </td>
            <td>
              <span v-for="v in item.history" :key="v.version" class="version-chip">
                v{{ v.version }}: {{ v.allowed_fields.join('、') || '空' }}
              </span>
            </td>
            <td>
              <input v-model="permissionDraft[item.site].added"
                     :data-testid="`perm-add-${item.site}`"
                     placeholder="补许可字段，逗号分隔" class="perm-input" />
              <input v-model="permissionDraft[item.site].removed"
                     placeholder="收回字段，逗号分隔" class="perm-input" />
              <button class="btn" type="button" :disabled="busy"
                      @click="changePermission(item.site)">变更许可</button>
            </td>
          </tr>
        </tbody>
      </table>
    </article>

    <!-- 板块三：最近一次试跑结果 -->
    <article class="panel" v-if="lastTrial">
      <h3>
        ③ 试跑结果：批次 {{ lastTrial.batch.batch_id }}
        <span class="muted">
          （{{ lastTrial.new_batch ? '新产出批次' : '并发/重复请求合批复用' }}，
          许可 v{{ lastTrial.batch.permission_version }}）
        </span>
      </h3>
      <table class="data-table">
        <thead>
          <tr><th>字段</th><th>证据状态</th><th>选择器</th><th>实际交付原值</th><th>样本出处</th><th>说明</th></tr>
        </thead>
        <tbody>
          <tr v-for="f in lastTrial.batch.fields" :key="f.field_name"
              :data-testid="`trial-field-${f.field_name}`" :data-usable="String(f.usable)">
            <td>{{ f.field_name }}</td>
            <td><span class="status-badge" :class="badgeClass(f.status)">{{ f.status }}</span></td>
            <td>{{ f.selector }}</td>
            <td>{{ f.raw_value ?? '—（未交付）' }}</td>
            <td>{{ f.sample_ref }}</td>
            <td class="muted">{{ f.reason }}</td>
          </tr>
        </tbody>
      </table>
    </article>

    <!-- 板块四：发布闸口核对 -->
    <article class="panel" v-if="publishReport">
      <h3>
        ④ 模板 {{ publishReport.template_id }} 发布闸口核对：
        <span :class="publishReport.publishable ? 'verdict-ok' : 'verdict-block'">
          {{ publishReport.publishable ? '整模板可发布' : '暂不可发布' }}
        </span>
      </h3>
      <p class="hint">
        可发布字段：{{ publishReport.publishable_fields.join('、') || '无' }} ｜
        待验收字段：{{ publishReport.blocked_fields.join('、') || '无' }} ｜
        发布采用批次：{{ publishReport.referenced_batches.join('、') || '无' }} ｜
        清单历史出处：{{ publishReport.provenance_batches.join('、') || '无' }}
      </p>
      <table class="data-table">
        <thead>
          <tr><th>字段</th><th>结论</th><th>证据状态</th><th>模板选择器</th><th>证据批次</th><th>样本出处</th><th>原值</th></tr>
        </thead>
        <tbody>
          <tr v-for="check in publishReport.fields" :key="check.field_name"
              :data-testid="`check-field-${check.field_name}`">
            <td>{{ check.field_name }}</td>
            <td><span class="status-badge" :class="verdictClass(check.verdict)">{{ check.verdict }}</span></td>
            <td>{{ check.evidence_status ?? '—' }}</td>
            <td>{{ check.template_selector }}</td>
            <td>{{ check.batch_id ?? '—' }}</td>
            <td>{{ check.sample_ref ?? '—' }}</td>
            <td>{{ check.raw_value ?? '—' }}</td>
          </tr>
        </tbody>
      </table>
    </article>

    <!-- 板块五：分站点证据数据集 -->
    <article class="panel">
      <h3>⑤ 分站点探针证据数据集（站点物理隔离，批次不可变）</h3>
      <div v-for="ds in datasets" :key="ds.site" class="dataset-card"
           :data-testid="`dataset-${ds.site}`">
        <header>
          <span class="site-tag">{{ ds.site }}</span>
          批次 {{ ds.batch_count }} ｜ 已采证字段证据 {{ ds.delivered_field_evidences }} 条 ｜
          未验收 {{ ds.blocked_field_evidences }} 条
          <button class="link" type="button" @click="toggleDataset(ds.site)">
            {{ expandedSite === ds.site ? '收起批次' : '展开批次' }}
          </button>
        </header>
        <table v-if="expandedSite === ds.site" class="data-table inner">
          <thead>
            <tr><th>批次</th><th>样本出处</th><th>许可版本</th><th>已交付</th><th>未验收</th></tr>
          </thead>
          <tbody>
            <tr v-for="batch in siteBatches(ds.site)" :key="batch.batch_id">
              <td>{{ batch.batch_id }}</td>
              <td>{{ batch.sample_ref }}</td>
              <td>v{{ batch.permission_version }}（{{ batch.allowed_fields_snapshot.join('、') }}）</td>
              <td>{{ batch.delivered_fields.join('、') || '—' }}</td>
              <td>{{ batch.blocked_fields.join('、') || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </article>

    <!-- 板块六：模板证据清单 -->
    <article class="panel">
      <h3>⑥ 模板证据清单：实际交付字段及其样本出处</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>模板</th><th>站点</th><th>字段</th><th>状态</th><th>选择器</th>
            <th>原值</th><th>样本出处</th><th>证据批次</th><th>许可版本</th><th>登记时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="record in manifest" :key="`${record.template_id}-${record.batch_id}-${record.field_name}`"
              :data-testid="`manifest-${record.template_id}-${record.field_name}`">
            <td>{{ record.template_id }}</td>
            <td><span class="site-tag">{{ record.site }}</span></td>
            <td>{{ record.field_name }}</td>
            <td><span class="status-badge" :class="badgeClass(record.status)">{{ record.status }}</span></td>
            <td>{{ record.selector }}</td>
            <td>{{ record.raw_value ?? '—' }}</td>
            <td>{{ record.sample_ref }}</td>
            <td>{{ record.batch_id }}</td>
            <td>v{{ record.permission_version }}</td>
            <td>{{ record.recorded_at }}</td>
          </tr>
          <tr v-if="!manifest.length">
            <td colspan="10" class="empty-state">暂无证据清单记录，先对模板发起试跑</td>
          </tr>
        </tbody>
      </table>
    </article>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import {
  probeEvidenceApi,
  type DatasetSummary,
  type EvidenceBatch,
  type ManifestRecord,
  type Permission,
  type PublishReport,
  type TemplateRegistration,
  type PageInfo,
  type TrialResult,
} from '@/api/probe-evidence'

const templates = ref<TemplateRegistration[]>([])
const pages = ref<PageInfo[]>([])
const datasets = ref<DatasetSummary[]>([])
const manifest = ref<ManifestRecord[]>([])
const lastTrial = ref<TrialResult | null>(null)
const publishReport = ref<PublishReport | null>(null)
const expandedSite = ref<string | null>(null)
const batchCache = reactive<Record<string, EvidenceBatch[]>>({})
const busy = ref(false)
const errorMessage = ref('')

const permissionRows = ref<{ site: string; current: Permission; history: Permission[] }[]>([])
const permissionDraft = reactive<Record<string, { added: string; removed: string }>>({})

function splitFields(text: string): string[] {
  return text.split(/[，,]/).map((item) => item.trim()).filter(Boolean)
}

function badgeClass(status: string): string {
  if (status === '已采证') return 'badge-green'
  if (status === '待许可') return 'badge-amber'
  return 'badge-gray'
}

function verdictClass(verdict: string): string {
  if (verdict === '可发布') return 'badge-green'
  if (verdict === '选择器不一致') return 'badge-red'
  return 'badge-amber'
}

async function guard<T>(action: () => Promise<T>): Promise<T | undefined> {
  errorMessage.value = ''
  try {
    return await action()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '操作失败'
    return undefined
  }
}

async function loadTemplatesAndPages() {
  const [tplPayload, pagePayload] = await Promise.all([
    probeEvidenceApi.listTemplates(),
    probeEvidenceApi.listPages(),
  ])
  templates.value = tplPayload.items
  pages.value = pagePayload.items
  for (const tpl of tplPayload.items) {
    if (!permissionDraft[tpl.site]) {
      permissionDraft[tpl.site] = { added: '', removed: '' }
    }
  }
  const sites = [...new Set(tplPayload.items.map((item) => item.site))]
  permissionRows.value = (
    await Promise.all(sites.map((site) => probeEvidenceApi.permission(site)))
  )
}

async function loadDatasets() {
  datasets.value = (await probeEvidenceApi.datasets()).items
}

async function loadManifest() {
  manifest.value = (await probeEvidenceApi.manifest()).items
}

async function loadAll() {
  busy.value = true
  await guard(async () => {
    await loadTemplatesAndPages()
    await Promise.all([loadDatasets(), loadManifest()])
  })
  busy.value = false
}

async function runTrial(templateId: number) {
  busy.value = true
  const result = await guard(() => probeEvidenceApi.runTrial(templateId))
  busy.value = false
  if (!result) return
  lastTrial.value = result
  await Promise.all([loadDatasets(), loadManifest(), loadPublishCheck(templateId)])
}

async function changePermission(site: string) {
  const draft = permissionDraft[site]
  const added = splitFields(draft.added)
  const removed = splitFields(draft.removed)
  if (!added.length && !removed.length) {
    errorMessage.value = '请填写要补许可或收回的字段'
    return
  }
  busy.value = true
  await guard(() =>
    probeEvidenceApi.updatePermission(site, added, removed, '工作台发起的许可变更'),
  )
  busy.value = false
  draft.added = ''
  draft.removed = ''
  await loadTemplatesAndPages()
}

async function loadPublishCheck(templateId: number) {
  await guard(async () => {
    publishReport.value = await probeEvidenceApi.publishCheck(templateId)
  })
}

async function toggleDataset(site: string) {
  if (expandedSite.value === site) {
    expandedSite.value = null
    return
  }
  expandedSite.value = site
  if (!batchCache[site]) {
    await guard(async () => {
      batchCache[site] = (await probeEvidenceApi.siteDataset(site)).batches
    })
  }
}

function siteBatches(site: string): EvidenceBatch[] {
  return batchCache[site] ?? []
}

onMounted(loadAll)
</script>

<style scoped>
.panel {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 16px;
}
.panel h3 { margin: 0 0 10px; font-size: 15px; }
.hint { color: var(--muted); font-size: 12px; margin: 8px 0 0; }
.muted { color: var(--muted); font-weight: normal; }
.site-tag {
  display: inline-block;
  background: #e8f0fe;
  color: #1f6feb;
  border-radius: 4px;
  padding: 1px 8px;
  font-size: 12px;
}
.field-chip, .perm-chip, .version-chip {
  display: inline-block;
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 1px 6px;
  margin: 2px 4px 2px 0;
  font-size: 12px;
  background: #f8fafc;
}
.perm-input {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 5px 8px;
  width: 150px;
  margin-right: 6px;
}
.status-badge {
  display: inline-block;
  border-radius: 999px;
  padding: 2px 10px;
  font-size: 12px;
}
.badge-green { background: #dcfae6; color: #15803d; }
.badge-amber { background: #fef3c7; color: #b45309; }
.badge-gray { background: #e5e7eb; color: #475569; }
.badge-red { background: #fee2e2; color: #b91c1c; }
.verdict-ok { color: #15803d; font-weight: 600; }
.verdict-block { color: #b45309; font-weight: 600; }
.dataset-card {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 8px;
  background: #fafbfc;
  font-size: 13px;
}
.data-table.inner { margin-top: 8px; }
.page-ref { margin-right: 12px; }
</style>
