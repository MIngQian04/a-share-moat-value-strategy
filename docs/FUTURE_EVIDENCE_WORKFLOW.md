# 未来产业证据工作流

这套工作流决定一家公司能否从 `RESEARCH_ONLY` 升级到 2.5% 的
`OPTION_SEED`。未来逻辑分、政策对齐、低估值和底部位置都不能替代证据门。

## 三个文件

- `config/future-thesis-registry.csv`：一家公司一张论证卡，保存需求假设、利润池假设、公司暴露假设、失效条件和下一次复核日期。
- `config/future-evidence-ledger.csv`：只追加、不覆盖的事实账本。一条证据只表达一个可核验判断。
- `outputs/barbell-strategy/future_evidence_readiness.csv`：每次组合运行自动生成的证据门结果。

## 种子仓硬门槛

以下三类证据必须各有至少一条当前有效的支持记录：

1. `DEMAND`：真实需求、投资、招标、装机、用户或使用量正在兑现。
2. `PROFIT_POOL`：收入增长没有被价格战、资本开支、回款或低毛利完全吞噬。
3. `COMPANY_EXPOSURE`：上市公司自身确实拥有对应收入、订单、份额或现金流暴露。

同时必须满足：

- 论证卡四项假设与失效条件完整；
- 来源类型是政府原文、公司法定披露或产业一手数据；
- 有证据日期、发布日期、原始链接和下次复核日期；
- 证据在决策日之前已发布且没有过期；
- 没有当前有效的 `CONTRADICTS` 反对证据。

任何一项不满足，状态保持 `RESEARCH_ONLY`，仓位为零。

## 允许值

- `evidence_type`：`DEMAND`、`PROFIT_POOL`、`COMPANY_EXPOSURE`
- `source_type`：`GOVERNMENT_PRIMARY`、`COMPANY_FILING`、`INDUSTRY_PRIMARY`
- `direction`：`SUPPORTS`、`CAUTION`、`CONTRADICTS`

`CAUTION` 用于记录已经出现、但尚未达到硬性证伪标准的负面事实。它不替代三类
`SUPPORTS` 证据，也不会自动取消2.5%种子仓；风险消除前不得升级核心仓。
`CONTRADICTS` 表示触及预先写明的失效条件，会直接阻止种子仓。

券商观点和媒体报道可以用于发现线索，但不能直接通过种子仓证据门。

## 每次复核

1. 阅读新财报、经营数据、招标和行业一手数据。
2. 为新事实追加一行证据，禁止修改旧事实来美化历史判断。
3. 若证据反对原假设，追加 `CONTRADICTS`，不要删除旧的支持证据。
4. 更新论证卡的 `next_review_date`。
5. 运行 `python3 scripts/run_barbell_strategy.py --offline`，查看生成的证据状态和目标组合。
6. 只有数据完整、日期口径正确后才运行正式刷新与网站发布。

## 状态含义

- `NOT_REGISTERED`：没有论证卡。
- `THESIS_INCOMPLETE`：假设或失效条件缺失。
- `THESIS_REVIEW_OVERDUE`：论证卡已经超过复核日期。
- `EVIDENCE_INCOMPLETE`：需求、利润池或公司暴露证据缺失或过期。
- `CONTRADICTED`：存在当前有效的一手反对证据。
- `SEED_READY`：证据门通过，但仍需财务、估值和底部状态共同通过才能获得2.5%仓位。
- `SEED_READY_WITH_CAUTION`：最低种子证据通过，但存在尚未触发硬性证伪的风险事实；可以保留2.5%试错仓，不能升级核心仓。

`SEED_READY` 不是买入建议，只代表这份未来假设已经达到可以小额验证的最低可审计标准。
