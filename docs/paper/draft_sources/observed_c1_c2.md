# C1 / C2 实测（从 `runs/` 抽出）

`runs/` 被 gitignore。初稿数字以本文件为准，不要读 `ARM_REPORT.json` 的 `spent_core_h`（恒为 0：调度器加了 `strict_cache.wall_s`，那些字段是空的）。核时来自各步 `skill_runner_result.json` 的 `core_hours_spent`。

预注册帽是每臂 180 核时。帽没有被执行。终点臂实际花得更多，不是被饿死。

两臂 Reflect 都关闭，账本 66 条、digest `79ad3828a1f42569` 未变。

## C2 — 从 SMILES 重建葡萄糖→HMF（5 步）

不是留出。终点资产是在包含这条路线的战役里成型的。能写的只有：同一验收标准下，两套冻结资产各自有没有交出几何连续链。

| 臂 | 哈希 | 核时 | STRICT | 链 |
|---|---|---|---|---|
| initial | `94458f7c2a70ad9c` | 446.6 | 1/5 | 否 |
| final | `e8c0cafc4de82836` | 555.3 | 1/5 | 否 |

两臂都只过了第 2 步（烯醇→酮）。第 1 步都失败，所以后面即使有过关也不能算交付。

| 步 | 反应 | initial | final |
|---|---|---|---|
| 1 | `O=CC(O)C(O)C(O)C(O)CO` → `O=CC(O)=CC(O)C(O)CO` | rejected 131.6 | rejected 112.5 |
| 2 | `O=CC(O)=CC(O)C(O)CO` → `O=CC(=O)CC(O)C(O)CO` | **STRICT** 47.7 | **STRICT** 81.0 |
| 3 | `O=CC(=O)CC(O)C(O)CO` → `O=CC(=O)C=CC(O)CO` | rejected 61.5 | rejected 139.4 |
| 4 | `O=CC(=O)C=CC(O)CO` → `O=CC1(O)C=CC(CO)O1` | rejected 91.6 | rejected 101.5 |
| 5 | `O=CC1(O)C=CC(CO)O1` → `O=Cc1ccc(CO)o1` | rejected 114.3 | rejected 120.9 |

墙钟：initial 112910 s（2026-09-29 → 09-30）；final 130845 s（09-30 → 10-01）。

## C1 — 按失败模式的修复 / 迁移重放

选的是最低 seq、且账本写得上的修订，不是「文本一定变了」。

- `no_dominant_mode`：seq 7，`.skills/diagnose-ts-failures` v2→v3。前后文本不同。
- `no_endpoint_record`：seq 1，`.skills/qm-execution` v0→v1。快照 `001` / `002` / `013` 字节相同（2480 B，sha256 前缀 `eb930c92bd64`）。这一臂不能把任何结果差写成技能改动。

没有任何 finished step 得到 STRICT。

| 模式 | 种 | 臂 | 步 1 | 步 2 | 核时 |
|---|---|---|---|---|---|
| no_dominant_mode | repair | before | rejected | rejected | 138.3 |
| no_dominant_mode | repair | after | unresolved | rejected | 232.9 |
| no_dominant_mode | transfer | before | rejected | unresolved（步内 180） | 203.2 |
| no_dominant_mode | transfer | after | rejected | rejected | 230.7 |
| no_endpoint_record | repair | before | rejected | rejected | 285.5 |
| no_endpoint_record | repair | after | rejected | rejected | 220.1 |
| no_endpoint_record | transfer | before | rejected | rejected | 209.8 |
| no_endpoint_record | transfer | after | rejected | rejected | 226.3 |

## 正文怎么写

预注册对照没有按声明执行（核时帽未执行；seq 1 文本相同；C2 不是留出），所以它**不能裁决**演化有没有改善发现。实际跑到的计算里，两套冻结资产都只过了同一步。发现本身是学习开启的战役交付的，不是这两臂交付的。

不要写「在 180 核时内」。不要把 C2 画成主图。
