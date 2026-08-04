# Five-device stability report

Date: 2026-07-22

## Scope

- Devices: `54481`, `54482`, `54483`, `54487`, `54488`
- Cycles: 3
- Total idempotent publish checks: 15

## Result

- All three cycles completed without an exception.
- No duplicate chapter was created.
- All five draft boxes were empty after the final cycle.
- `54482` retained its expected two chapters; every other device retained one chapter.
- No device became offline, stuck, or quarantined.

## Final platform state

| Device | Target chapter | State |
|---|---|---|
| 54482 | 第1章 灵气复苏 | 已发布 |
| 54481 | 第1章 重生归来 | 审核中 |
| 54483 | 第1章 世界突变 | 审核中 |
| 54487 | 第1章 守夜人觉醒 | 审核中 |
| 54488 | 第1章 传承戒指 | 审核中 |

## Long-run operation

Run the orchestrator with `python main.py`. The publish scan interval is controlled by
`scan.publish_interval_seconds` in `config/config.yaml`; each scheduled scanner job is
coalesced and limited to one active instance.
