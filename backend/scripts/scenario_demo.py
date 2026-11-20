"""端到端场景回放：甲乙两站同页试跑、许可拦截、并发合批、补许可回查。

独立运行（隔离模式 + 全新临时数据集，不污染正式 data/ 目录）：
    python3 -I scripts/scenario_demo.py
"""
from __future__ import annotations

import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.probe_evidence.service import (  # noqa: E402
    PRICE_FIELD,
    SITE_A,
    SITE_B,
    TITLE_FIELD,
    ProbeEvidenceService,
)


def line(title: str) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def show_batch(batch) -> None:
    print(f"  批次 {batch.batch_id} | 站点={batch.site} | 样本={batch.sample_ref}"
          f" | 许可版本=v{batch.permission_version} | 合批={batch.coalesced}")
    for item in batch.fields:
        value = item.raw_value if item.raw_value is not None else "（原值已拦截）"
        print(f"    - {item.field_name:<4} 状态={item.status.value:<5} "
              f"选择器={item.selector:<18} 原值={value}")
    print(f"    已交付字段={batch.delivered_fields} | 未验收字段={batch.blocked_fields}")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        svc = ProbeEvidenceService(data_dir=tmp)
        svc.bootstrap_demo_data()

        line("1. 采样页归属与可用字段校验（同一采样页供甲乙两站模板引用）")
        report = svc.validate_sampling("page-shared-news")
        print(f"  采样页={report['page_id']} 归属={report['page_owner']}")
        print(f"  可用字段={report['available_fields']}")
        print(f"  甲站模板 101 与乙站模板 102 均指向: "
              f"{svc.get_template(101)['page_id']} == {svc.get_template(102)['page_id']}")

        line("2. 甲站许可范围：标题已获准取原值，价格仍待许可")
        print(f"  当前许可: {svc.current_permission(SITE_A)}")

        line("3. 甲站用获准标题 + 未获准价格发起试跑")
        first = svc.run_template_trial(101)
        show_batch(first.batch)

        line("4. 发布闸口核对：补许可前区分可发布字段与未验收字段")
        check = svc.check_template_publish(101)
        for item in check.fields:
            print(f"    - {item.field_name:<4} 结论={item.verdict.value:<8} "
                  f"证据批次={item.batch_id} 出处={item.sample_ref} 原因={item.reason}")
        print(f"  整模板可发布={check.publishable}，可发布字段={list(check.publishable_fields)}")

        line("5. 并发请求：同站点同样本版本 12 个并发只产出一批站点证据")
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = [future.result() for future in
                       [pool.submit(svc.run_template_trial, 101) for _ in range(12)]]
        batch_ids = {r.batch.batch_id for r in results}
        print(f"  12 次请求落到批次数={len(batch_ids)}（{batch_ids}），"
              f"数据集实际批次={svc.dataset_summary(SITE_A)['batch_count']}")

        line("6. 乙站同页试跑：站点隔离，无许可字段全部拦截")
        b_result = svc.run_template_trial(102)
        show_batch(b_result.batch)
        print(f"  分站点数据集: {[d['site'] for d in svc.list_datasets()]}")

        line("7. 改变采样许可（补齐价格）后重跑，产生引用新许可版本的批次")
        new_perm = svc.update_permission(SITE_A, added=[PRICE_FIELD], note="价格许可补齐")
        print(f"  新许可版本: v{new_perm['version']} 授权字段={new_perm['allowed_fields']}")
        rerun = svc.run_template_trial(101)
        show_batch(rerun.batch)

        line("8. 回查前一批：归属与已交付字段保持采样时状态，不可变")
        old = svc.get_batch(SITE_A, first.batch.batch_id)
        print(f"  旧批 {old['batch_id']} | 许可版本=v{old['permission_version']} "
              f"| 已交付={old['delivered_fields']} | 未验收={old['blocked_fields']}")
        old_price = next(f for f in old["fields"] if f["field_name"] == PRICE_FIELD)
        print(f"  旧批价格原值={old_price['raw_value']}（许可变更不回填历史批次）")

        line("9. 模板证据清单：实际交付字段及样本出处全量登记")
        for record in svc.list_manifest(101):
            print(f"    - 模板{record['template_id']} {record['field_name']:<4} "
                  f"{record['status']:<5} 批次={record['batch_id']} "
                  f"出处={record['sample_ref']} 许可v{record['permission_version']}")

        line("10. 最终发布闸口结论")
        final = svc.check_template_publish(101)
        print(f"  整模板可发布={final.publishable}")
        print(f"  发布采用批次={list(final.referenced_batches)}")
        print(f"  清单历史出处批次={list(final.provenance_batches)}")

        line("11. 分站点探针证据数据集已落盘")
        for root in sorted(Path(tmp).rglob("*.json")):
            print(f"  {root.relative_to(tmp)}")


if __name__ == "__main__":
    main()
