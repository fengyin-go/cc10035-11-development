# 分站点探针证据与采样许可

解决「模板规则缺少区分适用站点和样本归属的能力」：模板采样页面的数据归属与可用
字段先经校验，再按站点生成探针证据数据集；探针运行时读取分站点数据集，采样结果
回写模板证据清单，登记实际交付的字段及样本出处。

## 领域对象与职责

| 对象 | 文件 | 职责 |
| --- | --- | --- |
| 采样页目录 `PageCatalog` / `SamplingPlanner` | `catalog.py` | 采样页与版本样本登记、数据归属与可用字段校验；同一采样页可被多站模板引用 |
| 采样许可 `PermissionRegistry` | `permissions.py` | 站点 × 字段范围的版本化许可；只追加新版本，历史版本可回查 |
| 证据数据集 `EvidenceRepository` | `repository.py` | 分站点 JSON 数据集（`data/probe_evidence/datasets/<站点>.json`），批次只追加、不可变 |
| 证据清单 `ManifestRepository` | `repository.py` | 模板证据清单（`manifest.json`），按 (模板, 批次, 字段) 幂等登记样本出处 |
| 探针执行器 `ProbeRunner` | `runner.py` | 归属校验 → 锁许可版本 → 许可拦截 → 采样 → 落批次 → 回写清单；并发合批 |
| 发布闸口 `PublishGate` | `gate.py` | 用实际采到的证据逐字段核对选择器，区分可发布与未验收字段 |
| 应用服务 `ProbeEvidenceService` | `service.py` | 门面、演示引导数据（甲乙两站同页场景） |

## 关键规则

1. **同页多站**：采样页不归属任何站点；证据归属发起站点。甲乙两站模板可指向
   同一 `page_id@sample_version`，但各自产出独立站点数据集，互不可见。
2. **许可拦截**：许可精确到站点 + 字段。未授权字段即使样本存在原值，探针也只
   登记 `待许可` 证据，`raw_value=null`，原值不离开探针。
3. **并发合批**：合批键 = 站点 + 采样页 + 样本版本 + 许可版本。同键并发请求
   在键级锁内二次检查数据集，只实际采样一次，只落一批站点证据。
4. **许可版本固化**：批次内冻结 `permission_version` 与授权字段快照。许可变更
   后重跑产生新批次；旧批次不可变，事后可按批次号回查归属与当时已交付字段。
5. **发布闸口**：仅 `已采证` 且选择器与模板一致、且归属本站点的字段可发布；
   `待许可/未命中/样本缺字段` 判为证据待验收，补许可前即可区分两类字段。
6. **字段四态**：`已采证`（唯一可用）、`待许可`、`未命中`（选择器不匹配）、
   `样本缺字段`（授权但无数据）。

## HTTP 接口（前缀 `/api/probe-evidence`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/pages` / `/pages/{page_id}/validation` | 采样页目录与归属/可用字段校验 |
| GET | `/templates` / `/templates/{id}` | 模板登记（站点、采样页、字段选择器） |
| GET | `/permissions/{site}` | 当前许可与版本历史 |
| POST | `/permissions/{site}/grant` | 以完整字段集登记新许可版本 |
| POST | `/permissions/{site}/update` | 补许可/收回许可（added/removed） |
| POST | `/templates/{id}/trial` | 按模板发起探针试跑，回写证据清单 |
| POST | `/trials` | 不依赖模板登记的临时试跑 |
| GET | `/datasets` / `/datasets/{site}` / `/datasets/{site}/batches/{batch_id}` | 分站点证据数据集与批次回查 |
| GET | `/manifest?template_id=` | 模板证据清单：实际交付字段及样本出处 |
| GET | `/templates/{id}/publish-check` | 发布闸口逐字段核对结论 |

## 演示与测试

```bash
# 端到端场景回放（临时数据集，自动清理）
python3 -I scripts/scenario_demo.py

# 40 个单元/并发/持久化/HTTP 测试
python3 -I run_tests.py
```

`scenario_demo.py` 完整覆盖：同页两站登记 → 甲站标题获准/价格待许可试跑 →
发布闸口区分两类字段 → 12 并发合批为 1 批 → 乙站隔离拦截 → 补许可重跑出新批次
→ 回查旧批归属与已交付字段 → 清单与数据集落盘。
