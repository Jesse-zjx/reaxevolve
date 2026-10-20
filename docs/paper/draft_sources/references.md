# 化学与判据文献（Methods / Discussion）

支撑 STRICT(v5)：单一虚频；原始 IRC 两端无约束优化后，中性规范 SMILES 精确匹配；全链原子守恒、几何连续。水平：r²SCAN-3c / CPCM(water)，约 150–200 °C 热水。不是热解。

旧版 `chem-discovery/references.md` 曾主张放宽互变异构端点（InChI 连接层）。五个干式互变异构步已经通过现行判据，旧结论作废。文献只用来标定干式能垒量级和水辅助对照的预期区间。

## 干式分子内质子转移（50–63 kcal/mol）

审稿人会拿水相脱水表观活化能 31–34 kcal/mol 来比本工作的干式互变异构 57–68 kcal/mol。那是不同类别。

- da Silva, *Angew. Chem. Int. Ed.* 2010, 49, 7523. DOI: 10.1002/anie.201003530. 气相 ethenol→乙醛 56.6 kcal/mol；加一个质子穿梭分子约 5.6。
- β-环戊二酮显式水互变，G3MP2//B3LYP. https://pmc.ncbi.nlm.nih.gov/articles/PMC3809839/ 气相分子内 62.9；加 1 个反应性水 27.3。
- Hydantoin 1,3-质子迁移 DFT, *Chem. Phys. Lett.* 2019. 分子内 >50；分子间降低 60–70%。
- 丙酮 keto–enol（沸石中水作共催化剂）, *J. Phys. Chem. C* 2023. DOI: 10.1021/acs.jpcc.3c05709

本工作干式步（电子能 ΔE‡，r²SCAN-3c/CPCM(water)；来自交付包 energetics）：

| 步 | ΔE‡ | 虚频 / cm⁻¹ |
|---|---|---|
| HMF s2 互变异构 | 68.2 | −1449.8 |
| FF s2 烯醇化 | 62.7 | −2042.5 |
| FF s3 烯醇→酮 | 61.0 | −2032.5 |
| FF s5 烯二醇→酮糖 | 57.3 | −1630.0 |
| FF s8 keto–enol | 67.8 | −2137.8 |

HMF 全链（同一份 `energetics_manifest.json`）：s1 脱水 50.2；s2 68.2；s3 脱水 46.6；s4 关环 32.9；s5 芳构化 51.1。葡萄糖→HMF+3 H₂O 电子能 −4.6 kcal/mol。逐步 SMILES 以交付包为准，不要手抄旧 HANDOVER。

## 水相糖文献（对照，不是验收）

单水穿梭可把干式势垒压到约 40–50%。现行判据拒收两端都带游离 H₂O 的旁观水步，所以这些文献标定的是设计选择的代价，不是可交付边。

- Assary, Kim, Low, Greeley, Curtiss, *Phys. Chem. Chem. Phys.* 2012, 14, 16603. DOI: 10.1039/C2CP41842H. G4MP2+SMD；solvent-assisted dehydration。
- Assary et al., HMF 收率预测（Lewis 酸/溶剂）. https://www.osti.gov/servlets/purl/1755729 水中质子转移 32.5 kcal/mol；实验果糖脱水 31–34。
- Zhang, Das, Assary, Curtiss et al. https://www.osti.gov/servlets/purl/1370175 ESI-MS+G4MP2；keto/enol 都是局域极小，实验区分不了。

负对照 A（强制水中继）未找到 TS，已归档，不引用为「条款会拒」。条款分辨力看负对照 C。

## IRC 为什么要求双端精确匹配

- Fukui, *Acc. Chem. Res.* 1981, 14, 363.
- Maeda, Harabuchi, Ono, Taketsugu, Morokuma, *Int. J. Quantum Chem.* 2015, 115, 258. DOI: 10.1002/qua.24757

IRC 连的是最近局域极小。单虚频不能保证连的是声明的那一对物种。负对照 C：三个线性插值猜测都是干净单模鞍点（−539 / −127 / −921 cm⁻¹），IRC 对不上声明端点，全部 rejected。只问「是不是过渡态」的判据会收下它们。

和已发表糖/热解网络的方法差：

| | 端点 | 全链几何连续 | 溶剂 | 能量 |
|---|---|---|---|---|
| 本工作 | 原始 IRC → 中性 SMILES 精确匹配 | 是 | CPCM(water) | r²SCAN-3c 电子能 |
| 气相热解基准网络（如 *J. Comput. Chem.* 54/84） | 仅 Hessian 单虚频 | 否 | 气相 773 K + SMD 对照 | DLPNO-CCSD(T)/CBS + RRHO |
| Assary/Curtiss | 连接层 + 标注互变 | 否 | SMD + 显式水 | G4 / G4MP2 |

不声明精度或机理领先。
