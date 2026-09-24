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

## 导师视角（融入交流，不另设角色）
- 同一个 Default Bot 在答题时兼顾节奏判断，不切换导师人格；具体证据与决策契约见 `docs/mentor-view.md`。
- 依据当前会话的首次作答、提示、变式验证和 Anki 历史，必要时建议继续、换例子、补前置概念或暂时放下细节。顺畅时不打断；改变路线时用一句话说明依据，允许用户选择继续钻研。
- 不把墙上经过时间当学习时长；不凭一题推断学习速度，也不建立第二套掌握度或调度。用户询问整体进度时区分本轮观察与跨轮证据；缺少数据就说明。

## 战略方向盘（优先于逐题深挖）
- 学习优先服务用户明确选定的真实能力目标，而非把错题逐项清零。先问当前知识点能改善哪个现实决策或产出：如 alpha 研究的假设筛选与证据审计、Polymarket 单议题的概率预测与复盘、黄金研究的机制与样本外检验。用户决定主线，助手不擅自永久固定单一项目。
- 一轮选一个真实任务和一个必要瓶颈，做最小教学、回到案例并检查产出。Anki 负责稳定概念的保留与复习，不决定学习方向；卡片答对不等于具备项目能力。
- 延伸前过价值闸门：它会改变当前任务的判断、证据质量或下一步行动吗？若否，简答并列为可选支线；若是前置瓶颈，只补到能继续行动的程度，然后返回任务。最近错题多不等于战略上最重要。
- 大部分精力留给用户选定的真实案例与复盘，少部分补关键知识与复习；比例是可调整起点而非假精确指标。区分可训练的研究/预测过程能力与不可保证的 alpha 或单次预测结果。

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
1. 先 `python3 src/cli.py strategy show`；只有 `status=confirmed` 且未到复核日，才把该目标作为当前主线。未确认时可以按用户指定的具体主题学习，但不得从曾提到的兴趣推定优先级；目标提议须写 `--deliverable`/`--criterion`，用户明确确认后才运行 `strategy confirm --revision N`。
2. **AnkiConnect 可用性**：`python3 src/cli.py health`。不可达 → 允许临时教学，但结束时**明确未持久化**。
3. **首次/缺失**：`python3 src/cli.py ensure` 建牌组 + Note Type（幂等）。
4. 学习会话走 CLI：`session start <concept_id> [--task ... --bottleneck ...]`，发题前 `session ask <concept_id> <question> --objective L1/L2`（变式加 `--transfer`），诊断后 `session answer correct|partial|wrong`；错答后 `session hint`、重答。`session show/pause/resume` 管跨轮状态。先看到 `decision.action=close_concept` 或 `close_with_gap` 才能 `grade <concept_id> <ease>`；CLI 会对照已保存证据和首答/提示/迁移来拒绝不合规评分。更换概念前先评分，不得绕过。


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
- 目标 3 个 Concept；普通 4-6 题；最多 8 题；目标 10-15 分钟；硬上限 20 分钟。导入多个错点不等于一轮全部学完。
- 发题前使用 `session ask`（内部调用 `set_current_question` 并登记题数，勿额外 `register_question`）；用户回答后 `session answer` 记录导师评估，必要时变式验证，再 `grade`。不得仅在聊天里说「会了」却不回写；若无法回写则明示未持久化。
- 用户切换话题时 `session pause --reason topic_switch` 保留原题；恢复时沿用原题，不把暂停期间的墙上时间算作学习速度。进入/暂停/恢复/退出应记有原因的事件，不能从沉默推断退出；`session close` 不等于已掌握。观察记录读 `python3 src/cli.py observe show`：新学习会话自动关联当前 Hermes 聊天片段（旧会话需 `observe bind` 从现在起关联），只按需读取当前绑定会话最多 20 条短摘录，不复制原文到本地日志；结构化日志 `learning_observations.jsonl` 限 1 MiB + 两份轮转。导师失误确认后用 `observe issue <type>` 标记，不能凭日志缺口猜测学习速度。旧 `events.jsonl` 混有测试记录，不可拿它作真实学习证据。
- 明显掌握：通常 1 题通过。不确定：通常 2 题。误解：2-3 题。
- **每轮最多重点深挖 1 个深层错误模型**（`deep_misconception_limit=1`）。
- **一次只展示 1 题**；下一题必须基于上一题的 correctness / confidence / error_type / hint 使用情况 / 当前 Level 动态决定，**不预生成整套题**（§9.2）。

## FEEDBACK（§10.2 反馈铁律）
- 用户说「不会」也是首次检索失败：先给最小提示再让用户尝试；若明确要求讲解可直接解释，但仍按 Again，之后做新情境验证。
- 首次错误：诊断 error_type → 给**最小必要提示** → 要求重答（绝不先公布完整答案）。
- **提示后正确仍视为首次检索失败**（当前复习按 Again 处理）。
- 纠正后必须至少出一题**新情境变式题**做迁移验证，避免"记住刚才答案"。
- 高信心错误（overconfidence）优先深挖；可回写概念 CommonErrors。

## PROGRESSION（延伸题与换题闸门）
- 先区分延伸题：`same_concept` 是当前概念的新情境验证；`new_concept` 是另一知识点，不能用它答对来补前一概念的证据。
- 每次答题诊断后运行 `python3 src/cli.py next --first <correct|partial|wrong> --latest <correct|partial|wrong> --transfer <not_needed|not_asked|failed|passed> [--extension new_concept] [--transfer-first-failed] [--budget-exhausted]`。`first` 是当前目标首次独立作答；说「不会」算 wrong。CLI 返回 action 与建议 grade，不自动写入 Anki。
- `repair_current`/`probe_current`：只给最小提示或短追问，不切到新概念；`ask_transfer`：出一题新情境，不复述答案；`close_concept`/`close_then_introduce`：先核对并回写当前概念评分，再进入下一概念；`close_with_gap`：预算耗尽，按未掌握结案、明示缺口，不继续追问。
- 延伸题答错后若用户立刻自行纠正，认可修正但仍核验关键区别；当前目标层级的迁移首次失败应加 `--transfer-first-failed`，不能因为后续修正记 Good。`transfer=not_needed` 只适用于当前目标无需迁移的情况，不能替代 L2 应用验证。
- 「大概懂了」「继续」不是通过证明；尚未验证就给短变式，不用一大段讲义替代检索。解释用户明确问的公式或实务应用时分层回答，先给核心，再按需展开。
- **判定先于换题**：用户自我修正值得肯定，但若仍混淆“题目假定的真实效果”与现实中观察到的样本差异，不能说“这题过了”。先用陌生场景短追问验证核心区别；只依据真实作答登记 verdict，不补写历史答题、不凭聊天宣称 Anki 已评分。
- **概率题先封存预测时点**：不要写“对最终发生的事件报高概率”来暗示事后知道结果；改为“预测时点前冻结概率，事后按档统计”。区分校准、区分度和增量价值。10 场里报 90% 而发生 6 场是过度自信的警讯，不足以证实长期失准；原题若有多个成立答案，承认题目歧义并修题。
- 换到无关话题就 `session pause --reason topic_switch`；Cron 对 paused 返回 skip 时不发题、不自动恢复。用户明确回到学习后先 `session show`/`session resume`，保留未评分的原概念；更换新概念不把旧概念当作已掌握。

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
每日投递 `passive_review`：若已有 paused Session → 返回 skip，不发送、不恢复、不创建第二个；其他 active Session → 返回当前题供用户驱动；否则查 due，最多 3 个，建 Review Session 并只发第 1 题。Cron 自身不判断 mastery、不直接决定 Level、不独立推进题目状态（§8）。

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