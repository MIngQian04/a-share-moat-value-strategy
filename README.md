# A-Share Moat Value Strategy

一个面向A股的前瞻哑铃投资研究框架：一端持有具备稳定现金流和可验证护城河的锚仓，另一端用小额种子仓跟踪未来产业机会，其余预算保留为现金。

项目的重点不是用历史回测挑选“最优参数”，而是把投资判断拆成可以持续记录、复核和推翻的证据流程。

> 研究项目，不构成投资建议，不连接券商，也不会自动下单。

## 当前公开版本解决什么问题

```text
国家规划与未来需求
        ↓
产业与利润池研究范围
        ↓
公司现金收益、估值与安全边际
        ↓
底部位置与趋势确认
        ↓
2.5% 种子仓 → 5% 确认仓 → 7.5% 核心仓

全A股稳定公司扫描
        ↓
行业地位 + 品牌定价权 / 规模成本代理
        ↓
现金流、ROE、分红覆盖、杠杆与估值复核
        ↓
稳定锚仓
```

组合不为了满仓降低标准。没有足够合格标的、证据尚未完成或行业达到上限时，剩余资金保留为现金。

## 核心原则

### 1. 自动筛选不等于自动决策

系统负责缩小研究范围、检查数据完整性、记录首次失败的门槛，并生成待复核事项。最终的护城河证据判断仍需要人阅读公司公告、政府资料和行业一手数据。

### 2. 护城河是可被推翻的假设

每只持仓必须说明：

- 当前护城河机制；
- 为什么难以复制；
- 应持续观察什么；
- 哪些变化意味着护城河削弱；
- 下一次复核日期；
- 证据变化后应采取什么组合动作。

历史盈利能力只能验证护城河产生过经济结果，不能单独把公司判定为“护城河仍然稳固”。

### 3. 事件发现与护城河判断分离

`scripts/run_moat_radar.py` 检查：

- 公司公告标题中的监管、治理、经营和生存风险关键词；
- 同期季度收入、归母净利润和经营现金流的显著恶化；
- 定期护城河复核是否到期。

规则命中只会生成 `PENDING_REVIEW`。它不会自动写入证据台账、改变护城河状态、调整仓位或交易。接口无权限、断网、离线缓存和“成功扫描但无触发”会被记录为不同的健康状态。

### 4. 仓位随证据双向变化

| 状态 | 单股参考仓位 | 基本要求 |
| --- | ---: | --- |
| `RESEARCH_ONLY` | 0% | 只有研究价值，证据或估值门尚未通过 |
| `OPTION_SEED` | 2.5% | 未来逻辑、现金收益、估值、底部位置和最低证据门通过 |
| `CONFIRMED_BUILD` | 5% | 至少两类产业里程碑得到有日期的一手证据验证 |
| `PROMOTED_CORE` | 7.5% | 三类里程碑全部验证、无风险否决且趋势确认 |

证据恶化时按相同阶梯降低仓位，不允许用叙事跳级。

### 5. 只记录真实前瞻净值

公开组合从明确的起始日以单位净值 `1.0000` 开始。每个新交易日使用上一交易日已经公布的目标仓位计算收益；当天收盘后产生的新仓位只能从下一交易日起生效。

总回报包含原始收盘价变化、现金分红和送转股。现金分红在除权日确认权益、派息日进入待复投资金，并在下一记录日按目标权重统一复投。

## 公开网站

[护城河价值策略](https://ming-daily-portfolio.qianmin968641.chatgpt.site)

网站提供：

- Today、5日、1个月、6个月和1年单位净值收益；
- 当前价格、当日涨跌幅、目标仓位和现金比例；
- 含分红的真实前瞻净值曲线；
- 每位访问者浏览器本地保存的个人起始日；
- 每只持仓的动态护城河档案和待复核事件；
- 中文/英文切换与移动端适配。

网站源码目前作为独立项目维护，避免把部署凭据、构建依赖和策略数据缓存混入策略仓库。

## 项目结构

```text
config/                 研究假设、政策映射、里程碑和证据台账
data_loader/            Tushare与本地缓存读取
fundamental/            财务时点与生存能力检查
industry/               申万行业周期研究
portfolio/              哑铃组合、净值、分红和网站数据导出
selection/              未来产业、护城河证据与雷达规则
valuation/              所有者收益和保守估值
scripts/                日常刷新与策略入口
tests/                  当前规则的自动化测试
docs/                   方法说明与历史研究材料
```

`data/raw/`、`data/processed/`、`outputs/`、`.env` 和网站构建目录不会进入公开仓库。

## 本地运行

### 1. 创建环境

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

需要在线获取数据时，在本地 `.env` 中填写：

```dotenv
TUSHARE_TOKEN=your_token_here
```

不要把真实Token提交到Git，也不要写入示例文件、Issue或日志。

### 2. 准备数据

本仓库不分发Tushare原始数据或完整财务缓存。第一次运行需要自行获取数据，或把已有缓存放入项目约定目录。

```bash
python3 scripts/refresh_rotation_market_data.py
python3 scripts/run_future_demand_screen.py --refresh-financials
```

不同Tushare接口可能需要独立权限。数据接口失败必须被视为“数据不可用”，不能解释为零值或没有风险。

### 3. 运行护城河雷达和组合

```bash
python3 scripts/run_moat_radar.py
python3 scripts/run_barbell_strategy.py
```

没有网络时可以使用已有缓存：

```bash
python3 scripts/run_moat_radar.py --offline
python3 scripts/run_barbell_strategy.py --offline
```

### 4. 运行测试

```bash
pytest
python3 scripts/check_public_release.py
```

## 主要配置与输出

| 文件 | 用途 |
| --- | --- |
| `config/barbell-policy.yaml` | 组合预算、单股上限和种子仓阶梯 |
| `config/future-thesis-registry.csv` | 未来产业假设 |
| `config/future-evidence-ledger.csv` | 未来产业一手证据台账 |
| `config/moat-thesis-registry.csv` | 持仓护城河假设和复核日期 |
| `config/moat-evidence-ledger.csv` | 护城河一手证据台账 |
| `outputs/barbell-strategy/target_portfolio.csv` | 本地生成的目标组合 |
| `outputs/barbell-strategy/portfolio_nav_history.csv` | 本地前瞻净值历史 |
| `outputs/barbell-strategy/moat_radar_alerts.csv` | 本地待人工复核事件 |
| `outputs/barbell-strategy/moat_radar_health.csv` | 数据源健康状态 |

`outputs/` 默认不提交。公开展示组合时，应明确数据日期、计算口径和研究用途。

## 数据与安全

- Token只允许存在于本地环境变量或 `.env`；
- 不提交原始行情、财务缓存、个人投资记录或运行日志；
- 不把接口失败当成无风险信号；
- 不在代码、README、Issue、截图或Git历史中展示密钥；
- 公开前运行 `python3 scripts/check_public_release.py`；
- 网站只展示只读策略快照，不包含Token，也不连接个人电脑或券商账户。

## 关于历史回测代码

仓库保留了一部分早期周期轮动、CPPI和卖出制动研究代码，用于展示项目演化过程。早期回测曾存在时点边界和前视风险，现有结果没有完成独立的逐字段可得日审计，因此：

- 不把旧回测收益、Sharpe或最大回撤作为当前策略成绩；
- 不用旧回测决定当前公司是否入选；
- 不保证旧研究脚本可直接复现或适合实盘；
- 任何重新发布的回测都必须完成point-in-time数据审计、下一交易日执行、退市样本处理、交易成本和缺失数据检查。

详情见 [docs/LEGACY_RESEARCH_NOTICE.md](docs/LEGACY_RESEARCH_NOTICE.md)。

## 开源协作

欢迎提交：

- 一手护城河证据和反证；
- point-in-time数据处理修正；
- 估值、分红和组合记账测试；
- 数据源失败与权限状态处理；
- 无障碍和中英文界面改进。

请不要在Issue、Pull Request或示例文件中提交任何Token、账户信息或付费数据。

## License

MIT License。见 [LICENSE](LICENSE)。
