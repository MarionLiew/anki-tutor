# AnkiTutor 工程设计文档（开源版）

> 本项目工程的完整设计依据，源自一份聚焦"Default Bot + Skill"自适应教学的实施规范。

## 1. 核心原则

- **Anki 管遗忘**（长期 Concept 状态 + FSRS 调度，唯一事实源）
- **Source Library 管知识**（原文 / 页码 / SHA-256，唯一事实源）
- **AnkiTutor Skill 管理解**（动态出题 / 错因诊断 / 迁移验证 / 会话控制）
- **Agent 本体管交互**（识别意图、路由、人格不变）

AnkiTutor **不是**另一个 Anki，**不是**独立 Tutor Bot，**不是**完整 LMS——它是按需调用的教学 Skill。

## 2. 第一版只做两个闭环

- **主动学习**：用户说"学这个" → 调 AnkiTutor → 提取概念 → 教学 → 迁移验证 → 写入/更新 Anki
- **被动复习**：Anki 到期 → Cron/用户触发 → AnkiTutor → 只推第一题 → 交互完成 → 回写评分

## 3. 数据职责边界

| 组件 | 唯一职责 | 明确不负责 |
|------|----------|-----------|
| Agent 本体 | 交互主体；识别意图；调用/退出 Skill | 独立维护 FSRS；复制长期学习状态 |
| Anki + FSRS | 概念状态、复习历史、到期调度 | 动态教学；生成大量固定题 |
| AnkiTutor Skill | 动态出题、即时反馈、错因诊断、会话控制 | 成为独立 Bot；自己实现 FSRS |
| TutorSession | 短期会话状态，使下条消息能续上 | 长期 mastery / next_review |
| Source Library | 原文/页码/hash、概念来源追溯 | 安排复习时间 |
| Cron | 按时触发/恢复复习并投递 | 完成整个 Session；连发多题；判掌握 |

## 4. 评分硬规则

```
Again(1)  首次检索失败（忘记/答错/需实质提示后想起）
Hard(2)   首次独立正确但明显犹豫/不完整
Good(3)   首次独立正确且达到当前目标 Level
Easy(4)   快速正确且有更高层级证据（谨慎用）
```

**绝不因"提示后想起"把 Again 记成 Hard** —— 失败误记 Hard 会拉长复习间隔。

## 5. Level 语义（L0~L3）

Level = **已验证的最高能力层级**，是证据记录，不是每次 Session 必须从 L0 跑到 L3 的目标。

| 层级 | 定义 | 典型验证 |
|------|------|----------|
| L0 Recognition | 看到选项能识别 | 选择题 |
| L1 Recall | 无选项能独立回忆 | 简答/定义/公式 |
| L2 Application | 陌生情境能应用 | 变式题/诊断案例 |
| L3 Construction | 能从零设计/审计/解释 | 写契约/审研究/设计流程 |

## 6. 一题一答 + 反馈铁律

- 一次只展示 1 题，下一题由上一题对错/置信/错因/提示/当前 Level 动态决定
- 先让用户产生答案，再教学
- 答错给**最小必要提示**，不先公布完整答案
- 提示后答对仍视为首次检索失败
- 纠正后必须至少一题**新情境变式**验证

## 7. 生命周期（保守）

- 默认 `retire`/`suspend`，不删除有复习历史的概念
- 只有明确垃圾且未复习、或用户明确确认，才允许删除（`delete_unreviewed(confirm=True)`）
- merge：源标 `merged` + suspend，保留来源与历史，不删除

## 8. 失败处理

| 故障 | 行为 |
|------|------|
| AnkiConnect 不可达 | 允许临时教学；结束时明确"未持久化"，不伪造成功 |
| ConceptID 冲突 | 停止自动创建；读两对象 → merge/人工选 |
| PDF 解析失败 | manifest 标 failed；不产生无来源概念 |
| LLM 无法可靠评开放题 | 降级为追问/让用户解释；不强写 Easy/Good |
| Cron 重复触发 | 已有 active Session → 恢复/轻提醒，不新建 |

## 9. 安全与隐私

- AnkiConnect 仅绑定 127.0.0.1，不暴露公网
- Source Library 本地存储；敏感 PDF 不上传外部模型（除非用户明确选择）
- 日志只记事件，不落 API key / 三方模型密钥 / 敏感原文全文

## 10. 模型 Schema（AdaptiveConcept）

字段：`ConceptID / Title / CoreKnowledge / LearningObjective / Level / Prerequisites / CommonErrors / SourceRefs / SourceHash / Status / TutorInstruction / Version / UpdatedAt`

ConceptID 是稳定永久唯一键（如 `probability.bayes.base_rate`），用于去重与更新。

## 11. 测试

mock AnkiConnect 离线单测（`tests/`），覆盖验收场景 AC-01~AC-09 与功能测试 T01~T13：
去重、即时纠错、评分硬规则、主动/被动复习、旧卡退役、来源删除不影响历史、断开不伪造、Session 恢复、预算上限、Level 语义、话题切换。