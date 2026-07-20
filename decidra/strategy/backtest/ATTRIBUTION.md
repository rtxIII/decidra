# 回测子系统来源与许可

本包移植自开源项目 **HKUDS/Vibe-Trading**（<https://github.com/HKUDS/Vibe-Trading>，MIT License）的 `agent/backtest/`。依据 MIT 许可保留原始版权与授权声明。

## 移植清单与改动

| 文件 | 来源 | 移植方式 |
| --- | --- | --- |
| models.py | `backtest/models.py` | 原样移植（纯 dataclass） |
| metrics.py | `backtest/metrics.py` | 原样移植，仅 import 头改为相对导入 |
| engine.py | `backtest/engines/base.py` | 移植 + 裁剪三处耦合（见下） |
| china_a.py | `backtest/engines/china_a.py` | 原样移植，import 改 `from .engine` |
| global_equity.py | `backtest/engines/global_equity.py` | 原样移植，import 改 `from .engine` |
| loader.py | 新写 | Decidra 数据源链适配器（非移植） |

## engine.py 相对上游 base.py 的改动

1. 剪除基本面/事件富集：删 `backtest.loaders.rsshub_events` / `tushare_fundamentals` 导入与 4 个 `_maybe_enrich_*` / 富集辅助函数及其调用。
2. 剪除 P3 范围的可选块：外部 benchmark、validation、run_card 三段（P1 用等权默认基准，绩效仍完整）。
3. 错误路径由 `print(json)+sys.exit(1)` 改为 `raise ValueError`（Decidra 以库方式调用，不作 CLI 子进程）；移除末尾 stdout 打印，`run_backtest` 直接返回指标字典。
4. 新增 F3 护栏：`_plan_open_order` 中目标名义大于 0 却因整手取整归零时告警（避免静默丢单）。

## 未移植（后续阶段）

期货/期权/加密/外汇引擎、optimizers、benchmark.py、validation.py、run_card.py、以及上游 `loaders/`（由 Decidra 自有数据源链替代）。

上游 MIT 许可全文见 Vibe-Trading 仓库 `LICENSE`。
