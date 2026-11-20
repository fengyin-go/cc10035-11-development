/**
 * 探针证据领域接口：采样页校验、分站点许可、探针试跑、
 * 分站点证据数据集、模板证据清单与发布闸口。
 */
import { fetchJson, request } from './client'

const BASE = '/api/probe-evidence'

export type FieldEvidence = {
  field_name: string
  status: string
  usable: boolean
  selector: string
  raw_value: string | null
  sample_ref: string
  reason: string
}

export type EvidenceBatch = {
  batch_id: string
  site: string
  page_id: string
  sample_ref: string
  sample_version: string
  permission_version: number
  allowed_fields_snapshot: string[]
  template_ids: number[]
  created_at: string
  coalesced: boolean
  delivered_fields: string[]
  blocked_fields: string[]
  fields: FieldEvidence[]
}

export type TrialResult = {
  ok: boolean
  batch: EvidenceBatch
  coalesced: boolean
  new_batch: boolean
}

export type Permission = {
  site: string
  version: number
  allowed_fields: string[]
  note: string
  issued_at: string
}

export type FieldCheck = {
  field_name: string
  template_selector: string
  verdict: string
  evidence_status: string | null
  batch_id: string | null
  sample_ref: string | null
  permission_version: number | null
  raw_value: string | null
  reason: string
}

export type PublishReport = {
  template_id: number
  site: string
  publishable: boolean
  publishable_fields: string[]
  blocked_fields: string[]
  referenced_batches: string[]
  provenance_batches: string[]
  fields: FieldCheck[]
}

export type ManifestRecord = {
  template_id: number
  site: string
  page_id: string
  sample_ref: string
  field_name: string
  selector: string
  status: string
  usable: boolean
  batch_id: string
  raw_value: string | null
  permission_version: number
  recorded_at: string
  reason: string
}

export type TemplateRegistration = {
  template_id: number
  name: string
  site: string
  page_id: string
  sample_version: string
  fields: Record<string, string>
}

export type PageInfo = {
  page_id: string
  url: string
  page_owner: string
  versions: string[]
  available_fields: string[]
}

export type DatasetSummary = {
  site: string
  batch_count: number
  delivered_field_evidences: number
  blocked_field_evidences: number
  batches: string[]
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await request(path, { method: 'POST', body: JSON.stringify(body) })
  if (!response.ok) {
    const detail = (await response.json().catch(() => ({}))) as { detail?: string }
    throw new Error(detail.detail ?? `接口返回 ${response.status}`)
  }
  return (await response.json()) as T
}

export const probeEvidenceApi = {
  listPages: () => fetchJson<{ items: PageInfo[] }>(`${BASE}/pages`),
  validatePage: (pageId: string) =>
    fetchJson(`${BASE}/pages/${encodeURIComponent(pageId)}/validation`),
  listTemplates: () =>
    fetchJson<{ items: TemplateRegistration[] }>(`${BASE}/templates`),
  permission: (site: string) =>
    fetchJson<{ site: string; current: Permission; history: Permission[] }>(
      `${BASE}/permissions/${encodeURIComponent(site)}`,
    ),
  updatePermission: (site: string, added: string[], removed: string[], note: string) =>
    postJson<{ ok: boolean; permission: Permission }>(
      `${BASE}/permissions/${encodeURIComponent(site)}/update`,
      { added, removed, note },
    ),
  runTrial: (templateId: number, fields?: string[]) =>
    postJson<TrialResult>(`${BASE}/templates/${templateId}/trial`, { fields }),
  publishCheck: (templateId: number) =>
    fetchJson<PublishReport>(`${BASE}/templates/${templateId}/publish-check`),
  datasets: () => fetchJson<{ items: DatasetSummary[] }>(`${BASE}/datasets`),
  siteDataset: (site: string) =>
    fetchJson<{ summary: DatasetSummary; batches: EvidenceBatch[] }>(
      `${BASE}/datasets/${encodeURIComponent(site)}`,
    ),
  manifest: (templateId?: number) =>
    fetchJson<{ items: ManifestRecord[] }>(
      `${BASE}/manifest${templateId ? `?template_id=${templateId}` : ''}`,
    ),
}
