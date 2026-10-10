# AnkiTutor 工程设计文档（开源版）

> 本项目工程的完整设计依据，源自一份聚焦"Default Bot + Skill"自适应教学的实施规范。

工程原则入口：根目录 `AGENTS.md`；学习原则权威来源：[learning-contract.md](learning-contract.md)。
本文件说明具体数据/实现契约；教学评分、Level 与掌握判断统一引用学习约定。

## 多 Track 数据与兼容性
- `strategy.json` version 3：`focus` 是 Track ID 或 null；`tracks` 是按稳定 ID 保存的对象。Track 复用 version 2 的 outcome/criterion/roadmap/revision/status/复核信息，新增 id/name/track_status（active/completed/archived）。确认 status 与生命周期 track_status 分开。
- `strategy migrate` 显式备份 `strategy.legacy.bak`，核验字节后原子写入，将原策略映射到 `legacy`，保持原证据。v1/v2 仍可只读或使用旧 CLI；创建第一条新 Track 时执行同样迁移。重复迁移不新增 Track。恢复需停教学后从备份还原，不能用 events 推断历史。
- 旧 `strategy show/confirm/revise/roadmap/asked/expire` 作用于当前 Focus；create/list/focus/complete/archive/activate 是多 Track 扩展。Outcome/Criterion 改变时 Roadmap 不继承，旧版本保留于 history。名称变更但目标/标准不变可保留证据。
- Session 的 `track_id` 可为空；`strategy_revision` 用于防止过期目标恢复。`active_session.json` 只有一个前台；`paused_sessions/<track-id-or-session-id>.json` 保存 dormant 状态全部字段，不复制 Anki 调度。保存核验后才移除旧前台，恢复先写前台后移除快照；异常保留证据并阻塞不安全状态。CLI/Cron 用标准库 flock 串行化本地状态转换。
- `track::<id>` 仅 Anki 原生标签。link/unlink 只操作命名标签并读回验证，普通 Concept 更新不替换该命名空间；其他用户标签不受影响。无本地关联表、无重复卡片。
- Track complete/archive 不调用任何 Anki 写操作。Cron due 查询 `is:due -is:suspended` 并核对 Concept Status=active，不要求标签、不限制 Focus；按 note 聚合卡片。旧暂停前台会保存快照并释放入口；前台已有题或 pending 时不新建、不重发。无 due 时才可准备满 24 小时的一次轻提醒，prepared 不是送达凭据。


## 教学与持久化原则
统一见 [learning-contract.md](learning-contract.md)。rubric、hint 送达登记及只读 reconcile 的调用示例见仓库 `SKILL.md`；回执核验细节见 [audit-recovery.md](audit-recovery.md)。

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
| AnkiConnect 不可达 | 停止教学并修复；保留未评分证据，不伪造成功 |
| ConceptID 冲突 | 停止自动创建；读两对象 → merge/人工选 |
| PDF 解析失败 | manifest 标 failed；不产生无来源概念 |
| LLM 无法可靠评开放题 | 降级为追问/让用户解释；不强写 Easy/Good |
| Cron 重复触发 | 已有前台 Session → skip，不新建、不重发 |

## 9. 安全与隐私

- AnkiConnect 仅绑定 127.0.0.1，不暴露公网
- Source Library 本地存储；敏感 PDF 不上传外部模型（除非用户明确选择）
- 日志只记事件，不落 API key / 三方模型密钥 / 敏感原文全文

## 10. 模型 Schema（AdaptiveConcept）

字段：`ConceptID / Title / CoreKnowledge / LearningObjective / Level / TargetLevel / Prerequisites / CommonErrors / SourceRefs / SourceHash / Status / TutorInstruction / Version / UpdatedAt`

ConceptID 是稳定永久唯一键（如 `probability.bayes.base_rate`），用于去重与更新。

## 11. 测试

mock AnkiConnect 离线单测（`tests/`），覆盖验收场景 AC-01~AC-09 与功能测试 T01~T13：
去重、即时纠错、评分硬规则、主动/被动复习、旧卡退役、来源删除不影响历史、断开不伪造、Session 恢复、预算上限、Level 语义、话题切换。

## 12. 融入对话的导师视角

导师视角是同一 Agent 的决策规则，不是独立 Bot、定时报表或第二套学习数据库。依据本轮首次作答、提示、变式验证与 Anki 复习历史决定继续、换例子、补前置或暂停；顺畅时不打断。不能把暂停期间的墙上时间当学习时长，也不能从单次作答推断长期速度。证据契约、干预边界与验收情境见 [mentor-view.md](mentor-view.md)。
