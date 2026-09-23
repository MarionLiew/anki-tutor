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

- **概念固定，题目动态。** 长期追踪同一个知识点，每次复习换新情境。
- 答错先诊断（`error_type`）→ 给**最小提示** → 你重答 → 再出一道变式确认。agent 从不直接公布答案。
- 评分硬规则：忘记或答错就是 `Again`，即使提示后想起了也不行（提示后想起不算首次检索成功）。
- **Anki 依旧是调度唯一事实源**（FSRS）。AnkiTutor 只负责教学，不抢调度。

## 安装

把下面这段粘给任意 AI 助手（Hermes / Claude / GPT / Gemini），它自己会装完：

```text
把 AnkiTutor 安装到 ~/.anki-tutor，仓库：
https://github.com/MarionLiew/anki-tutor 。
git clone 后创建 state/ 和 library/ 子目录，pip install -r requirements.txt，
然后运行验证：
    cd ~/.anki-tutor && python3 src/cli.py health
"OK" 表示 localhost:8765 上的 AnkiConnect 返回 6。如果 Anki 没在运行，
直接说明即可——不要动我已有的任何文件、密钥或数据。
```

或者手敲命令：

```bash
git clone https://github.com/MarionLiew/anki-tutor.git ~/.anki-tutor
cd ~/.anki-tutor
pip install -r requirements.txt
python3 src/cli.py ensure
```

除 Python 3.10+ 外，还需要 **Anki 桌面版**和 **AnkiConnect 插件**（代码 `2055492159`，监听 `localhost:8765`）。没有 Anki，CLI 照常跑，但每次写入都会标"未持久化"——绝不假装成功。

## 快速上手

```bash
python3 src/cli.py health          # AnkiConnect 通不通
python3 src/cli.py ensure          # 建牌组+题型，幂等
python3 src/cli.py ingest notes.pdf --title "贝叶斯入门"   # 提取候选概念
python3 src/cli.py due              # 有哪些到期
python3 src/cli.py grade <concept> 3   # 评分：1=Again 2=Hard 3=Good 4=Easy
```

每天一次被动复习（最多取 3 个到期概念，只发第一题）：

```bash
python3 src/passive_review.py
```

Hermes 上挂 Cron：`hermes cron create "0 20 * * *" --name anki-tutor-review --skill anki-tutor`

## 怎么工作

| 组件 | 负责 |
|-----------|------|
| Anki + FSRS | 概念状态、复习历史、调度——唯一事实源 |
| Source Library | 原始资料、页码锚点、SHA-256、来源追溯 |
| TutorSession | 短期状态，让下一条消息能接着当前这题继续 |
| AnkiTutor skill | 出题、诊断、最小提示、迁移验证 |

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
- 测试完全离线、不需要 Anki：`python3 -m pytest tests/ -q`（15 个用例，mock AnkiConnect）

## 许可

MIT © 2026 Marion Liew。见 [LICENSE](LICENSE)。