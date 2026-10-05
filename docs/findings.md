# 详细结论：Captain「转人工判定」在 qwen 上的行为

对应探针 `probe.py` 的运行结果。日期 2026-10-05。

## 一句话结论

保守判定在 qwen-plus / qwen-max 上 **8/8 复现**；但它是**模型先验 + 正向 COMPLETE 判据**在承重，
**不由任何单条 prompt 句子承重**——逐层拆 prompt 都不改变行为，**换弱模型才暴露差异**。
失败方向是单向的：只会**多转人（误判）**，不会**漏关单**。

## 消融阶梯（v0 → v4，均为 qwen-plus）

| 版本 | 改动 | 一致率 | 观察 |
|---|---|---|---|
| v0 | 上游原 prompt | 8/8 | 基线 |
| v1 | 移除全部 handoff 判据 | 8/8 | 模型换个理由重新推出 incomplete |
| v2 | v1 + 倒转"存疑则保留"偏见句 | 8/8 | 偏见句也不是承重墙 |
| v3 | 移除整段 INCOMPLETE 判据 | 8/8 | 仍靠正向 COMPLETE 定义重建 |
| v4 | v3 + 放宽 COMPLETE 判据 | 8/8 | 单点/多点/整段拆都不翻 |

## 换模型对拍（v0 原 prompt）

| 模型 | 一致率 | 翻了的样例 |
|---|---|---|
| qwen-plus | 8/8 | — |
| qwen-max | 8/8 | — |
| qwen-turbo | 6/8 | S6（答全未致谢）、S7（仅问候）误判为 incomplete |

⇒ 弱模型的失败方向是**过度转人**，**没有任何模型出现漏关单**。

## 差异笔记（原以为 X，实际是 Y）

1. **原以为**：prompt 是转人工行为的控制面，改一句就能改行为。
   **实际**：拆掉 INCOMPLETE 判据、倒转偏见句、放宽 COMPLETE 判据，行为**纹丝不动**。
   承重的是**模型先验 + 正向 COMPLETE 定义**。
2. **原以为**：保守判定的风险是"该转不转"。
   **实际**：三模型一致地**只向"多转人"偏移**，不向"漏关单"偏移——错误代价不对称。
3. **推论**：**换模型的影响 > 改 prompt**。这解释了上游把模型做成 `Llm::FeatureRouter`
   可配 + 白名单（`config/llm.yml`）的设计动机——模型是可变的**行为风险点**，所以要收口。

## 实验二：episode 边界（记忆分段）——标记对判定零影响

**背景**：Captain 用 `<conversation_boundary status="resolved" />` 给会话分段。该标记由"已解决"的 activity 消息生成（`message_history_builder_service.rb:2,37-45`）。

**架构事实（代码级，可核对）**：
- 主 agent 的历史构建器取 `message_type: [incoming, outgoing, activity]`（`:20`）→ **能看到边界标记**。
- 转人工评估器的转录构建器取 `message_type: [incoming, outgoing]`（`conversation_completion_service.rb:53`）→ **activity 被过滤，边界标记到不了它**。

**实验**：6 条样例（5 条"旧 episode 看似未解决 + 新问题已答完"，1 条无陈旧内容对照）。A = 把 marker 硬塞进转录（反事实）；B = 不含 marker（等同生产）。

| 模型 | A（含 marker） | B（不含 marker） | 逐条判定 |
|---|---|---|---|
| qwen-plus | 1/6 | 1/6 | 完全相同 |
| qwen-max | 1/6 | 1/6 | 完全相同 |

**结论**：
1. 注入 marker **零影响**——两模型上 A、B 逐条判定一致。
2. 评估器**对陈旧内容敏感、对 episode 边界不敏感**：BM6（无陈旧内容）判 complete；带陈旧内容的 5 条全判 incomplete，且理由中明确引用旧 episode（如"对第一个问题仅表示已升级给物流团队，未提供进展"）。
3. 解读：评估器无法区分"已关闭但看起来未解决的旧 episode"与"真正还开着的旧问题"，于是保守地保持开启。`expect=complete` 指"当前 pending 交流已解决"——边界感知的评估器本应判 complete。后果：一个"已解决但结尾看起来没解决"的会话被重开后，永远不会自动关单，只会转人工。**记忆分段机制在评估器侧是盲区。**

## 局限（诚实标注）

- `temperature=0`、样例 label 直接给出、仅 qwen 系、单次无方差估计、无配额/埋点包装。
- 未跑 OpenAI 原厂模型（本机不可达）——"跨厂商一致性"未验证。
