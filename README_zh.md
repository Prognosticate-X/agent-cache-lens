# agent-cache-lens 🔍

[![CI](https://github.com/Prognosticate-X/agent-cache-lens/actions/workflows/ci.yml/badge.svg)](https://github.com/Prognosticate-X/agent-cache-lens/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.9+](https://img.shields.io/badge/Python-3.9%2B-brightgreen.svg)](https://www.python.org/)
[![Zero Dependencies](https://img.shields.io/badge/Dependencies-0-success.svg)](pyproject.toml)

> **零外部依赖的 AI Agent 提示词缓存（Prompt Cache）网络穿透嗅探仪、前缀哈希断裂分析器与缓存守护中间件。**  
> 专门解决开源 Agent 客户端（如 [anomalyco/opencode#61282](https://github.com/anomalyco/opencode/issues/61282)）中 CacheX 暴跌、动态加载技能击穿缓存（[amd/gaia#5021](https://github.com/amd/gaia/issues/5021)）以及 Schema 序列化乱序导致的 10 倍推理成本与延迟恶化问题。

[English (US)](README.md) | [中文说明 (Chinese)](README_zh.md)

---

## ⚡ 痛点背景：为什么 Agent 提示词缓存经常雪崩？

当前主流大模型（Anthropic Claude 3.5 / Opus 5.5、OpenAI GPT-4o、DeepSeek V3）普遍支持 **Prompt Caching**。命中缓存时，输入 Token 价格可直降 **90%**，首字延迟（TTFT）大幅缩短 **85%**。

然而，大模型供应商计算缓存命中严格依赖**临时断点（Ephemeral Breakpoint）之前所有 Token 序列在字节级（Byte-exact）的哈希一致性**。在现实的 Multi-Agent 与长会话交互中，经常因为微小的代码细节导致缓存彻底穿透：

```
                       [ Prompt Cache 击穿的典型触发因素 ]
                                         │
        ┌────────────────────────────────┼────────────────────────────────┐
        ▼                                ▼                                ▼
   系统指令动态污染                  动态技能加载导致工具集变动             Schema 乱序与非确定性
在 System Prompt 中动态写入        在会话中途动态装载新技能           JSON 序列化未开启 key 排序，
时间戳、Git 分支或运行时状态        （如 [amd/gaia#5021]）使得        不同进程或环境重连导致
打破了整个前缀哈希。               后续所有对话的缓存前缀被毁。       哈希字节序列发生偏转。
        │                                │                                │
        └────────────────────────────────┼────────────────────────────────┘
                                         ▼
                   [ 线路前缀哈希在首部字节即发生分歧 ]
                                         ▼
              🔴 0% 缓存命中率 | 账单成本暴涨 10 倍 | 50s+ 首字卡顿
```

### 真实社区痛点案例：[OpenCode #61282](https://github.com/anomalyco/opencode/issues/61282)
*   **现象**：开发者使用 Tokscale 监测发现，在同样的工作流下，通过 OpenCode 调用 Opus 5.5 的 **CacheX 仅为 16.2x**（估算成本 $0.78 / MTok），而原生 Claude Code 却高达 **63.3x**（$0.39 / MTok），缓存重用率相差近 4 倍！
*   **根本原因**：
    1. 上下文长度识别偏低，在 170k 提前触发了 Compaction 上下文压缩（[#61020](https://github.com/anomalyco/opencode/issues/61020)）。
    2. 插件 Hook 动态向系统提示词末尾注入可变文本（[#61248](https://github.com/anomalyco/opencode/issues/61248)）。
    3. 工具字典和参数 Schema 缺少确定性递归排序。

---

## 🛠️ `agent-cache-lens` 核心功能

1. **透明反向代理与嗅探器 (`proxy`)**：本地启动轻量代理（基于 Python 标准库，0 依赖），透明拦截 Agent 客户端发往 API 的请求，逐轮计算前缀哈希 Diff，在终端毫秒级指出导致缓存失效的字符与字段。
2. **离线会话深度审计 (`analyze`)**：直接导入 OpenCode 导出会话文件、Claude Code 历史记录或 HAR 抓包文件，生成结构化 Markdown 审计报告。
3. **A/B 基准对照测试 (`compare`)**：并排对比两个会话日志，直接量化 CacheX 倍率差距与资金浪费额度。
4. **确定性缓存守护中间件 (`guard` / `--guard`)**：动态递归规范化工具参数 Schema、自动排序工具集，并在最合理的位置插入 `cache_control` 临时断点。

---

## 🚀 快速上手

### 1. 免安装直接运行
本工具完全基于 Python 标准库构建，无需 `pip install` 任何第三方依赖：

```bash
git clone https://github.com/Prognosticate-X/agent-cache-lens.git
cd agent-cache-lens
./bin/agent-cache-lens --help
```

### 2. 启动实时线路嗅探代理
将 Agent 客户端（如 OpenCode、Claude Code 或自研框架）的 Base URL 指向 `http://localhost:8080`：

```bash
# 启动代理（默认监听 8080 端口，上游指向 Anthropic）
./bin/agent-cache-lens proxy --port 8080 --upstream https://api.anthropic.com

# 或开启实时守护模式（自动稳定 Schema 与断点）：
./bin/agent-cache-lens proxy --port 8080 --guard
```

**实时终端反馈展示：**
```text
[Turn 01] Cache Retention: 100.0% (8,500 tokens) | Prefix Intact
[Turn 02] ⚠️ CACHE INVALIDATED! Retention: 0.0% | Reason: SYSTEM_MUTATION
         ↳ Lost 8,500 tokens | System prompt was mutated at segment [system_text].
           Char mismatch at offset 42:
             Prev: ...system engineer...
             Curr: ...system engineer. Current timestamp: 2026-11-03T13:40:15Z...
         ⚡ Metrics: CacheX: 1.82x | Hit Rate: 64.5% | Read: 8,500 | Write: 420 | Session Cost: $0.0611
```

### 3. 一键比对两份 Agent 会话（A/B 对比）

```bash
./bin/agent-cache-lens compare examples/sample_claude_code_session.json examples/sample_opencode_session.json
```

**输出基准对比表：**

| 指标 | Native Claude Code | OpenCode (Claude Agent) | 差距对比 |
| :--- | :---: | :---: | :---: |
| **总交互轮数** | `3` | `3` | - |
| **CacheX 倍率** | `**1.82x**` | `**0.0x**` | 目标会话缓存命中率为 0% |
| **缓存命中率** | `64.48%` | `0.0%` | `+64.5%` |
| **缓存读取 Tokens** | `17,420` | `0` | - |
| **缓存写入 Tokens** | `9,300` | `26,820` | - |
| **实际会话总成本** | `**$0.0611**` | `**$0.1745**` | 额外浪费 `+$0.1134` |

---

## 📐 Agent 开发者最佳工程实践建议

为保证多轮 Agent 会话中维持 **90%+ 的缓存命中率**，请遵循以下原则：

1. **绝对固定系统提示词（System Prompt）前缀**：绝不要将 `datetime.now()`、工作目录路径、Git 当前分支名等高频变动变量写入静态 System 文本中。如有动态信息，应放在单独的动态 block 或追加在 User Turn 中。
2. **工具列表字典递归排序与字母排序**：所有工具必须在发送前按 `name` 排序，其 `parameters` 下的 `properties` 必须进行递归 key 排序，防止不同语言/运行时的序列化差异击穿前缀。
3. **推迟动态工具加载（Deferred Skill Attachment）**：中途加载的新工具应统一追加到工具列表尾部，严禁插入列表中间破坏既有前缀。
4. **精准锚定 Ephemeral 临时断点**：
   - 断点 1：静态 System Prompt 结尾。
   - 断点 2：工具列表 `tools[]` 的最后一个工具。
   - 断点 3：倒数第二个 User Turn（`messages[-2]`），锁定历史对话内容。

---

## 🧪 运行单元测试

```bash
python3 -m unittest discover -s tests -v
```

---

## 📄 许可证

MIT © 2026 Prognosticate X
