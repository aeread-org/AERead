# Refund V3.4 开发实验发布摘要

同一220例、110对；Policy82、Intake56、Payments26、Customer56。
每例一个 active LLM seat，其余三席 scripted。所选五组共1,100例。

| 配置 | 严格通过 | 严格失败 | strict未知 |
|---|---:|---:|---:|
| Gemini Lite | 23 | 197 | 0 |
| Gemini Pro，requested low | 192 | 28 | 0 |
| GPT none | 160 | 60 | 0 |
| GPT low | 194 | 26 | 0 |
| GPT medium | 202 | 18 | 0 |

以上不是排名表。Lite是V3.3收集、V3.4重放评分；Pro由父阶段187例加续跑33例组成，
包括一次获授权的未评分frontier重试。原历史660例作为独立投影保留，不静默覆盖旧Pro。

GPT low→medium：同过191、新过11、退步3、同败15；净增8例。
这些是顺序开发实验的探索性描述，存在阶段/时间混杂，不是reasoning单因素孤立因果证明，
也不是held-out、正式publication QC或普遍模型优越性结论。

Failure taxonomy遵循“格式/schema→active action guard→本seat业务分量”的互斥主分类；
可重叠分量不能相加当失败总数。完整逐seat分类和全部11个native leaves有效分母见
[summary.json](summary.json)，逐例记录见[episodes.jsonl](../trajectories/episodes.jsonl)。
不把scripted下游分量错误都归因于active模型，也不把未观测值补成失败。

GPT none已知费用USD2.2565952，独立串行时长不可得；low为USD2.6201742、26.05704257362分钟；
medium为USD2.7856612、27.84865092778分钟。Pro新协议父阶段USD12.47179675、157.0215384993分钟，
续跑USD1.345584875、17.5175691590分钟；完整两阶段合计USD13.817381625、174.5391076583分钟，
包括未进入评分面板的父阶段frontier。历史未知收费仍未解决。模型档位是请求参数，
不独立证明Arena内部reasoning执行；缺失reasoning tokens不补零。

本包公开解析后的typed actions、原生分数、有效性、来源摘要hash和描述性分类，
不公开原始模型回答、提示词、观察内容或完整私有receipt。公开复算会重新生成观察、
重放四席动作，逐例比较native state与11个分量；它不重建原始provider回复或原始seal。
wire、原始围栏变换和计费真实性仍属于本地审计声明，不冒充公开独立认证。

本次打包不产生新模型调用，不修改原实验源码、答案、合同或账本。
V2.5 [issue #309](https://github.com/aeread-org/AERead/issues/309)要求的特定历史文件和计数
仍是另一项工作，本发布不替代它，也不将其标为解决。

复算入口及完整限制见[README](../README.md)和[QC声明](../qc/STATUS.md)。
