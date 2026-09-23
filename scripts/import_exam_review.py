"""Ingest the exam debrief as a Source, then create AnkiTutor Concepts for
the failed / weak areas identified in quantos_assessment_20260923_0957.json.
Targeted — one concept per gap, all pointing at the debrief source.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from source_library import SourceLibrary
from ingest import IngestService
from anki_client import AnkiClient
from concept_service import ConceptService
from config import LIBRARY_DIR

lib = SourceLibrary(LIBRARY_DIR)
src = "/tmp/ankitutor_exam/quantos_assessment_20260923.md"
res = IngestService(lib).ingest(src, title="QuantOS 考卷复盘 2026-09-23")
sid = res["source_id"]
print(f"Source ingested: {sid} | hash={res['hash'][:12]} | candidates={res['candidate_count']}")

svc = ConceptService(AnkiClient())
S = f"{sid}"

concepts = [
    ("quantos.probability.base_rate_neglect",
     "Base Rate Neglect / 基础率忽略",
     "后验概率必须同时考虑基础率与似然：当基础率很低时，即使灵敏度高、假阳率低，检测阳性的后验患病率也可能只有个位数百分比。",
     "能在陌生贝叶斯情景中，用自然频率法计算后验概率，避免只凭似然作答。",
     "L2", ["probability.bayes.base_rate"], ["inverse_probability"],
     ["#p=1"], "优先用自然频率法"),
    ("quantos.probability.edge_vs_benchmark",
     "概率优势 ≠ 下注优势",
     "模型概率高于市场可比价只是必要条件；计入手续费、滑点、对手价差后仍为正期望才是下注优势。",
     "面对一个有优势的概率判断，能识别并说明为何仍需扣除交易成本才构成下注理由。",
     "L2", [], ["overconfidence"], ["#p=2"], ""),
    ("quantos.research.mde_definition",
     "MDE（最小可检测效应）定义",
     "MDE = 在给定样本量、功效与显著性下，统计上能够可靠检出的最小真实效应；它不是最大回撤，也不描述收益大小。",
     "能用 MDE 概念判断一个研究设计是否有足够功效去验证某个效应。",
     "L1", [], ["concept_confusion"], ["#p=3"], "把 MDE 与回撤/收益指标区分开"),
    ("quantos.research.strong_baseline_role",
     "强 baseline 的作用",
     "强 baseline 用于两件事：判断复杂方法是否带来真正的增量价值；避免把简单可得收益误归功于复杂模型。",
     "评估一篇模型论文时，能指出需要与怎样的事实上强 baseline 对比、以及漏掉 baseline 会导致什么偏差。",
     "L2", [], [], ["#p=4"], "对比时永远先问 baseline"),
    ("quantos.ops.fault_taxonomy",
     "故障必须分类：数据 vs 代码 vs 研究失败",
     "数据故障（超时/缺失/schema drift）、代码故障（抛异常）、研究失败（结论经证伪）必须分开记录与处理：它们的取证、责任与修复路径完全不同。",
     "面对一个异常，能把它正确归类到 数据/代码/研究 之一，并指出该类的处置方向。",
     "L2", [], [], ["#p=5"], ""),
    ("quantos.contract.minimal_prediction_contract",
     "最小预测契约字段",
     "一个 Polymarket 预测目标的最小契约含：问题定义、结算规则、信息截止时间、概率输出、基准、记分方法（proper scoring rule）、停止条件、失败状态。",
     "能为一个给定预测目标写出满足上述全部字段的最小机器可执行契约。",
     "L3", [], ["incomplete_model"], ["#p=6"], ""),
    ("quantos.data.audit_chain",
     "数据可审计链（≥6 节点）",
     "报告数字→原始数据的可审计链：report → report_input → derived_feature → canonical → raw → source_capture；在 canonical 与 raw 两节点检查时间可得性（release date / available-at）。",
     "能把一个报告数字追溯到具体输入源并指出哪个环节可能出现 PIT 污染。",
     "L2", [], [], ["#p=8"], ""),
]

for cid, title, core, lo, lvl, prereq, errs, refs, hint in concepts:
    refs_full = [f"{S}{r}" for r in refs]
    existing = svc.get(cid)
    if existing:
        svc.update({"concept_id": cid, "title": title, "core_knowledge": core,
                    "learning_objective": lo, "level": lvl, "source_refs": refs_full,
                    "tutor_instruction": hint})
        print(f"[update] {cid}")
    else:
        svc.create({"concept_id": cid, "title": title, "core_knowledge": core,
                    "learning_objective": lo, "level": lvl,
                    "prerequisites": prereq, "common_errors": errs,
                    "source_refs": refs_full, "status": "active",
                    "tutor_instruction": hint, "version": 1,
                    "domain": "quantos", "origin": "exam"})
        print(f"[create] {cid}")
print("done")