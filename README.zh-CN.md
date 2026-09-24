# AnkiTutor

<p align="center">
  <a href="README.md">English</a> · <b>简体中文</b>
</p>

概念固定，题目每次都是新的。

**AnkiTutor** 让你的 AI 助手在你的 Anki 之上当自适应导师。一张卡存一个 Concept（你想长期记住的那个知识点），每次到期时，agent 都**重新出一道题**——同一张卡，绝不重复同一场复习。练的是迁移，不是背答案。

```
概念：base_rate_neglect（基础率忽略）
─────────────────────────────────────────────
复习 1:  "患病率1%，灵敏度90%，假阳10%，
          检测阳性后实际患病概率？"
复习 2:  "如果把患病率改成30%呢？"
─────────────────────────────────────────────
答错？ agent 给最小提示 → 你重答 →
        再出一道全新变式确认你真的会了。
```

## 它能做什么

- 概念固定，题目动态。长期追踪同一个知识点，每次复习换新情境。
- 答错先给最小提示、再重答，随后用新情境验证迁移。明确要求解释时可以讲解，但首次不会仍按 `Again`。
- 评分硬规则：忘记或答错就是 `Again`，提示后想起不算首次检索成功。
- 同一个助手会留意是否在不影响学习目标的细节上耗尽时间，必要时建议换路；不另设导师人格，也不例行汇报。
- Anki 依旧是调度唯一事实源（FSRS）。AnkiTutor 负责教学。

## 安装

把下面这段粘给任意 AI 助手（Hermes / Claude / GPT / Gemini），它自己会装完：

```text
把 AnkiTutor 安装到 ~/.anki-tutor，仓库：
https://github.com/MarionLiew/anki-tutor 。
git clone 后创建 state/ 和 library/ 子目录，pip install -r requirements.txt，
然后运行验证：
    cd ~/.anki-tutor && python3 src/cli.py health
AnkiConnect 健康检查成功会返回含 `"version": 6` 的 JSON。Anki 未运行就说明连接失败；不要动已有文件、密钥或数据。
```

或者手敲命令：

```bash
git clone https://github.com/MarionLiew/anki-tutor.git ~/.anki-tutor
cd ~/.anki-tutor
pip install -r requirements.txt
python3 src/cli.py ensure
```

除 Python 3.10+ 外，还需要 **Anki 桌面版**和 **AnkiConnect 插件**（代码 `2055492159`，监听 `localhost:8765`）。没有 Anki 时，本地目标和会话命令仍可用，但无法核验或持久化 Anki 的读取与评分；不能声称 Anki 写入成功。

## 快速上手

战略分三层：**outcome**（终局结果，如「我能独立验证一条 alpha 假设」）→ **roadmap**（通往结果的能力链，每项以核验过的产出物/判断为证据）→ **concept**（Anki 卡片，服务当前能力）。评分不推进目标——只有 roadmap 证据算推进。目标未确认时导师会主动问一次（7 天冷却）你想主推哪条线；方向永远从你嘴里确认，不从学习记录推断。

```bash
python3 src/cli.py health
python3 src/cli.py ensure
python3 src/cli.py strategy show  # 未确认前不自动选主线
# 下面仅为示例，必须先征得用户对目标与产出的确认。
# outcome = 终局结果陈述（不是主题名）；roadmap = 能力链。
python3 src/cli.py strategy propose alpha --outcome "独立验证一条策略假设" --criterion "自己重跑数据能通过审计"
python3 src/cli.py strategy confirm --revision 1
python3 src/cli.py strategy roadmap add "设计达到功效的检验"
python3 src/cli.py strategy roadmap evidence "设计达到功效的检验" "2026-09-24 MDE 审计通过"
python3 src/cli.py strategy roadmap gap            # 下一个该补的能力
python3 src/cli.py session start quantos.research.mde_definition --task "审查基准" --bottleneck "理解 MDE"
python3 src/cli.py session ask quantos.research.mde_definition "MDE 为两个百分点意味着什么？" --objective L1
python3 src/cli.py session answer wrong  # 记录导师已判断的答案，CLI 不自行判开放题
python3 src/cli.py session hint
python3 src/cli.py session answer correct
python3 src/cli.py session ask quantos.research.mde_definition "新情境：MDE 3pp、观察差异 1pp，怎么判断？" --objective L1 --transfer
python3 src/cli.py session answer correct
python3 src/cli.py grade quantos.research.mde_definition 1  # 证据允许后才回写
```

`session show`、`session pause --reason topic_switch`、`session resume` 可保留当前题。新增 `observe show` 可查看有上限的学习观察报告：进入/暂停/恢复/退出、作答判断、提示、迁移、评分，以及用 `observe issue <type>` 明确标记的导师失误。在 Hermes 中开启新学习会话会绑定当前聊天；报告按需只读最多 20 条当前学习片段的用户/助手消息摘要，**不把聊天原文复制进日志**。旧会话可用 `observe bind` 从此刻开始关联，无法倒推之前的聊天；无绑定时仅显示结构化记录。独立观察元数据日志上限为 1 MiB 加两份轮转备份；旧 `events.jsonl` 混有测试记录，不应视为纯净学习历史。CLI 不会自行判断自由回答，`grade` 检查已保存证据，Anki 写入结果不明时标为 pending。

每天一次被动复习（最多取 3 个到期概念，只发第一题）：

```bash
python3 src/passive_review.py
```

Hermes 上挂 Cron：`hermes cron create "0 20 * * *" --name anki-tutor-review --skill anki-tutor`

## 怎么工作

AnkiTutor 的教学路线要基于你明确确认的目标。提到 alpha、Polymarket 或黄金只会让它们成为候选，不会自动排优先级。目标需写明一个具体产出及完成判据；30 天后提示复核，不会擅自换方向。每轮另记当前任务和瓶颈；Anki 仍独自负责概念复习排程。本地目标存于 `state/strategy.json`（可用 `ANKITUTOR_STATE` 改目录），不是另一套掌握度数据库。

| 组件 | 负责 |
|-----------|------|
| Anki + FSRS | 概念状态、复习历史、调度——唯一事实源 |
| Source Library | 原始资料、页码锚点、SHA-256、来源追溯 |
| TutorSession | 短期状态，让下一条消息能接着当前这题继续 |
| AnkiTutor skill | 出题、诊断、迁移验证、对话中的节奏判断 |

导师视角不是第二个人格：它读取当前作答和 Anki 历史，只在换个方式可能更有用时插一句。一题答对不足以推断学习速度。证据范围和干预规则见 [docs/mentor-view.md](docs/mentor-view.md)。

```
src/
  anki_client.py      AnkiConnect HTTP 封装（增删改查/评分/suspend）
  session.py          一题一答状态机 + 预算（8题上限 / 20分钟封顶）
  concept_service.py  ConceptID 去重、merge、retire、字段校验
  source_library.py   资料存储 + 哈希 + 页码索引
  ingest.py           PDF/DOCX/MD 解析 + 候选概念分块
  passive_review.py   Cron 入口：只发第一题，优先恢复不重复建
prompts/              出题、诊断、概念抽取三个模板
tests/                用 mock AnkiConnect——不需要真的 Anki
```

## 它不是

AnkiTutor 不是又一个 Anki，不是独立导师 Bot，也不是 LMS。它是 agent 按需调用的 skill。没有 Web UI、没有自己的调度器、不会整体批量替你生成固定卡组。边界才是重点——Anki 继续当唯一的调度器，Source Library 当唯一的知识库。

## 环境与测试

- Python 3.10+，`pypdf` / `python-docx`（解析用），`pytest`（测试用）
- 测试完全离线、不需要 Anki：`python3 -m pytest tests/ -q`（mock AnkiConnect）

## 许可

MIT © 2026 Marion Liew。见 [LICENSE](LICENSE)。