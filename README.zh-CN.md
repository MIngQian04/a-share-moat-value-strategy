# 安全边际投资研究平台

**机器负责搜索，人工负责判断，规则负责执行，市场负责验证。**

一个从全 A 股中寻找“估值具有安全边际，同时具备可验证长期价值捕获能力”的投资研究平台。

系统先通过所有者收益、现金流、资产负债表和五档 DCF 建立保守估值边界，再把护城河机制、日期明确的证据、观察指标和反证信号记录为独立的研究流程；低估值本身不等于长期优势。

仓库当前是确定性的 Python 流水线与人工研究记录；LLM 辅助研究属于未来设想，不是运行时依赖。

**English:** [README.md](README.md) · **公开网站：** [ming-daily-portfolio.qianmin968641.chatgpt.site](https://ming-daily-portfolio.qianmin968641.chatgpt.site)

> **仅供研究。** 不连接券商，不自动下单。

## 当前项目状态

这份公开文档快照日期为 **2026-07-17**，对应当前快照中最近一个已完成交易日。快照不包含凭据、私人实际成交或浏览器本地账户数据。

- **覆盖范围：** 扫描 5,522 只 A 股；其中 202 只通过财务复核，并具备可完成估值的输入。
- **筛选结果：** 15 家公司通过当前稳定锚仓门槛；下方公开研究队列展示其中 8 行排名。
- **估值：** 已生成 202 份五档所有者收益 DCF 记录。
- **护城河证据：** 当前维护 10 条用于研究长期价值捕获的可证伪护城河注册表记录，并有雷达健康快照。
- **前瞻验证：** NAV 记录从 2026-07-15 开始，并包含原始收盘价沪深 300 对比。
- **公开展示：** 上方链接提供双语只读网站；这些数字是单个快照，不是永久覆盖承诺。

汇总数字保存在 [`docs/public-status.json`](docs/public-status.json)，由 [`scripts/build_public_readme_snapshot.py`](scripts/build_public_readme_snapshot.py) 根据本地最新哑铃策略输出生成。

**当前筛选漏斗：** 5,522 只扫描标的 → 202 只通过财务复核并可估值 → 15 只满足当前锚仓门槛 → 8 只展示于公开研究队列。

### 最新筛选概览

下表是在快照中 202 行已完成财务复核记录内，按实现的锚仓评分排序的研究队列。基准 DCF 安全边际按代码实际口径计算：`dcf_base_value_per_share / market close - 1`。排名用于确定人工研究优先级，不代表系统已经确认护城河，也不构成自动买入信号。

**快照日期：2026-07-17。** 完整的公开字段保存在 [`docs/public-screening-snapshot.csv`](docs/public-screening-snapshot.csv)。

| 排名 | 代码 | 公司 | 行业 | 评分 | 基准 DCF 安全边际 | 财务/数据门 | 筛选状态 | 护城河代理状态 |
| ---: | --- | --- | --- | ---: | ---: | --- | --- | --- |
| 1 | `600519.SH` | 贵州茅台 | 食品饮料 | 73.9 | -23.5% | `PASS_CASH_EARNINGS` | `WATCH` | `BRAND_PRICING_POWER_PROXY` |
| 2 | `002032.SZ` | 苏泊尔 | 家用电器 | 73.4 | -6.9% | `PASS_CASH_EARNINGS` | `WATCH` | `SCALE_COST_LEADER_PROXY` |
| 3 | `000568.SZ` | 泸州老窖 | 食品饮料 | 73.2 | +68.6% | `PASS_CASH_EARNINGS` | `WATCH` | `NO_POSITION_EVIDENCE` |
| 4 | `603195.SH` | 公牛集团 | 轻工制造 | 71.7 | -11.2% | `PASS_CASH_EARNINGS` | `WATCH` | `BRAND_PRICING_POWER_PROXY` |
| 5 | `002027.SZ` | 分众传媒 | 传媒 | 71.7 | -3.6% | `PASS_CASH_EARNINGS` | `WATCH` | `POSITION_ONLY_REVIEW` |
| 6 | `000651.SZ` | 格力电器 | 家用电器 | 71.6 | +113.3% | `PASS_CASH_EARNINGS` | `DEFENSIVE_ELIGIBLE` | `SCALE_COST_LEADER_PROXY` |
| 7 | `300760.SZ` | 迈瑞医疗 | 医药生物 | 71.5 | -1.8% | `PASS_CASH_EARNINGS` | `WATCH` | `BRAND_PRICING_POWER_PROXY` |
| 8 | `300979.SZ` | 华利集团 | 纺织制造 | 70.4 | +24.6% | `PASS_CASH_EARNINGS` | `WATCH` | `POSITION_ONLY_REVIEW` |

> **状态说明：** `WATCH` 表示保留在研究/观察队列；`DEFENSIVE_ELIGIBLE` 表示通过当前稳定锚仓全部门槛；`PASS_CASH_EARNINGS` 表示归一化所有者收益和归一化 FCF 通过现金收益门。`BRAND_PRICING_POWER_PROXY` 与 `SCALE_COST_LEADER_PROXY` 是机器代理；`POSITION_ONLY_REVIEW` 表示只通过行业位置代理；`NO_POSITION_EVIDENCE` 表示没有通过位置型代理。以上代理状态都不等于人工确认的护城河证据。

## 这个系统如何寻找机会

系统不是先指定热门行业再寻找股票，也不是只根据低估值机械买入，而是将跨行业估值与财务质量、未来需求研究和可证伪护城河证据交叉，寻找当前预期较低、但未来利润池可能改善的公司。

```mermaid
flowchart LR
    A["全 A 股"] --> B["财务质量与<br/>低估值筛选"]
    B --> C["所有者收益与<br/>五档 DCF 安全边际"]
    C --> D["未来需求与<br/>利润池研究"]
    D --> E["护城河与<br/>价值捕获能力甄别"]
    E --> F["证据<br/>状态"]
    F --> G["规则生成<br/>仓位"]
    G --> H["T+1<br/>前瞻 NAV"]
    H --> I["沪深 300<br/>持续比较"]
```

第一条腿从全 A 股寻找估值支持、所有者收益、现金流转化、资产负债表质量、生存能力、数据完整性和行业位置；第二条腿研究政策、产业规划、需求、瓶颈和利润池变化，再在护城河证据流程中记录结构性优势、观察指标和反证信号。候选池来自两者的交叉，而不是其中任何一项单独通过。

## 为什么做这个项目

投资研究既需要机器的一致性，也需要人对不确定未来的判断。本项目用机器处理宽广的 A 股市场，由人工验证未来需求与护城河证据，再由规则把证据状态转成目标仓位，最后用前瞻观察验证完整过程。目标是让研究流程可检查、可复现，并清楚标出仍然未知的部分。

## 机器、人工、规则与市场

| 层次 | 当前职责 | 边界 |
| --- | --- | --- |
| **机器：搜索** | 扫描全市场、报表、估值、现金流、生存质量、行业位置和证据完整性。 | 缩小研究范围，但不能证明护城河或预测公司未来。 |
| **人工：验证** | 判断未来需求、政策相关性、行业风险和有日期的一手证据，确认或否定假设并记录理由。 | 不是无边界的主观选股；后来信息不能回写历史 NAV。 |
| **规则：生成** | 把证据状态、DCF 边界和仓位上限转成锚仓、未来期权和现金权重。 | 只产生模型目标与开盘代理价，不发送券商订单。 |
| **市场：验证** | 记录前瞻日 NAV，并与沪深 300 原始收盘价代理比较。 | 实盘样本仍短，基准不含指数分红。 |

这意味着 DCF 与雷达输出是供人工复核的机器辅助结果：后来信息不能改写历史 NAV，任何流程也不会发送券商订单。

## 核心能力

### 安全边际与未来需求交叉

实际问题不是“什么便宜”或“什么热门”，而是公司是否有当前现金收益支撑，以及未来利润池是否存在可信的改善路径。政策文件、产业规划、需求信号和里程碑证据用于定义研究方向；政策匹配本身不是买入信号。

### 护城河识别价值捕获能力

行业景气只能说明利润池可能扩大，不能说明所有公司都会受益；收入增长或市场份额也不能单独证明持久护城河。护城河档案要回答：公司是否依靠品牌、定价、技术、成本、稀缺资源、渠道、转换成本、标准、牌照、规模或生态位置，持续获取并保留行业利润，以及什么证据会否定这一机制。

注册表与 append-only 证据台账记录经济机制、难以复制的原因、有日期且可追溯的一手来源、观察指标、反证信号、复核日期和证据恶化时的组合动作。财务指标只验证经济结果，不能自动把 `DRAFT` 提升为 `INTACT`。

<p align="center"><img src="docs/assets/zh-moat-thesis.png" alt="中文护城河档案：护城河机制、监测指标与削弱信号" width="900"></p>

这张档案把护城河变成可被证伪的假设：说明难以复制之处、需要观察什么，以及什么变化会削弱判断。

### 五档 DCF 是安全边际边界，不是精准目标价

DCF 在本项目中不是为了给出一个看似精准的目标价，而是建立非常悲观、谨慎、基准、乐观和非常乐观的估值边界。它帮助判断基准安全边际是否存在、乐观情景是否已经被价格透支、便宜是否可能是价值陷阱，以及何时应考虑加仓、持有、暂停或减仓。

`valuation/owner_earnings.py` 使用年度 point-in-time 报表、最近三期所有者收益中位数、净现金、五年预测和终值。增长率限制在 -2% 至 6%，终值增长率为 2.5%，基准折现率为 10%。

| 情景 | 折现率 |
| --- | ---: |
| `VERY_OPTIMISTIC` 非常乐观 | 8% |
| `OPTIMISTIC` 乐观 | 9% |
| `BASE` 基准 | 10% |
| `CAUTIOUS` 谨慎 | 11% |
| `VERY_PESSIMISTIC` 非常悲观 | 12% |

基准档仍是可重复的筛选门槛；其余档位展示估值区间，不暗中改变经营预测。

<p align="center"><img src="docs/assets/zh-dcf-sensitivity.png" alt="中文五档折现率 DCF 敏感性界面" width="900"></p>

界面保留 10% 中性档作为机械门槛，同时展示 8%–12% 的估值区间，供人工判断安全边际。

### 护城河雷达是证据监测系统

雷达的自动层检查持仓公告、监管/治理/经营关键词、财务与经营现金流恶化、定期复核到期和数据源健康；人工层补充机构研报、政府与行业资料、竞争对手变化、管理层披露、技术变化以及原始护城河假设。

雷达负责发现可能挑战投资逻辑的事件，不负责解释事件含义。命中生成 `PENDING_REVIEW`；公告覆盖的 `OK`、`PARTIAL`、`UNAVAILABLE`、`OFFLINE` 保持不同健康状态。输出文件为 `moat_radar_alerts.csv` 和 `moat_radar_health.csv`。

### 规则化哑铃仓位

当前政策使用 65% 锚仓预算、25% 未来产业总上限、15% 单一主题上限、10% 现金底线和 15% 锚仓单股上限。未来证据按同一阶梯升降：

| 状态 | 参考仓位 | 含义 |
| --- | ---: | --- |
| `RESEARCH_ONLY` | 0% | 仍在研究的候选。 |
| `OPTION_SEED` | 2.5% | 有证据、估值和时机支持的未来期权。 |
| `CONFIRMED_BUILD` | 5% | 至少两类里程碑以有日期证据验证。 |
| `PROMOTED_CORE` | 7.5% | 三类里程碑、无未解决反证且趋势确认。 |

当证据、估值或分散限制不足以支持更多暴露时，现金就是有效输出。

### 真实前瞻 NAV 与成交边界

1. 收盘后发布的信号只成为下一交易日目标。
2. 今日收益使用上一交易日已经公布的目标仓位。
3. 模型开盘价是可复现的执行代理，不保证成交。访问者本地的实际价格、数量和手续费单独记录；未成交与部分成交保持待执行。
4. NAV 使用原始收盘价涨跌，加税后代理 `cash_div` 与 `stk_div` 送转比例。除权日确认权益，派息日形成待复投资金，下一交易日按目标权重统一复投。
5. 不把复权价与单独分红同时使用，避免重复计算。
6. 沪深 300（`000300.SH`）使用原始收盘价代理，不含指数分红；缺失日期显示 `PARTIAL` 或 `UNAVAILABLE`，不编造数据。

<p align="center"><img src="docs/assets/zh-nav-vs-csi300.png" alt="中文前瞻组合 NAV 与沪深 300 单位代理对比图" width="900"></p>

这是一段从同一起始单位记录的前瞻结果，不是旧回测，也不承诺持续跑赢大盘。

## 公开网站与产品截图

打开[公开只读网站](https://ming-daily-portfolio.qianmin968641.chatgpt.site)查看最新发布快照。独立的 `portfolio-site/` 项目展示模型 NAV、当日收益板、明日目标板、完整持仓、个股护城河档案、DCF 敏感性、估值修复摘要、配置中的公开机构参考、雷达健康和浏览器本地实际成交记录；它不会连接券商或自动下单。

<p align="center"><img src="docs/assets/zh-overview.png" alt="中文公开网站总览：NAV、收益曲线与当日持仓" width="100%"></p>

总览把研究流程放回产品界面：累计与当日 NAV、昨日仓位收益口径、明日执行板、持仓、组合分布和沪深 300 对比集中展示。

估值修复页面是研究辅助，不是自动信号。它整理市场为什么折价、估值修复需要什么、哪些因素可能转恶，以及带日期的公开机构参考如何与模型估值并列。

<p align="center"><img src="docs/assets/zh-valuation-repair.png" alt="中文估值修复摘要：低估原因、修复条件、预期转恶因素与公开机构估值参考" width="820"></p>

本 README 图片由用户于 2026-07-19 从公开只读网站截取。实际成交账本依赖访问者本地浏览器数据，因此不在公开文档中展示。

公开机构参考来自 `config/valuation-repair-briefs.json` 的静态/人工整理内容；网站不会每次访问都自动联网搜索。网站源码是独立嵌套仓库，根仓库通过 `.gitignore` 排除。

## 组合结构

- **锚仓：** 当前现金经济、行业位置和护城河代理较稳定；锚仓预算 65%，单股上限 15%。
- **未来期权：** 政策关联需求与有日期里程碑；在 25% 总上限内按 2.5% → 5% → 7.5% 阶梯建设。
- **现金：** 当前政策至少 10%；当证据或估值标准未满足时，现金可以更高。

仓库当前实现的是确定性的 Python 筛选、财务处理、DCF、证据/雷达规则、仓位、T+1 NAV 和基准比较，以及配置驱动的静态研究摘要。**没有** DeepSeek、OpenAI 或其他 LLM API 运行时；LLM 证据总结、研报提取和反证检测仍是未来或可选能力。

## 快速开始

需要 Python 3.10+、本地 Tushare Token；只有构建独立网站时才需要 Node.js/npm。不同 Tushare 接口可能需要不同权限。

```bash
git clone https://github.com/MIngQian04/a-share-moat-value-strategy.git
cd a-share-moat-value-strategy
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Token 只能写入本地 `.env`，绝不打印、复制、提交或写入输出、截图和文档。

```bash
python3 scripts/refresh_rotation_market_data.py
python3 scripts/run_moat_radar.py
python3 scripts/run_future_demand_screen.py --refresh-financials
python3 scripts/run_barbell_strategy.py
python3 scripts/build_public_readme_snapshot.py
```

数据源不可用时保留缓存并报告不可用，不把缺失数据变成零风险或零价值。只使用缓存检查时：

```bash
python3 scripts/run_moat_radar.py --offline
python3 scripts/run_barbell_strategy.py --offline
```

构建独立网站：`cd portfolio-site && npm ci && npm run build`。

运行检查：

```bash
python3 -m pytest -q
python3 -m compileall -q portfolio scripts valuation tests
python3 scripts/check_public_release.py
```

## 仓库结构

- `config/`：策略假设、政策映射、里程碑与证据台账。
- `data_loader/`：Tushare 客户端、本地行情缓存、公告和分红。
- `fundamental/`：Point-in-time 财务与生存质量输入。
- `industry/`：行业周期与未来需求研究。
- `selection/`：候选池、政策门槛、护城河证据和雷达规则。
- `valuation/`：所有者收益归一化与 DCF 估值。
- `portfolio/`：仓位规则、分红记账、NAV 和网站导出。
- `scripts/`：日常流程与命令行入口。
- `tests/`：研究、护城河、组合和记账规则测试。
- `docs/`：方法、可复现说明和实现边界。
- `portfolio-site/`：独立嵌套网站仓库，根仓库忽略。

原始缓存、生成输出、`.env` 和网站构建产物不会进入根仓库公开版本。

## 方法与文档

详细实现见 [中文方法说明](docs/METHODOLOGY.zh-CN.md) 与 [English methodology](docs/METHODOLOGY.md)，涵盖 point-in-time 数据、已实现的所有者收益 DCF 公式、政策/未来需求研究、可证伪护城河、证据状态、仓位变化、T+1、分红账本、基准构造、缺失数据和可复现边界。

更多资料：[架构](docs/ARCHITECTURE.md) · [运行手册](docs/RUNBOOK.md) · [未来证据流程](docs/FUTURE_EVIDENCE_WORKFLOW.md) · [历史研究说明](docs/LEGACY_RESEARCH_NOTICE.md) · [可复现说明](docs/REPRODUCIBILITY.md)。

## 路线图

### 已实现

- 带本地缓存和 Tushare 数据路径的跨行业筛选。
- 带证据门槛的政策/未来需求映射与仓位状态。
- 护城河注册表、append-only 证据台账与雷达健康输出。
- 以 10% 为基准的五档折现率 DCF 敏感性。
- 黏性锚仓、未来仓阶梯、现金底线和文档化人工覆盖。
- 带 T+1 目标、分红账本和原始价格记账的前瞻 NAV。
- 沪深 300 价格代理比较和公开快照导出。
- 独立双语只读网站与本地实际成交记录。

### 进行中/部分实现

- 公告覆盖取决于 Tushare `anns_d` 权限和网络可用性。
- 一手证据与人工护城河确认仍需人工研究和台账维护。
- 机构估值参考是配置中的人工整理资料，不是自动联网研报服务。
- 前瞻记录仍较短；尚未把更长样本外检验和交易成本分析宣称为完成。

### 未来设想

- 带来源引用和人工批准的 LLM 辅助证据总结。
- 更多数据源冗余、因子/收益归因。
- 更完整的行业里程碑、多基准比较和组合决策审计日志。
- 可复现、含交易成本的滚动样本外检验。

## 局限与免责声明

这是研究软件，不构成投资建议；没有保证收益、券商连接或自动实盘交易。政策方向不保证公司利润，DCF 依赖假设，护城河判断可能错误，公开研报可能不完整或有偏差，Tushare 接口可能失败或需要权限，前瞻 NAV 样本目前有限。沪深 300 对比是原始收盘价代理而非全收益指数。流动性、手续费、最小交易单位、税费和实际滑点都可能让真实结果不同于模型或本地成交记录。

## 安全、协作与许可证

凭据只保存在本地环境文件中；不要添加下单代码或提交私人数据。贡献应包含聚焦测试或可复现检查，并说明对记账、证据状态或仓位上限的影响。见 [SECURITY.md](SECURITY.md) 与 [CONTRIBUTING.md](CONTRIBUTING.md)。项目采用 [MIT License](LICENSE)。
