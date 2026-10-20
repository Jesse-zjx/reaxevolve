# 已发表对标（Introduction）

效力锚点必须是仓库外的已发表工作。本工作的效力锚点是 ORCA + STRICT(v5)，二值、无公开榜，不能写 outperformed the state of the art。

卷期以本地 PDF 首页为准（HANDOVER 把 ERA 误写成 655）。

## 三篇 Nature

| | 效力锚点 | 内部指标 | 和本文的差别 |
|---|---|---|---|
| **Co-Scientist**（Gottweis et al., *Nature* **655**, 487, 2026） | 湿实验（5 药→3 抑制）+ 7 位专家盲评 | Elo 自评；原文称 preliminary | 组件固定；不把执行反馈写成可复用 Skills/Tools |
| **Robin**（Ghareeb et al., *Nature* **655**, 497, 2026） | 一个真实命中 + 逐组件消融 | LLM-judge 锦标赛；并体检 judge 幻觉 | 跨轮带信息，组件仍固定；有 Deep Research 对照（0 命中） |
| **ERA**（Aygün et al., *Nature* **654**, 909, 2026） | 外部既存排行榜 | 树搜索节点分；best-of-N=1000 | 每次从根重启；分连续且可比榜。PDF 标题是 empirical software，不是化学网络 |

我们和 ERA 同类：确定性外部执行器，单点效力高于 Elo / LLM-judge。但 ERA 的分可和公开榜比；我们只能说 N 步通过了事先声明的判据。

白空间（只写这一句）：三篇都不让自己的能力组件被执行反馈改写并跨任务复用。不要写成「因此演化后的冻结资产被测到更强」——那条没有数据。

## 自进化框架

Gao et al., *A Survey of Self-Evolving Agents*, arXiv:2507.21046（TMLR 2026-01）。借用 what / when / how，不宣称对齐已定型分类：

| 轴 | 本文 |
|---|---|
| what | 只演化 Skills/Tools（程序性记忆）；不训练模型参数 |
| when | 只在 Reflect；Explore / Validate 不改资产 |
| how | 结构化 QM 反馈（虚频、端点、失败模式）→ 反思环节的自然语言修订；非梯度、非 RL |

Microsoft *Agentic Evolution*（2026）可作「独立确定性验证器存在时，自主演化报告更稳」的经验观察，不要写成定理。

## 初始技能谱系

TSBench（https://github.com/marvcks/TSBench）：78 个基元反应，GFN2-xTB，单虚频 + 双向 IRC。`assets/initial` 的两份技能和几何工具来自这里。这解释初始臂为什么像一个已发表的 TS 搜索基线，不解释终点臂该不该在气相小分子上赢。78 个里 24 个双重态、4 个带电，STRICT(v5) 计不了分。不当留出测试。

## 糖网络计算（Discussion，不是竞争对手）

Assary / Curtiss 系列（G4 / G4MP2 + SMD，溶剂辅助脱水）和气相热解网络（如 *J. Comput. Chem.* 基准，Hessian 单虚频、无全链几何连续）说明：本工作不在能量水平上占优，占优处是 IRC 双端精确匹配和全链几何连续。不要写机理首创。细节和 DOI 见 `references.md`。
