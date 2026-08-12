# P2.1 Protocol Freeze Manifest

> 本 manifest 是**独立于 protocol 文件**的 freeze 记录，不回改 frozen protocol（回改会使
> blob SHA 失效）。权威 protocol 定义 = blob `7f09148...` at commit `293ca11...`。

## Freeze 签字

```text
Frozen protocol version    P2.1 Preregistration v1.3
                           phase3_p2_1_preregistration_v1.3.md

Protocol commit SHA        293ca11cbcfdae7d82ca21e184e44426999ea349
Protocol blob SHA          7f09148b09f10b3a2ef89264e2031e3a5eca28a6

Freeze Review              APPROVED（审查 2608120033 第五轮）
Freeze basis               commit 293ca11 / blob 7f09148 / CI run #87 success
Protocol modifications     PROHIBITED after this point
                           （除非声明放弃当前 protocol 并另起版本化新协议）

Closure 状态
  C1-C6（第四轮六项）       CLOSED
  closure-1（第五轮 §1）    CLOSED — B-recovery E1-E4 family aggregation
  closure-2（第五轮 §2）    CLOSED — B-core FAIL 时 P-002 维持 C（mechanism-only）
```

## 阶段切换

```text
Protocol Definition        → DONE（v1.3 FREEZE APPROVED）
Implementation Conformance → ACTIVE（P2.1A implementation may begin）
```

## P2.1A 执行顺序（签字）

```text
[1] Protocol Freeze                     DONE / APPROVED
    commit = 293ca11... / blob = 7f09148...
[2] 创建 P2.1A sentinel                 DONE（p2_1a_sentinel.json, state=UNCONSUMED）
[3] 开发 P2.1A implementation           NEXT
    只实现 v1.3；不改变 protocol；不查看正式 Y/Gate outcome
[4] synthetic / unit / invariant tests  允许；不构成 formal exposure
[5] Implementation Review               检查代码与冻结协议逐项同构
[6] 锁 implementation SHA               代码完成 + 测试通过 + 接触 A outcome 之前
    + clean worktree + dependency manifest
[7] Step-0 data sufficiency             只读 eligible/trigger session counts；禁读 Y/gain/Δ/CI
[8] 若 DATA SUFFICIENT → formal exposure → sentinel UNCONSUMED→CONSUMED → 一次性 Gate
[9] 输出唯一 verdict                    PASS / FAIL（DATA INSUFFICIENT 在 Step-0 停止）
```

## Implementation Review 强制项

- stable hash 须用 `hashlib.md5/sha256` 机械映射，**禁止** Python built-in `hash()`；
- B3 trigger map 一次生成后固化为 artifact，bootstrap 只能查表，不能重随机；
- formal pipeline 不得有隐藏 config 可改变 `0.95 / Q95 / 15min / 3cycle / W=10 / 0.9 / B1 ε / bootstrap seed/N`；
- Step-0 与 outcome computation 在代码/API 层物理隔离（防"只想看数量"却顺手算出 Y）；
- implementation tests 证明 fail-closed、deterministic replay、跨运行 reproducibility；
- implementation SHA 在**正式结果第一次暴露之前**锁，不能提前声称 frozen。

## Sentinel artifact

`results/raw/phase3_p2_1/p2_1a_sentinel.json`（state=UNCONSUMED，记录 frozen protocol
commit/blob；formal exposure 后 state→CONSUMED，永久禁止 rerun）。
