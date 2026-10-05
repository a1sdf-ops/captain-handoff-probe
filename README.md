# Chatwoot Captain · 转人工判定隔离探针

隔离复现开源客服平台 [Chatwoot](https://github.com/chatwoot/chatwoot) 内置 AI Agent **Captain**
的「转人工判定」，并用一组受控消融实验定位：**到底是什么在决定它"转人工"还是"自动关单"**。

不部署整套 Rails 栈，只隔离 `Captain::ConversationCompletionService` 的决策面，
用零依赖 Python 探针在 qwen 上复跑上游原 prompt + 8 条标注样例。

## TL;DR

- 保守判定在 **qwen-plus / qwen-max 上 8/8** 复现。
- **4 级 prompt 消融全 8/8，行为纹丝不动** → prompt 不是"承重墙"，承重的是 **模型先验 + 正向 COMPLETE 判据**。
- **换弱模型才翻**：qwen-turbo **6/8**（该关单却判 incomplete）。
- 失败方向**单向**：只会"多转人"，**没有任何模型出现漏关单**。
- 推论：**换模型的影响 > 改 prompt** —— 这解释了上游为什么把模型做成可配（`Llm::FeatureRouter`）+ 白名单收口。

## 拆的是什么

Chatwoot 是开源全渠道客服平台（Intercom/Zendesk 的开源替代），其 `enterprise/` 目录内置
AI Agent **Captain**。对静默的 pending 会话，Captain 会回头评估："答完了吗？"——
答完则自动关单，含糊则转人工。这个判定由
`enterprise/lib/captain/conversation_completion_service.rb` + `prompts/conversation_completion.liquid`
实现，输出结构化 `{complete, reason}`，且**默认保守**（异常/含糊一律判 incomplete）。

## 结果

### 结果一：消融阶梯（qwen-plus）

| 版本 | 改动 | 一致率 |
|---|---|---|
| v0 | 上游原 prompt | **8/8** |
| v1 | 移除全部 handoff 判据 | **8/8** |
| v2 | v1 + 倒转"存疑则保留"偏见句 | **8/8** |
| v3 | 移除整段 INCOMPLETE 判据 | **8/8** |
| v4 | v3 + 放宽 COMPLETE 判据 | **8/8** |

单点拆、多点拆、整段拆，**都不翻**——模型换个理由重新推出 incomplete。

### 结果二：换模型对拍（v0 原 prompt）

| 模型 | 一致率 | 翻转样例 |
|---|---|---|
| qwen-plus | **8/8** | — |
| qwen-max | **8/8** | — |
| qwen-turbo | **6/8** | S6（答全未致谢）、S7（仅问候）误判为 incomplete |

⇒ 弱模型的失败方向是**过度转人**（该关单却要转），**没有任何模型漏关单**。

## 方法（保真边界）

| 组成 | 来源 | 说明 |
|---|---|---|
| prompt | **上游原文逐字** | `chatwoot/enterprise/lib/captain/prompts/conversation_completion.liquid` |
| schema | 上游 | `{complete: boolean, reason: string}` |
| 调用形态 | 复现 | system = prompt，user = transcript，结构化输出（tool call） |
| 转录拼装 | 复现（本仓库的等价物） | 等价 `format_evaluation_input`；label 由样例直接给出 |
| 偏离（已知） | — | 裸 HTTP（无 Ruby/Rails）；`temperature=0`（上游走 RubyLLM 默认）；无配额/埋点包装 |

样例 8 条：4 条应 **incomplete**（多问答一半 / 只给外链 / 承诺跟进 / 客户不满）、
3 条应 **complete**（完整自洽 / 答全未致谢 / 边界仅问候）、1 条规则边界（转人工后仍 pending → incomplete）。

## 快速复现

```bash
# 0) 准备：把 chatwoot 克隆到本仓库同级目录（本仓库默认从 ../chatwoot 读上游 prompt）
git clone --depth 1 https://github.com/chatwoot/chatwoot.git ../chatwoot
#    或： export CAPTAIN_CLONE=/path/to/chatwoot

# 1) 配置（在仓库根目录建 .env，已被 .gitignore 忽略）
#    LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
#    DASHSCOPE_API_KEY=sk-xxxx
#    LLM_MODEL=qwen-plus

# 2) 基线
python probe.py

# 3) 换模型对拍
PROBE_MODEL=qwen-max   python probe.py
PROBE_MODEL=qwen-turbo python probe.py

# 4) 消融阶梯（先生成变体，再逐个跑）
python make_variants.py
PROBE_TAG=v1_plus PROBE_PROMPT=./variants/v1_no_handoff.liquid      python probe.py
PROBE_TAG=v2_plus PROBE_PROMPT=./variants/v2_bias_flipped.liquid    python probe.py
PROBE_TAG=v3_plus PROBE_PROMPT=./variants/v3_lenient.liquid         python probe.py
PROBE_TAG=v4_plus PROBE_PROMPT=./variants/v4_weak_complete.liquid   python probe.py
```

每次运行会落一份原始输出到 `results/<tag>.json`。

## 仓库结构

```text
probe.py            # 零依赖探针（标准库 urllib）
samples.json        # 8 条标注样例
make_variants.py    # 从本地 clone 运行时生成 v1-v4 消融 prompt（变体本身不入库）
results/            # 原始运行输出（v0 × 3 模型 + v1-v4）
docs/               # 详细结论与局限
```

## 诚实边界与局限

- 仅 qwen 系，单次运行、**无方差估计**；`temperature=0`；样例 label 直接给出。
- 未跑 OpenAI 原厂模型（不可达），"跨厂商一致性"未验证。
- 只隔离了"判定"这一环，未覆盖 Captain 的主回答循环、工具调用、多租户等其余部分。

## 授权与归属

- Chatwoot 为 **open-core**：核心 MIT，`enterprise/` 目录另授权。
- **本仓库只含探针作者自己的代码**；上游 prompt **不转载**，仅在运行时从你的本地 clone 读取。
- 消融 prompt 由 `make_variants.py` 运行时生成，**不入库**（见 `.gitignore`）。
- 对标版本：chatwoot `v3.4.4`，commit `1f1146a8d8`。上游 prompt 若变更，`make_variants.py` 的
  assert 会报错，提示重新校准。

## License

本仓库代码以 MIT 发布，见 [LICENSE](LICENSE)。
