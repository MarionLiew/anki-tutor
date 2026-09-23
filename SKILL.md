---
name: anki-tutor
description: "AnkiTutor 自适应教学 Skill：为 Default Bot 提供理解/诊断/迁移/动态教学的按需能力。当用户学习/复习/答题/摄入资料，或 Cron 触发到期复习时使用。Anki 管遗忘、Source Library 管知识、本 Skill 管理解、Default Bot 管交互路由。"
version: 0.2.0
author: marionliew
license: MIT
platforms: [macos]
metadata:
  hermes:
    tags: [anki, learning, fsrs, spaced-repetition, tutoring]
    related_skills: []
    homepage: ""
---

# AnkiTutor Skill

**PURPOSE**：当用户明确进行学习、复习、答题、资料学习，或 Cron 触发到期复习时，为 Default Bot 提供自适应教学能力。本 Skill **不改变 Default Bot 的长期身份**，也不是独立 Bot（doc §3.1）。

## SOURCE OF TRUTH（数据职责边界）
- **Anki**：Concept、复习历史、FSRS 调度 —— 长期学习状态的唯一事实源。
- **Source Library**：原始学习资料与出处 —— 知识的唯一事实源（`library/`）。
- **TutorSession**：只保存当前一轮短期状态（`state/active_session.json`）。
- **绝不维护第二套 FSRS / next_review / mastery 数据库**（doc §3/§9）。

## ENTER（进入条件）
- 用户说「学习 <主题/资料>」「继续学习」「复习」「考考我」「重新学习 <Concept>」。
- Cron 投递 `passive_review`。
- 存在 active TutorSession，且用户回复明显对应当前题。

## EXIT（退出条件）
- Session 完成。
- 用户明确停止 / 稍后继续。
- 用户明显切换到无关话题（默认 Bot 恢复普通模式，不强拉回教学）。

## 运行时路径
```
anki-tutor/
├── SKILL.md
├── src/           # 确定性脚本：anki_client, session, concept_service, source_library, ingest, cli, events, config
├── prompts/       # question_generation, diagnosis, concept_extraction
├── state/         # 短期 Session（active_session.json）+ events.jsonl
├── library/       # sources / parsed / manifests / index
└── tests/
```
脚本运行：`cd <skill>/src && python3 cli.py <cmd>`。所有操作**必须**走 CLI/`src`，Default Bot **不得**现场即兴写 Python 改 Anki（doc §14 模块职责 + 用户对确定性脚本的偏好）。

## 触发即执行的步骤
1. **AnkiConnect 可用性**：先 `python3 src/cli.py health`。不可达 → 允许临时教学，但结束时**明确未持久化**，绝不伪造"已写入 Anki"（doc §16/t01 语义）。
2. **首次/缺失**：`python3 src/cli.py ensure` 建牌组 + Note Type（幂等）。
3. 然后按下方 ACTIVE LEARNING / PASSIVE REVIEW 流程走。

## ACTIVE LEARNING（主动学习）
1. 读取 Source（`ingest`）或定位已有 Concept（`cli.py check/get`）。
2. 查询 Anki 已有 Concept + Level + CommonErrors + 是否到期。
3. 选择**未掌握或当前目标需要**的起点，跳过已稳固内容（doc §7）。
4. 先探测/检索（短解释或先验探测题），再最小教学 —— **先让用户产生答案**（§10.2）。
5. 按当前 Level 与目标选 Recall / Application / Construction（表见 `prompts/question_generation.md`），**不强制逐级跑到 L3**（§7.2）。
6. 每轮一个 Concept 走完（→ 诊断 → 必要时迁移验证）后，`cli.py grade` 回写 + 必要时 `record_error` / `set_level`。

## PASSIVE REVIEW（被动复习 / Cron）
1. `python3 src/cli.py due --limit 3` 查 active + due 的 Concept（一次最多 3 个）。
2. 读取 CoreKnowledge / Level / CommonErrors / SourceRefs。
3. 创建/恢复 Review Session（`state/`）。
4. **只生成并发送当前第 1 题**；后续由用户回答驱动（§8：Cron 绝不连续推整组题，绝不输出长篇课程）。若无 due 概念则不强行教学。

## SESSION POLICY（§9.1）
- 目标 3 个 Concept；普通 4-6 题；最多 8 题；目标 10-15 分钟；硬上限 20 分钟。
- 明显掌握：通常 1 题通过。不确定：通常 2 题。误解：2-3 题。
- **每轮最多重点深挖 1 个深层错误模型**（`deep_misconception_limit=1`）。
- **一次只展示 1 题**；下一题必须基于上一题的 correctness / confidence / error_type / hint 使用情况 / 当前 Level 动态决定，**不预生成整套题**（§9.2）。

## FEEDBACK（§10.2 反馈铁律）
- 首次错误：诊断 error_type → 给**最小必要提示** → 要求重答（绝不先公布完整答案）。
- **提示后正确仍视为首次检索失败**（当前复习按 Again 处理）。
- 纠正后必须至少出一题**新情境变式题**做迁移验证，避免"记住刚才答案"。
- 高信心错误（overconfidence）优先深挖；可回写概念 CommonErrors。

## LEVEL（§7.1）
Level = **"已验证的最高能力层级"**（L0 识别 / L1 回忆 / L2 应用 / L3 构造）。
- 是已通过的证据记录，不是本次 Session 必须从 L0 跑到 L3 的目标。
- 普通复习达到当前目标层级即可结束（T12）。
- 层级只升不降，除非用户明确要求（concept_service.set_level 已强制）。

## GRADING（评分映射，§11 —— 硬规则）
- **Again(1)**：首次不会 / 答错 / 需要任何实质提示后才想起。
- **Hard(2)**：首次独立正确但明显犹豫 / 不完整。
- **Good(3)**：首次独立正确且达到当前目标 Level。
- **Easy(4)**：快速正确且有更高层级证据；谨慎使用。
- **绝不因"提示后想起"就把 Again 记成 Hard** —— 失败误记 Hard 会拉长复习间隔（§11）。

## CARD POLICY（§4/§5）
- 固定保存 Concept，不保存大量临时题；一次性案例与变式题**默认不写入 Anki**。
- 定义、公式、稳定原则、关键区别、反复错误模型可成为长期 Concept。
- 生命周期：**默认 retire/suspend，不删除有复习历史的 Concept**；只有明确垃圾且未复习、或用户明确确认，才允许 delete_unreviewed(confirm=True)。

## CRON（Phase 3）
每日投递 `passive_review`：若存在 active Review Session → 恢复（**不创建第二个**）；否则查 due，最多 3 个，建 Review Session 并只发第 1 题。Cron 自身不判断 mastery、不直接决定 Level、不独立推进题目状态（§8）。

## 失败处理（doc §13/§16）
| 故障 | 行为 |
|------|------|
| AnkiConnect 不可达 | 允许临时教学；结束时明确未持久化，不伪造成功 |
| ConceptID 冲突 | 停止自动创建；读两个对象 → merge 或人工选择 |
| PDF 解析失败 | manifest 标 failed；**不产生无来源 Concept** |
| LLM 无法可靠评开放题 | 降级为追问/让用户解释；不强写 Easy/Good |
| Session 状态损坏/缺失 | 不猜用户正在答哪题；回退到最近 Concept，明确重开该题 |
| Cron 重复触发 | 已有 active Session → 恢复/轻提醒，不新建 |

## 隐私与安全（§16）
- AnkiConnect 仅绑定 127.0.0.1；不暴露公网。
- Source Library 本地存储；敏感 PDF 不上传外部模型，除非用户明确选择。
- 日志只记事件，不记 API key / 三方模型密钥 / 敏感原文全文。

## 测试与验收
`cd anki-tutor && python3 -m pytest tests/ -q`（mock AnkiConnect，离线可跑）；对真实 Anki 可用 `src/cli.py` 各子命令冒烟。验收对齐文档 AC-01~AC-09 / T01~T13（见 tests/ 注释）。