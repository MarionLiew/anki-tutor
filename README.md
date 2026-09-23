# AnkiTutor

**自适应教学 Skill**：让 AI Agent（Hermes / Claude / 任意 LLM 主机）接管你的 Anki 复习——固定 Concept，动态出题；答错先诊断、给最小提示、要求重答，再用新情境迁移验证。

Anki 管遗忘（FSRS）、Source Library 管知识、AnkiTutor 管理解，交互主体是"Agent 本体"而不是独立 Bot。

> 设计文档：`docs/engineering-spec.md` · MIT License

---

## ✨ 一句话安装

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/MarionLiew/anki-tutor/main/install.sh)
```

安装脚本会：
1. 复制 `ANKI_TUTOR_HOME`（默认 `~/.anki-tutor`）
2. 检测/提示安装 Anki + AnkiConnect 插件
3. 配置环境路径，跑通 `python3 src/cli.py health`
4. 输出使用说明

### 手动安装（三行）

```bash
git clone https://github.com/MarionLiew/anki-tutor.git ~/.anki-tutor
pip install -r requirements.txt   # pypdf / python-docx / requests
python3 ~/.anki-tutor/src/cli.py ensure
```

### 依赖

| 组件 | 用途 |
|------|------|
| [Anki](https://apps.ankiweb.net/) 桌面版 | 本地复习/FSRS 调度（真实数据层） |
| [AnkiConnect](https://foosoft.net/projects/anki-connect/) 插件 | `localhost:8765` HTTP 接口 |
| Python 3.10+ | 脚本层（AnkiClient / Session / Source Library） |

> 不需要 Anki 也能学：脚本会把"未持久化"明确标出（见 §16 安全规则）。但复习调度必须 Anki 才能落地。

---

## 这是什么

Agent 变为自适应导师的核心逻辑，全部收敛在一个 skill 里：

- **一次只出一题**，下一题由上一题的对错、置信度、错因、提示使用情况动态决定（绝不预生成整套试卷）
- **紊乱解答优先确认**：答错 → 诊断 error_type → 给最小提示 → 要求重答 → 新情境变式验证
- **Level = 已验证的最高能力层级**（L0 识别 / L1 回忆 / L2 应用 / L3 构造），不强制逐级跑到 L3
- **评分硬规则**：忘记/答错必须 Again，提示后想起不记 Hard
- **生命周期保守**：retire/suspend 优先，不删除有复习历史的概念

## 架构

```
AnkiTutor skill
├── src/
│   ├── anki_client.py     # AnkiConnect HTTP 封装（CRUD/grade/suspend）
│   ├── session.py         # TutorSession 状态机 + 题目预算
│   ├── concept_service.py # ConceptID 去重 / merge / retire / 字段校验
│   ├── source_library.py  # 资料存储 + SHA-256 + 页码索引
│   ├── ingest.py          # PDF/DOCX/MD 解析 + 候选概念分块
│   ├── passive_review.py  # Cron 入口：只推第一题 / 恢复 → 不新建
│   ├── cli.py             # 确定性操作界面（health/ensure/grade/retire/merge/ingest）
│   └── config.py          # 路径 / 字段 / 评分与会话策略 单一来源
├── prompts/               # 出题 / 诊断 / 概念抽取 三个可维护提示模板
├── scripts/               # launchd 自启 / 导入脚本
│   └── install.sh         # ⬅ 一句话安装入口（仓库根）
├── state/                 # 短期 Session + 事件日志（非长期学习事实源）
├── library/               # sources / parsed / manifests / index
└── tests/                 # mock AnkiConnect 离线单测（AC-01..09, T01..13）
```

## 快速上手

```bash
cd ~/.anki-tutor

# 1. 环境 + 建牌组/模型（幂等）
python3 src/cli.py ensure
python3 src/cli.py health

# 2. 摄入一份资料 → 产生候选概念（不批量建卡）
python3 src/cli.py ingest path/to/notes.pdf --title "贝叶斯入门"

# 3. 主动学习：查看掌握情况 / 到期概念
python3 src/cli.py search --topic probability
python3 src/cli.py due --limit 3

# 4. 评分 / 生命周期
python3 src/cli.py grade quantos.probability.base_rate_neglect 3   # Again=1 Hard=2 Good=3 Easy=4
python3 src/cli.py retire old.concept --reason "过时"
python3 src/cli.py merge src.concept canonical.concept
```

### Cron 被动复习（每小时/每日）

```bash
# 手动触发一次（只推第一题）
python3 src/passive_review.py
```

配到 Hermes：`hermes cron create "0 20 * * *" --name anki-tutor-passive-review --skill anki-tutor`

### 测试

```bash
python3 -m pytest tests/ -q   # 15 项，mock AnkiConnect，无需真实 Anki
```

---

## 数据与隐私

- AnkiConnect 仅绑定 `127.0.0.1`；Source Library 本地存储
- 敏感 PDF 不上传外部模型（除非你明确选择）
- 日志只记事件，不落 API key / 三方模型密钥 / 敏感原文

## 已有概念示例（用户真实考卷复盘导入）

考卷错题被自动转成带来源页码的 AnkiTutor Concept：

```
quantos.probability.base_rate_neglect       # P02 贝叶斯基础率（逆概率谬误）
quantos.probability.edge_vs_benchmark       # P07 概率优势 ≠ 下注优势
quantos.research.mde_definition             # R06 MDE 定义
quantos.research.strong_baseline_role       # R07 强 baseline 作用
quantos.ops.fault_taxonomy                  # O03 数据/代码/研究失败分类
quantos.contract.minimal_prediction_contract# C07 最小预测契约字段
quantos.data.audit_chain                    # D08 数据可审计链 ≥6 节点
```

## License

[MIT](LICENSE) © 2026 Marion Liew

## 致谢

设计参考 [OpenTutor](https://github.com/zijinz456/OpenTutor)（资料摄入/自适应教学/知识图谱思路）。