# Web语义抽取与内容理解中心

面向Web结构化数据采集场景，提供页面DOM解析、实体识别、关系抽取、内容分类和知识图谱构建的语义抽取平台

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/WorkbenchView.vue|tsx  全部模块共享工作台
│   ├── src/data/modules.ts              18个业务模块配置
│   ├── src/api/              统一请求封装
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/resource.py  通用查询/导出/登记/动作接口
│   ├── app/routers/probe_evidence.py  探针证据专用接口（试跑/许可/数据集/清单/发布闸口）
│   ├── app/services/<key>.py    每个模块独立领域逻辑
│   ├── app/probe_evidence/      分站点探针证据与采样许可领域（见该目录 README）
│   ├── app/services/base.py     共享服务骨架
│   ├── app/store.py          内存数据仓库与示例数据
│   ├── tests/                探针证据单元/并发/持久化/HTTP 测试（40 例）
│   ├── scripts/scenario_demo.py  甲乙两站同页端到端场景回放
│   └── run_tests.py          隔离模式测试入口
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

探针证据领域的端到端场景回放与测试（无需启动服务，使用临时数据集）：

```bash
cd backend
python3 -I scripts/scenario_demo.py   # 甲乙两站同页试跑/许可拦截/并发合批/补许可回查
python3 -I run_tests.py               # 40 个测试用例
```

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| DOM解析 | `dom_parser` | 解析配置 | 配置名称、目标URI、解析引擎 |
| 实体抽取 | `entity_extract` | 实体条目 | 实体ID、实体类型、实体名称 |
| 关系图谱 | `relation_graph` | 关系边 | 边ID、源实体、目标实体 |
| 内容分类 | `content_classifier` | 分类标签 | 标签ID、页面URI、一级分类 |
| 模板规则 | `template_rule` | 规则模板 | 模板名称、适用站点、提取字段 |
| 文本分块 | `text_segment` | 文本块 | 块ID、来源页面、块类型 |
| 情感标注 | `sentiment_tag` | 情感记录 | 记录ID、文本片段、情感倾向 |
| Schema对齐 | `schema_align` | 对齐规则 | 规则名称、源Schema、目标Schema |
| 种子调度 | `feed_scheduler` | 调度任务 | 任务名称、URL种子、抓取深度 |
| 质量检查 | `quality_check` | 检查规则 | 规则名称、检查字段、检查类型 |
| 探针选择 | `probe_selector` | 探针配置 | 探针名称、目标页面、选择器列表 |
| 页面快照 | `page_snapshot` | 快照记录 | 快照ID、页面URI、DOM哈希 |
| 抽取指标 | `extract_metric` | 指标记录 | 记录时间、所属任务、成功页面数 |
| 语义结果 | `nlu_result` | 语义记录 | 记录ID、输入文本、意图标签 |
| 知识链接 | `knowledge_link` | 链接记录 | 链接ID、源实体、外部URI |
| 输出目标 | `output_target` | 输出配置 | 配置名称、输出类型、目标地址 |
| 抽取工坊 | `extract_studio` | 交互任务 | 任务名称、示例页面、标注区域 |
| 聚合视图 | `aggregate_view` | 视图配置 | 视图名称、统计维度、聚合字段 |

## 约定

- 全部模块共享`frontend/src/views/WorkbenchView.vue|tsx`和一套资源路由。
- 每个模块仍保留独立`backend/app/services/<模块>.py`；纯前端保留
  `frontend/src/domain/<模块>.ts`，用于承载真实业务差异并维持36题位容量。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 探针证据：分站点采样归属与许可校验

模板规则之外新增独立领域 `app/probe_evidence/` 与前端「探针证据」工作台
（路由 `/probe-evidence`），补齐模板采样页面的数据归属与可用字段校验能力：

- **同页多站**：同一采样页（`page_id@sample_version`）可被甲乙两站模板引用，
  采样页目录只做归属/可用字段校验，证据按发起站点分数据集存储、互不可见。
- **站点 × 字段许可**：许可版本化、只追加；超出权限的字段原值在探针处拦截，
  证据只登记 `待许可` 状态而不带原值。
- **并发合批**：同站点 + 同样本版本 + 同许可版本的并发请求只产出一批站点证据，
  批次固化采样时确认的许可版本与授权快照，批次不可变。
- **模板证据清单**：试跑结果回写清单，逐字段登记实际交付原值、选择器、
  样本出处（批次号、样本引用、许可版本），按 (模板, 批次, 字段) 幂等。
- **发布闸口**：维护者用实际采到的字段核对选择器；补许可前即可区分
  `已采证`（可发布）与 `待许可/未命中/样本缺字段`（未验收），跨站点证据不能放行。
- 许可变更后重跑产生引用新许可版本的新批次，旧批次保留，可随时回查其归属与
  当时已交付字段。详见 `backend/app/probe_evidence/README.md`。

领域：数据工程
子方向：数据采集、爬虫与RPA
