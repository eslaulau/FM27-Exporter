# FM27 原生引擎逆向项目进度日志

> 本文件是项目的持续进度台账。每轮推进均在本文件追加日期条目，并同步更新相关分析报告/脚本；不得只在对话里报告进展。
>
> 当前基线：FM27 27.1.1+2511875；目标模块 fm_Data/Plugins/x86_64/game_plugin.dll；所有函数地址均为该 DLL 的 RVA，ImageBase 为 0x180000000。

## 项目目标与推进标准

本项目不是先猜战术，也不是用现实足球理论解释引擎。目标是从 FM27 原生比赛引擎中确认：

1. 战术输入（阵型、位置、角色、职责、个人指令、团队指令）被读取/映射的位置；
2. 原生结构体中的输入字段、派生字段及状态门控；
3. 这些值如何进入候选行为、方向/位置计算、传球/射门选择；
4. 计算结果如何影响事件质量、射门结果与比赛结果；
5. 形成可复核的“战术设置 → 引擎内部数值 → 球员行为/决策 → 比赛结果”因果链后，再反向设计四后卫战术。

**证据规则：**直接内存读写、函数调用、数值计算和数据结构是已确认事实；UI 语义、角色/职责映射、最终行为效果和胜率影响，在得到映射或实测前一律标注为未确认。不得把偏移名称或函数名称当作充分证据。

---

## 2026-11-28：Run #7 完成，方向分布参数上游初始化链开始收敛

### 工作流与产物

- GitHub Actions：[Run #7 — Trace MATCH_PLAYER direction distribution field producers](https://github.com/eslaulau/FM27-Exporter/actions/runs/46124508570)
- Run ID：46124508570；Run number：7；状态：completed / success
- 触发 Commit：ffd0c7bdf55fd200df78172a4d93385ab3e56511
- Artifact：FM27-Native-Hotspots，ID 15255297010
- Artifact SHA-256：7596b26c66518b15e207b9403bce18d159e0733898d82a47fd4312199bb821ef
- Artifact 大小：1,261,823 bytes
- Ghidra：12.2；本轮脚本从 PE Exception Directory / .pdata 修正原生函数边界，保持前几轮验证过的函数体和 CALL xref 提取方式。
- 结果文件：native-hotspot-summary.txt、native-hotspot-decompilations.txt、native-hotspot-xrefs.txt、direction-generator-fields/match-player-field-xrefs.json。

Run #7 的扫描统计：
- PE runtime function ranges：144,876
- candidate functions：1,686
- scanned functions：1,679
- scanned code：14,275,767 bytes
- field references：11,722
- unique consumer functions：1,106

### 新增确认：方向分布参数上游写入者已有可反编译函数体

Run #7 已成功恢复并反编译以下重要函数：
- 0x48334D0：MATCH_PLAYER 方向分布概率门控字段写入者，函数体 10,271 bytes；
- 0x46E4740：方向分布中心/边界参数更新者，函数体 906 bytes；
- 0x47E44C0：方向分布第二阶段门控字段写入者，函数体 6,058 bytes；
- 0x3BDB0：方向分布次级概率字段写入者，函数体 2,393 bytes；
- 0x3C720：方向分布基础字段初始化器，函数体 3,093 bytes；
- 0xF8050：球员/移动上下文的次级参数写入者，函数体 9,435 bytes；
- 0x452FF10：方向分布字段批量初始化器，函数体 24,143 bytes；
- 0x4969440：派生字段范围写入者，函数体 9,921 bytes；
- 0x3798830：派生字段系数写入者，函数体 665 bytes。

### 新增确认：0x3C720 是多字段基础初始化器，但 UI 语义尚未解码

0x3C720 不是单一参数的搬运函数。它多次调用 0x4704100，以不同的数值 ID 和 flag 组合读取参数，然后写入多个方向分布基础字段。例如：

| accessor ID | 输出字段 | accessor flags |
|---:|---:|---:|
| 0x20 | MATCH_PLAYER+0x22B0 | 0x200500 |
| 0x21 | MATCH_PLAYER+0x228C | 0x8200500 |
| 0x14 | MATCH_PLAYER+0x2208 | 0x8200500 |
| 0x23 | MATCH_PLAYER+0x21A0 | 0x8200500 |
| 0x18 | MATCH_PLAYER+0x2184 | 0x200500 |
| 0x36 | MATCH_PLAYER+0x2228 | 0x200400 |
| 0x33 | MATCH_PLAYER+0x2188 | 0x200002 |
| 0x3D | MATCH_PLAYER+0x2C5 | 0x200100 |
| 0x39 | MATCH_PLAYER+0x2C7 | 0x200100 |
| 0x35 | MATCH_PLAYER+0x2C6 | 0x200100 |
| 0x31 | MATCH_PLAYER+0x2C8 | 0x200100 |
| 0x2C | MATCH_PLAYER+0x2170 | 根据分支为 0x201000 或 0x200000 |
| 0x38 | MATCH_PLAYER+0x2280 | 0x8008000 |
| 0x15 | MATCH_PLAYER+0x21F4 | 0x200100 |

后续还会写入 +0x2238、+0x227C、+0x2174、+0x21C0、+0x2298、+0x218C、+0x221C、+0x226C、+0x223C、+0x2278、+0x217C、+0x21BC 等字段。函数还根据比赛上下文、+0x21F8、球员状态以及球队扩展标志调整部分数值。

**严格结论：**0x3C720 证明这些方向分布字段由一个多参数访问器按 ID/flags 取得基础值，再经上下文修正写入；但仅凭 ID 数值和 flag 不能把它们命名为“压迫”“站位”“传球风险”或某个 PI。必须先解码 0x4704100 的查值规则，再与托管枚举/战术输入表对齐。

### 新增确认：0x48334D0 是上下文与概率状态混合的复杂写入器

0x48334D0（10,271 bytes）：
- 从 MATCH_PLAYER 周边上下文对象读取多个基线参数（包括 +0x2198、+0x21B0、+0x21B4、+0x219C、+0x2284、+0x2288、+0x22B4 等）；
- 调用 0x4704100，参数 ID 为 0x42、flags 为 0x8000000；
- 按阶段/侧向/球队及球员状态、概率阈值、比例缩放和若干条件分支，多次更新 MATCH_PLAYER+0x21F8；
- 在特定分支中消费与 0x45AC0 相同家族的 seeded PRNG 状态。

因此 +0x21F8 确实是条件驱动的概率门控字段，不是简单的静态属性映射；但它的基础来源、各分支的足球语义和对具体角色的影响尚未建立。

### 新增确认：0x46E4740 更像跨槽位的分布参数调节器

0x46E4740 遍历球队的 slot-record 指针数组，并根据输入的 bit flags 改动对应记录内的若干字段，例如：
- +0x2C4、+0x123B、+0x2180
- +0x22A0、+0x228C
- +0x222C、+0x22B8

它会按位标志对参数做增减并限制在边界内。这是一个有状态的参数调节路径，不应直接等同于某个具体战术指令。需要继续追踪调用者提供的 bitset、更新数组如何生成，以及这些更新何时作用于球员槽位。

### 当前保留的行为链

~~~text
角色/职责/个人指令/团队战术（上游 UI 映射仍待解码）
                  ↓
0x4704100：按 ID + flags 读取匹配参数（本轮定位，待反编译）
                  ↓
0x3C720 / 0x48334D0 / 0x46E4740 / 0x47E44C0 / 0x3BDB0
                  ↓
MATCH_PLAYER +0x2170 / +0x21F0 / +0x21F8 / +0x228C / +0x22A0 / +0x22B0
                  ↓
0x45AC0：消费 seeded PRNG，生成 +0x1E40 / +0x1E54 等派生参数
                  ↓
0x496F840：360 方向环的候选方向采样与角度惩罚
                  ↓
0x492D060：最近对手位置/朝向参与的空间投影
                  ↓
0x494F820：历史时间样本、插值、距离和角度容差验证
                  ↓
候选行为/位置选择（还需连到真正的最终位置提交点）
~~~

### 射门/xG 线索的边界维持不变

0x4C01760、0x4D1F0、0x164680、0x166400、0x1691C0 仍只证明 XG/射门事件分类、几何标记、球员关联、统计更新和事件登记；**尚未发现最终 xG 概率公式，也未证明 XG_SHOT_DATA 的实际数值 payload 是在这些函数中写入。**继续将 xG 概率公式和事件/UI 记账逻辑严格区分。

### 下一轮执行项（Run #8）

优先级按“是否能解码战术输入的来源”排序：

1. 新增反编译 0x4704100：确定 accessor 如何根据 ID/flags 取得值，是否映射到角色、职责、PI、TI 或球员/比赛状态。
2. 反编译 0x4815250、0x4822D50：它们是方向参数初始化路径的同层 helper；确认它们是数值转换、状态读取还是上下文检查。
3. 追踪 0x3C720 的调用者和参数对象来源，并将 accessor ID 与托管枚举、导出配置/战术结构对应。
4. 追踪 0x46E4740 的 bitset 生产者，确认这些增减操作由什么比赛状态触发。
5. 在获得 UI/托管侧映射后，制作小范围对照表：每个 UI 设置改变时，哪些 native ID/offset 发生变化；避免只依赖静态代码猜测。
6. 只有完成输入映射，才继续将候选行为与最终球员坐标/动作提交点连接，继而研究传球、射门质量与赛果。

Run #8 不重复全量 IL2CPP/字段扫描；复用当前 .pdata 范围、字段 scanner 与热点 Ghidra 快速工作流。


### 本轮补充：Run #7 原生参数路径细化

已将 Run #7 的函数级细节同步追加到主分析报告第 10 节：
- 报告：[Run #56 / CandidateMovementMechanics（已追加 Run #7）](https://github.com/eslaulau/FM27-Exporter/blob/main/docs/reverse-engineering/FM27_27.1.1_Run_46115767659_CandidateMovementMechanics_20261128.md)
- 报告更新 Commit：`6663af86f89e046d099b4559bd4e6142f93b5e26`
- 新增内容：`0x3C720` 的 accessor ID/flags → MATCH_PLAYER 字段表；`0x48334D0` 对 `+0x21F8` 的状态依赖更新；`0x46E4740` 的 11 槽位位掩码参数调节；`0x47E44C0` 与 `0x481A6A0` 的 Shot Zone 直接调用关系。

**防止误归因的关键修订：**`0x47E44C0` 的直接 caller 是 Advanced Shot Zone 主处理函数 `0x481A6A0`，所以不得把它简单标成通用跑位/战术参数加载器。后续必须区分一般球员参数初始化与 Shot Zone 专用空间处理。

### Run #8 状态（本轮提交后）

- Workflow：[Run #8](https://github.com/eslaulau/FM27-Exporter/actions/runs/46126771752)
- Commit：`c6afa51c23f3a73ee007ea3c8d06ee8c79d446cb`
- 最近一次查询仍显示 `in_progress`，卡在热点 Ghidra 反编译步骤；字段扫描、Java 21 和 Ghidra 下载均已成功，Artifact 尚未生成。
- 目前不将它写成成功或失败。完成后必须读取 Artifact 的实际反编译和 xref，再记录结果。


### 再核对发现：MATCH_PLAYER 初始化入口与概率量修正

主分析报告第 10.6–10.7 节再次补充了 Run #7 的两条关键路径：
- `0xF8050`：在一个函数中注册球员比赛对象到 team 集合、绑定两套槽位记录、写入 side/OOP slot，并用 seeded PRNG 初始化多组字段。当前把它列为 **MATCH_PLAYER 实例初始化候选入口**；尚未把它定性成已证实的 C++ constructor，等待调用者/调用约定确认。
- `0x3BDB0`：先将 `+0x2230` 复制到 `+0x21F0`，再按比赛阶段、两队时间/状态和多个内部参数进行调整、缩放及 0–100 钳制；直接 caller 为 `0x185090`。这是一段上下文修正，不是已确认的 PI/TI 数值直通映射。
- 详细报告更新 Commit：`778ce5b4ed50c48b643fe7d74750395dc2c9eb3f`。

下一阶段要把创建时的初始化（`0xF8050`）与初始化之后的参数刷新（`0x3C720/0x3BDB0/0x48334D0`）分开追踪。Run #8 已将 `0x4815250` 等 helper 加入反编译目标，用于验证这条链。


## 2026-11-28：Run #8 完成，转向追踪参数源数据（Run #12 进行中）

### Run #8 已确认成功

- Workflow：[Run #8](https://github.com/eslaulau/FM27-Exporter/actions/runs/46126771752)，Run ID `46126771752`，success
- Commit：`c6afa51c23f3a73ee007ea3c8d06ee8c79d446cb`
- Artifact：`15256007922`，1,282,754 bytes
- SHA-256：`7440afdec86a144395120bc1a212c0b8302815fb339a820a22595ae6f3b1cb6b`
- 输出目录：`native-hotspot-summary.txt`、`native-hotspot-decompilations.txt`、`native-hotspot-xrefs.txt`、`direction-generator-fields/`
- 本轮函数体：`0x4704100` 2,354 bytes；`0x4815250` 1,422 bytes；`0x4822D50` 2,185 bytes；`0x4984DD0` 132 bytes；`0x47F1E70` 679 bytes。

**修正此前对 accessor 的理解：**`0x4704100` 不是“读取战术枚举”的简单 getter，而是参数值计算器。它读取 `MATCH_PLAYER+0x480+(signed char)ID` 的参数字节；当 ID ≤ `0x0E` 时先乘以 5，其余 ID 保留原尺度。当前已看到的调用 ID 达到 `0x44`。因此不能把这些 ID 直接对应到 TeamInstruction / PlayerInstruction。

### Run #8 核心公式已解码

第三参数是组合 flags，控制以下修正项：
- 球员时间/阶段字段 `+0x1228) 与球队系数 `+0x149FC`；
- 球员 `+0x21F8/+0x21FC/+0x21F0/+0x22A8/+0x2214/+0x2234` 分别与球队系数 `+0x149F0/+0x149E8/+0x149EC/+0x149E4/+0x14A00/+0x149F8` 组合；
- 有效 OOP 槽位、当前阶段 PI 记录及 `+0x21CC` 门控；
- 部分 flags 附加常数、按 ID 类别变换值；
- `param_3 & 0x3FF) 最低置位 bit 选择 `VA 0x18507A440` 的 10 组非线性归一化曲线之一（每组 12 bytes）；
- 特定 flags 下通过 team `+0x34ED` 关联索引递归计算另一球员的同一参数，再按其 `+0x11C8` 权重与本球员值混合。

由此得到的正确数据链是：

```text
MATCH_PLAYER +0x480..+0x4C4 参数字节向量
                   +
TEAM +0x149E4..+0x14A00 系数候选区
                   +
球员时间/阶段/PI/槽位/球队状态
                   ↓
0x4704100 动态参数值计算器（flags + 参数类别 + 曲线 + 关联球员混合）
                   ↓
0x3C720 / 0x48334D0 等初始化或刷新函数
                   ↓
MATCH_PLAYER 的 +0x2170/+0x21F0/+0x21F8/+0x22A0 等派生字段
                   ↓
0x45AC0 / 0x496F840 / 0x492D060 / 0x494F820
                   ↓
候选方向、空间投影和候选时空验证
```

**未确认：**`+0x480..+0x4C4` 字节向量的真正语义（是否包含球员属性、角色参数、配置参数或组合数据）；team 系数块各字段写入来源；10 个曲线表项具体常量；任何 UI 指令的一一映射。

### 同轮 helper 的准确边界

- `0x4815250` 组合两侧团队统计子对象、活动球员槽位、球员 `+0x22F8` 权重、双方时间/阶段字段和多个 team 数值，产出 0–100 的相对指标；目前不能擅自命名为控球率、压迫或实力值。
- `0x4822D50` 仅在 team `+0x1556E == 1` 时生成扩展模式状态 bitmask；由时间、阶段、对手和比赛状态共同决定。
- `0x4984DD0` 是双方时间/阶段先后比较器。
- `0x47F1E70` 是状态/历史记录容器更新，不等于最终球员移动指令。

### 相关仓库提交

- 主分析报告新增 Section 11：`0408e14e0f93006c798a757c64717ad10a684de1`
- Ghidra 参数向量/队伍系数写入者自动 seeds 与归一化曲线导出：`7adc3e15545a850aaa46fe6827f8b9d9265a5cec`
- 扩展字段扫描器：`f93364af559445415d063df7260b985d9d232333)
- 修正包装脚本换行：`2af97d1bd8ac179fe998830bf16a60d69c064c7f`
- 工作流调用扩展扫描器：`1276d6572dd3f7c24263f17532fbac291a188bc4`
- 将 accessor 函数名改为中性、符合证据的 `MATCH_PLAYER_PARAMETER_VECTOR_VALUE_EVALUATOR`：`84d94c7b2b129cf1d9526e86d216097ffebd8a13`
- 工作流监听 scanner 的源文件变化：`3d41e89eacf353667426a02d3afd162bd7e90392`

### 失败/取消工作流如实记录

- Run #9（`46127545533`）被更新工作流时的 `concurrency.cancel-in-progress` 取消；不产生有效分析结论。
- Run #10（`46127579330`）在扫描器导入时失败：包装文件生成了字面量 `\\n`，导致 Python `SyntaxError`，不是扫描结果或引擎错误。
- Run #11（`46127754952`）再次被 Run #12 的新工作流运行取消。
- Run #12（[Actions](https://github.com/eslaulau/FM27-Exporter/actions/runs/46127758872)）使用修复后的脚本和最新工作流；最近一次查询为 in progress，正在执行参数向量/系数区扫描，尚无有效结果。

### Run #12 预期交付 / 下一步

1. 直接找出 `+0x480..+0x4C4` 参数向量固定偏移的写入函数与批量拷贝函数。
2. 找出 `+0x149E4..+0x14A00` 8 个系数候选字段的生产者/初始化器。
3. 从 `parameter-constant-tables.txt` 读取 `VA 0x18507A440` 的 10 行常量，确认曲线公式参数。
4. 检查新自动 seeds 的函数体与 caller/callee，建立数据从初始化/托管结构传到 MATCH_PLAYER 的路径。
5. 在数据源确立后，再尝试对应到托管层的角色/职责/PI/TI；不得先猜 UI 语义。


### 本轮继续推进：补齐 `0x3C720` 参数索引落点表

在 Run #8 的真实伪代码中，进一步逐项核对了参数 ID → evaluator flags → MATCH_PLAYER 写回字段，已将表格加入主报告 Section 11.7：
- 例：`0x20 → +0x22B0`、`0x21 → +0x228C`、`0x44 → +0x22A0`；
- 同一索引在不同上下文可复用，如 `0x3D` 写入不同字段；
- `+0x22B8` 在某个状态分支使用动态参数 `0x3C`，否则来自直接公式；
- `+0x2238` 使用动态高字节参数，不能仅按低字节把它当成固定 `0x12`。

这一步只确认数值数据流落点，不把参数命名成某项角色、属性或 PI/TI。
- 主报告更新 Commit：`a40db2b6afff8661d35db51ef185134ecf1028d6`

### Run #12 最新状态快照

- Workflow：[Run #12](https://github.com/eslaulau/FM27-Exporter/actions/runs/46127758872)
- 参数字节/球队系数扫描：success
- Ghidra 12.2 下载：success
- Ghidra 热点反编译：in progress
- Artifact：尚未生成；本轮没有新增数据源结论。


## 2026-11-28：Run #12 完成；候选位置机制更清楚；参数源扫描已开始纠正栈帧误报

### Run #12 实际结果

- Workflow：[Run #12](https://github.com/eslaulau/FM27-Exporter/actions/runs/46127758872)，success
- Artifact：`15256413119`，3,399,576 bytes
- SHA-256：`9c51c6ece6e594f511767e66c42c26d1bcdd96ceadd2c0a4cbbdca68545cb742`
- 主报告新增 Section 13，Commit：`758c2f50401274a8ab6ba70d1d21d36208005021`

### 实质结论 A：10 组非线性归一化曲线常量已解出

曲线表在 RVA `0x507A440`，每项 12 bytes。字段位置现已按反编译指令确认：
- +0 divisor
- +1 slope
- +2 intercept
- +3 denominator
- +4 bias
- +8 int32 threshold

10 组数值已经全部写入主报告 Section 13.1。这里纠正了最初导出脚本的标签错误：+3 是 denominator，不是 bias。曲线计算为：

```text
q = min(value, value * value / divisor)
value = bias + (q * slope + intercept) / denominator
if value >= threshold:
    value = threshold + 2 * (value - threshold)
```

低 10-bit 曲线 selector 为 0 时走独立的 `(value + 3) / 5` 路径。

### 实质结论 B：TEAM 系数块读多写零，写入源尚未找到

本轮固定偏移字段扫描：
- `TEAM+0x149E4`：R×1，W×0
- `+0x149E8`：R×3，W×0
- `+0x149EC`：R×3，W×0
- `+0x149F0`：R×5，W×0
- `+0x149F4`：R×3，W×0
- `+0x149F8`：R×3，W×0
- `+0x149FC`：R×3，W×0
- `+0x14A00`：R×3，W×0

发现三处读取同一系数块的参数计算器：
- `0x4704100`；
- `0x474F370`；
- `0x475D640`。

已把后三处的反编译种子加入专项 Ghidra 脚本。TEAM 系数槽位可能通过更大对象复制、配置解包或外部初始化写入，但目前没有直接写者证据。

### 重要质量修正：Run #12 动态写入者列表存在 RBP 栈帧误报

Run #12 自动选出的最高命中函数 `0x46A8C40` 有大量表面上的 `+0x480) 写入，但指令基址是 RBP，函数序言将 RBP 设为 RSP，即这些是栈局部变量。字段 scanner 只知道位移，不知道对象类型，因此不能把这些函数当成 MATCH_PLAYER 参数源。

已修正 `TraceParameterSources.java`：
- 排除 RSP 栈引用；
- 仅当函数前 12 条指令证实 RBP 被设为 RSP 栈帧时，才排除 RBP 命中；
- 没有栈帧证据的 RBP 引用保留，避免误删真实对象基址寄存器；
- 增加 evaluator seeds `0x4704100`、`0x474F370`、`0x475D640`；
- 修复摘要中 CALLEE 数量受 CALLER 循环变量覆盖的计数错误。

代码 Commit：`dbec035a901c54a35e8a76541a261daede92d5d7`

### 参数源专项 Run #2

- Workflow：[Focused Parameter Source Run #2](https://github.com/eslaulau/FM27-Exporter/actions/runs/46129258995)
- 当前状态：字段扫描仍在执行；尚无 Ghidra Artifact。
- 目标：只保留结构基址可信的参数向量/TEAM 系数写入候选，然后反编译写入者和三个参数计算器变体。
- Run #1 已成功，但未使用栈帧过滤；其动态写入者候选不作为有效结论。

### 球员行为链下一目标保持不变

当前已确认：
`0x45AC0 → 0x496F840 候选位置/方向记录 → 0x494F820 历史样本与时空验证 → 0x4865900/0x4873400 阶段/OOP 候选筛选 → 0x4874AC0 候选状态/PI gate`。

仍未确认的是**被接受的候选位置被谁提交为球员移动目标/运动状态**。下一轮要把调用者/间接调用/对象记录消费者连起来；与此同时，只继续追参数源，不扩展到无关模块。


## 2026-11-28：Movement Commit Run #2/#3 完成；候选排名与接受链推进一层；参数源扫描改用 UnwindInfo

### Movement Commit Run #2：此前超时的大型消费者成功反编译

- Workflow：[Run #2](https://github.com/eslaulau/FM27-Exporter/actions/runs/46129914873)，success
- Artifact：`15256934221`，307 KB；SHA-256 `42d5f78f74fd6b1122bf2f286ddd5334d692ae49642a98b96a136053852d0b23`
- 提升 Ghidra timeout 后，`0x4936080`（53,578 bytes）完整反编译，约 6,417 行 C 伪代码。

**新增机制证据：**
- `0x4936080` 初始化多槽输出候选记录；
- 遍历多组历史时间/候选位置样本；
- 使用 360 单位角度表计算候选相对方向；
- 以位置距离、角度差、tick/phase、球队状态、球员状态和 PI/OOP 槽位状态等共同更新复合累计代价；
- 对候选执行 `0x494DA10` 额外时空门控；
- 只有候选代价改善时才覆盖输出记录中的坐标/方向/距离/flags；
- 返回输出候选结构，未在本函数中发现 `MATCH_PLAYER+0x140/+0x144` 当前位置写回。

这说明它是候选位置/轨迹排名器，不是最终移动执行器。

### Movement Commit Run #3：找到候选排名器唯一直接 caller

- Workflow：[Run #3](https://github.com/eslaulau/FM27-Exporter/actions/runs/46130255627)，success
- Artifact：`15256564698`，308,866 bytes
- SHA-256：`bbb07ef46c0ddf189c2ccee7384c0b01a39b0699cee12f9457bca2efc203b9ba`
- Scanner：144,876 runtime functions；13 个目标；191 个候选 caller；444 个 CALL/JMP/Jcc；14 个静态函数指针命中。

**唯一直接调用点：**
- `0x4936080` 的直接 caller 是 `0x48ADC70)；
- CALL site RVA `0x48ADCF5)；
- caller range `0x48ADC70–0x48ADE5F)。

`0x48ADC70` 的接受流程：
1. 调用 `0x4936080` 写本地候选输出；
2. 读取候选区间/状态值，结合 TEAM 当前 tick `+0x154EC)、候选边界及若干 flags 判断；
3. 失败分支可能清除参数 flags 后递归重试；
4. 接受分支调用 `0x4C35210(dst, candidate, 0xF0)` 将候选记录传给上层输出缓冲区。

`0x4C35210` 在大量不同模块中以 `(dst, src, size)` 形式调用，size 包括 `0xC0/0xD0/0xF0)、`count*4`、`count*0x10` 等；它没有独立 `.pdata` 函数边界。当前只能标为**通用内存/记录复制辅助入口候选**，不能命名为 Movement Director 或最终移动提交函数。

### Movement Commit Run #4 正在进行

- Workflow：[Run #4](https://github.com/eslaulau/FM27-Exporter/actions/runs/46130539648)
- 新增扫描目标：`0x48ADC70` 和 `0x4C35210)；
- 目标：找出 `0x48ADC70` 的 match tick/player update caller，以及 `0x4C35210` 的函数边界/调用者特征；
- 当前 Ghidra 反编译步骤 in progress，尚无 Artifact。

### 参数源专项 Run #4 失败于过滤质量，不是引擎分析

- Workflow：[Parameter Source Run #4](https://github.com/eslaulau/FM27-Exporter/actions/runs/46129581510)，success
- Artifact：`15257088899`，2,198,011 bytes；SHA-256 `3131dd7c873146907049d9c8a8bfe27b49c2546b92e616bc5ecb75da4e870def`
- 实际 scanner 统计：RSP base refs 排除 248；通过旧 prologue 识别的 RBP 栈帧 refs 为 0；保留 RBP refs 1,300。
- 最高命中 `0x46A8C40` 有 262 个表面写引用，全部为 `[RBP+offset]`。其 Ghidra 伪代码中有大量栈局部变量，故这些命中不是 MATCH_PLAYER 参数向量写入。
- 其他 8 个最高命中候选也同样全部是 RBP 基址；无一个 TEAM 系数字段有直接写操作。

**质量修复：**不能只根据前 12/32 条指令来判断 RBP 栈帧。现已改用 Windows x64 PE `.pdata` 对应的 UNWIND_INFO：
- header 第 4 byte 的 low nibble 是 frame register；
- register id 5 = RBP；
- 若 UnwindInfo 声明 RBP frame register，则过滤该函数全部 RBP+offset 目标命中；
- 无 frame register 的函数才回退检查前 32 条 prologue 指令。
- 修正 Commit：`1e11d5a018fa28b2203edd8155326e7b4033910b`

参数源专项 Run #5：[Actions](https://github.com/eslaulau/FM27-Exporter/actions/runs/46130421400)，目前扫描成功，Ghidra 反编译 in progress。完成前不认定参数向量写入源已找到。

### 本轮分析报告与记录提交

- Movement Commit 新增 Section 15（Run #2/#3 的候选排名/接受链）：`91cf12d8027f394617fa56dbf9c2dfc8ea864b52`
- UnwindInfo 过滤机制记录（Section 13.7）：`165e96659e0bb935e7f1a32e8984468985b72d67`
- 本项目持续台账在本次再追加上述工作流结果、当前状态和下一步，不将未完成运行写成结论。

### 下一步只做两条直接任务

1. **球员移动提交：**由 Run #4 追 `0x48ADC70` 的直接 caller 和接受记录的后续消费者；定位真正每 tick 运动状态/目标位置写回字段。不要把 `0x4C35210` 当作运动算法。
2. **战术参数来源：**等 Run #5 检查 UnwindInfo 过滤后的真实对象基址候选；无可信固定偏移写入时，改从 `0xF8050`、`0x185090`、`0x3C720` 的对象初始化和数据复制源追踪参数向量。TEAM 系数块目前读多写零，继续沿整块对象复制/配置装载查找。

行为链闭合后立即转向射门/传球结果实际计算与比分事件写入，不做无关系统扩展。


## 2026-11-28：Movement Handoff Run #1 完成；找到候选记录写入 MATCH_PLAYER 的状态区

### Movement Handoff Run #1

- Workflow：[FM27 player movement handoff Run #1](https://github.com/eslaulau/FM27-Exporter/actions/runs/46130992721)，success
- Artifact：`15257522846`，56,533 bytes
- SHA-256：`f2cb26d7a9507e7544be185edb81d9ce435ca52fe76638f92e1f812c032d7fd4`
- 代码 Commit：`19e2fcc9b15c9a3a5f67ccd1cb5acb962cdd0395`（Ghidra handoff 脚本）；Workflow Commit：`3199465d724348bad4cade6b20bf7083d3ad0a97`

### 关键新证据

**1. `0x644B0` 实际从两侧 11 人槽位中挑选 MATCH_PLAYER**

遍历 MATCH 对象 `+0x15380/+0x15388`，每个 team record 的球员数组位于 `+0x138)，数量字段在 `+0x72E`。筛选 `MATCH_PLAYER+0x23C6)、`+0x1C64) 当前状态、球员时间/索引、阶段 PI、球队阶段和目标距离。以多个空间/时间/状态量累计代价 `fVar26)，选择最合适的 `MATCH_PLAYER*` 返回。

这把候选阶段处理从“作用于某个抽象候选”变成“对双方 11 人位置槽中某一个具体 MATCH_PLAYER 选取待处理对象”。

**2. `0x61660` 把通过验收的候选写入选中球员内部状态区**

- 调用 `0x644B0` 取得选中 MATCH_PLAYER；
- 检查双方团队的排期/时间窗口；
- 调用 `0x48ACFD0` 生成候选位置；
- 后者经 `0x48ADC70 → 0x4936080` 完成候选排名和时间/状态验收；
- 验收成功时，对 0xD0-byte 候选记录执行后处理，再复制到 `MATCH_PLAYER+0x1BB0)；
- 写 `MATCH_PLAYER+0x1C44 = candidate_index`；
- 写 `MATCH_PLAYER+0x1C64 = 0x72`；
- 更新 MATCH 级环形计数。

这是首次直接看到候选生成/验收后的数据，实际落入具体 MATCH_PLAYER 内部记录，而不只是停留在局部缓冲区。

**目前仍然不能说已经写入球员 Transform。**`+0x1BB0) 是一个 0xD0-byte 的候选/运动状态记录，`+0x1C64=0x72) 是当前确认的后续状态标签。下一步必须找到谁读取这个状态和记录并把它转成真实移动目标/运动量。

### 主技术报告更新

- 新增 Section 16（0x644B0 选择球员 → 0x61660 接纳候选 → MATCH_PLAYER+0x1BB0 记录写入）。
- 报告 Commit：`af1d899aa65a04fddf4d4ee309dce50c97db0255`

### Parameter Source Run #5 完成：过滤器有效，但真实数据源仍未证明

- Workflow：[Parameter Source Run #5](https://github.com/eslaulau/FM27-Exporter/actions/runs/46130421400)，success
- Artifact：`15257309602)，2,069,929 bytes
- SHA-256：`f2efba892e825aaa5f8d894bd1ac5021c61183061bc137cceb5c10d197b1b2b8`
- scanner 处理 19,082 个候选函数、47,355 条字段访问、13,146 个访问函数；
- RSP 栈基址误报过滤 248 条；
- UnwindInfo 确认的 RBP 栈帧误报过滤 1,293 条；
- 非栈帧 RBP 保留 7 条。

虽然识别出 9 个固定偏移写入候选（`0x41668D0)、`0x17D6260)、`0x29D8F80)、`0x4089740)、`0x19FDAE0)、`0x1C83270)、`0x1CD9400)、`0x8224B0)、`0x1519F00)），但逐个反编译后确认它们的对象身份尚未证明；至少 `0x41668D0` 是创建 0x808-byte record 的配置/记录容器路径，`0x8224B0` 是大型结构初始化器，`0x4089740` 操作另一种带 +0xA0 子对象的记录。不能因为它们也有 +0x480 等偏移就认定为 MATCH_PLAYER 参数向量写入者。

TEAM `+0x149E4..+0x14A00` 系数区仍为读多写零。

**因此参数源问题尚未解决。**下一轮以明确的 MATCH_PLAYER 指针传递链为锚点，追踪 `0xF8050` 的玩家对象、`0x185090` 的复制源和 `0x3C720` 同一个 player pointer，不再把同偏移其他类当作写入证据。

- 主报告 Section 13.8 Commit：`2fe80cd6dc89240e434a9e63b8f839564714ca0a`

### 下一轮锁定两件事

1. 对 `MATCH_PLAYER+0x1BB0..+0x1C80` 的候选记录进行定向读写扫描，重点找谁读取 `+0x1C64 == 0x72)，并追它连接到移动目标、速度/加速度或 Transform 的具体路径。
2. 对参数向量只做带对象身份的指针追踪，从 MATCH_PLAYER 初始化/复制路径找到真正填充 `+0x480..+0x4C4) 的来源；TEAM 系数块以整体初始化/复制方式继续追。

在闭合这两条之后，继续进入传球/射门结果和比分事件写入机制。


### 下一轮实现已提交：MATCH_PLAYER movement record 专项扫描

为追踪 `MATCH_PLAYER+0x1BB0) 的 0xD0-byte 候选记录，已提交三项专项文件：
- 字段扫描器：`scripts/engine_analysis/scan_movement_record_fields.py`，Commit `2fe4ab92d3baa6da61002ff953b33c769ebd445f`；
- Ghidra 消费者/写入者追踪脚本：`scripts/ghidra/TraceMovementHandoff.java)，Commit `8bfc500db527da3690357273383f4d5990a71be9`；
- 专项工作流：`FM27 per-player movement record consumer trace)，Commit `68b8e080a2bbfc8aa11f2b56c21dec352c06c521`。

目标字段包括：
`+0x1BB0) 记录起始、`+0x1C34/+0x1C3C) 距离/辅助值、`+0x1C44) 候选时间索引、`+0x1C60) 方向索引、`+0x1C64) 状态码，以及记录尾部状态成员。

Run #1 曾尝试按显式函数反编译，但没有读取 movement record 的 field-xref 清单；新增 Run #2 已把字段 scanner 输出作为输入，自动挑选读写这些候选记录成员的函数并进行 Ghidra 反编译。

- 专项 Run #2：[Actions](https://github.com/eslaulau/FM27-Exporter/actions/runs/46131546936)，当前 in progress；
- 同一工作流之前的 Run #1：[Actions](https://github.com/eslaulau/FM27-Exporter/actions/runs/46130992721)，success，但仅包含显式 handoff seeds；
- Run #2 成功后优先检查谁读取 `+0x1C64 == 0x72)，以及是否把 `+0x1BB0) 内的坐标/方向数据转换为运动目标、速度/加速度或 Transform。

**边界：**当前只证明候选状态记录被写入 MATCH_PLAYER；最终运动提交尚未确认。不得把它说成 Transform 已更新。


### 本轮代码核验更正：Handoff 后处理 CALL 目标地址漏写前缀 4

重新逐条核对 Run #3 的原生 CALL xref 后，发现早先 Ghidra seeds 把 `0x61660` 的两个调用目标少写了前缀 `4`：
- site RVA `0x61971` 实际 call target = `0x47F2120`，不是 `0x7F2120`；
- site RVA `0x61999` 实际 call target = `0x4707AA0`，不是 `0x707AA0`。

Run #3 曾反编译的 `0x7F20E0`、`0x707A30` 与 handoff 无关，相关解释全部撤回。已修正 Ghidra 脚本：
- Commit：`a9f7ed19c873c4fd2ece745be776ab19c4a29dbc`
- 技术报告更正 Commit：`374179a3a0ed2e8356cb2cb0f06ee899a6e2f5fd)

### Movement Record consumer Run #2：脚本编译错误已修复，Run #3 重新运行

- Run #2：[Actions](https://github.com/eslaulau/FM27-Exporter/actions/runs/46131546936)，失败原因：`ranges` 声明为 `Map)，但脚本调用 `floorEntry()`；这是 Java 编译错误。
- 修正：将类型改为 `NavigableMap<Long,long[]>`，Commit 同上 `65422b3b14e41fb1ebf6aa4b2be4f19645074c8e`（注意本地址修复后另有 Handoff 目标更正；Run #3 的 head commit 是 `65422b3b14e41fb1ebf6aa4b2be4f19645074c8e`）。
- 当前 Movement Record consumer Run #3：[Actions](https://github.com/eslaulau/FM27-Exporter/actions/runs/46131767534)，字段扫描已成功，Ghidra 消费者反编译进行中。
- Handoff Run #3：[Actions](https://github.com/eslaulau/FM27-Exporter/actions/runs/46131767568)，success，Artifact `15257951656)，但其后处理目标曾用错 RVA；因此本轮仅使用其确认的 `0x61660 → 0x644B0 / 0x48ACFD0) CALL xrefs，不采用误标的两个后处理函数。

### 下一步

1. 检查 Handoff Run #4（修正 0x47F2120/0x4707AA0）新 Artifact，确认真实 helper 逻辑。
2. 检查 Movement Record consumer Run #3，对 `+0x1BB0) 记录读取函数进行 Ghidra 反编译，找到 state `0x72) 的消费者和最终 movement/transform update。
3. 将确认的字段消费链补进主报告；若只看到记录复制/队列管理，不把它当作运动执行。


## 2026-11-28：Movement Record Run #3 完成，候选记录消费者已生成四分量下游输出

### Run #3 与 Artifact

- Workflow：[Per-player movement record consumer Run #3](https://github.com/eslaulau/FM27-Exporter/actions/runs/46132062768)，success
- Artifact：`15258218044`，601,709 bytes
- SHA-256：`76eb398464d8c1910696481a49d195bacb6db8a1c15db69fb8f555b5cf75d168`
- Ghidra 脚本使用已经确认的 MATCH_PLAYER movement-record 字段清单，自动筛选多字段消费者并反编译。
- 主技术报告 Section 17 Commit：`e4671c31c4a6e8c8c9b4607888cc6334a00afc50`

### 新确认的两个关键消费者

**1. `0x4915090)：读取并解包 MATCH_PLAYER movement record**
- 读取 player `+0x1BB0/+0x1BB8) 候选 XY，`+0x1C3C) 辅助距离，`+0x1C40/+0x1C44) 时间/候选索引，`+0x1C64) 状态；
- 同时检查当前 tick、阶段 PI、OOP slot、球场边界、与关联球员候选时间/空间冲突和历史样本；
- 接受时将记录解包到调用者的 param_7：候选 XY、距离、候选 index、映射后的状态标签和侧向标记；
- 函数本身没有写 player 当前 XY +0x140/+0x144。

**2. `0x4911C10)：验收结果位 + 四分量输出记录**
- 在入口调用 `0x4915090)，把其结果更新到调用者 flag 结构 `param_5+0x10) 的 bit 0x200；
- 对已接受候选执行更多阶段、时间、空间、球场边界、历史轨迹和其它球员冲突检查；
- 满足条件时写入输出结构 `param_8)：多分支生成四个 float 分量 `param_8[4..7])，写入阈值 `+0x24)、状态标签 byte `+0x2D) 和距离/向量/时间辅助字段 `+0x1C/+0x1D/+0x21)；
- 输出的四分量是候选/动作输出记录，不是已证明的 Transform 写回。

**调用关系边界：**
- 机器 xref 已确认 `0x4911C10 → 0x4915090)，call site RVA `0x4911C8D)；
- `0x4911C10) 暂未发现直接 CALL caller；可能通过间接指针/vtable/回调，但需要 Run #5 静态指针结果验证；
- `0x489DEA0)（36,736 bytes）是 `0x4865900) 调用的另一条大型 per-player 更新函数，不是 `0x4911C10) 的直接 caller；
- `0x489DEA0) 处理候选缓冲区/时间/空间状态，但没有凭偏移足够证据将它判为最终 Transform 写入器。

### Run #5 正在追实际调用者/输出消费者

- Workflow：[Movement Commit Run #5](https://github.com/eslaulau/FM27-Exporter/actions/runs/46132797258)
- 新目标包括 `0x4915090)、`0x4911C10)、`0x489DEA0)、`0x61660)、`0x47F2120)、`0x4707AA0)；
- 扫描直接 CALL/JMP/Jcc 和非执行区静态绝对 VA / RVA 函数指针；
- 当前字段扫描/调用扫描步骤仍在执行，尚无有效 Artifact。
- 目标：找出谁调用 `0x4911C10)、谁接收 `param_8[4..7])、是否把它传到 Movement Director/physics 或最终 Transform 更新。

### 本轮严格结论

现在已形成更完整的中间链：
`0x61660) 将候选记录写入 MATCH_PLAYER → `0x4915090) 读取/解包和验收 → `0x4911C10) 生成四 float 候选/动作输出和结果标志。

**最终球员 Transform 或实际速度/运动状态写回仍未定位**，因此目前还不能说已证明真实移动执行。下一步继续找四分量输出的消费者，之后再把角色、职责、PI/TI 与移动执行联系起来。


## 2026-11-28：Movement Action Chain 补齐（Unified Run #56 + 专项 Commit #8 / Handoff #6 / Record #5）

本节以已下载的四份 Actions Artifact 逐项核对，不把不同工作流各自的 Run number 混为一套编号。

### 工作流与产物

- Unified Engine Run #56：[Actions](https://github.com/eslaulau/FM27-Exporter/actions/runs/46115767659)，Run ID `46115767659`，success；16 个主要步骤均完成。
  - Artifact `15251543526`，29,859,099 bytes，SHA-256 `4ccf48200a85b8834cabc8e61b910476d39f7005d35fb76bd25f4793bc7f2eae`。
  - Commit：`050e90d1ad96850c5daad77f4b4ff68d7f99c6ad`。
- Movement Commit Run #8：[Actions](https://github.com/eslaulau/FM27-Exporter/actions/runs/46133501677)，Run ID `46133501677`，success。
  - Artifact `15258718019`，995,508 bytes，SHA-256 `8671b85490b6a539695ea1243f436ea0f6264c67b8dd7c1962c39de46325df79`。
  - Commit：`aa0b984c9262cdf04aa6261037208b102e4d1b3f`。
- Movement Handoff Run #6：[Actions](https://github.com/eslaulau/FM27-Exporter/actions/runs/46133487111)，Job success，但 Ghidra 控制台尾部有 `ConcurrentModificationException`，且本轮没有传入 movement-record field TSV；只采纳生成成功的显式 seed 反编译和可核实 xref，不将其描述为完整 consumer pass。
  - Artifact `15257969048`，160,227 bytes，SHA-256 `6186a067a59de43d4579b13ea3c0ceae9ad6eb18c39770832c5f6f7700e4bb71`。
  - Commit：`d434cd7ea11f1c4131296c1c23e9f0c96a115fff`。
- Movement Record Run #5：[Actions](https://github.com/eslaulau/FM27-Exporter/actions/runs/46133487021)，success。
  - Artifact `15258786644`，653,830 bytes，SHA-256 `ef3faead65523306d49d860f66f649a6ac7975432cf46dd56a2696a75fb98225`。
  - Commit：`d434cd7ea11f1c4131296c1c23e9f0c96a115fff`。

详细分析报告：[MovementActionChain Run #56 / Commit #8 / Handoff #6 / Record #5](https://github.com/eslaulau/FM27-Exporter/blob/main/docs/reverse-engineering/FM27_27.1.1_MovementActionChain_Run56_20261128.md)，Commit：`3d7b0b8ffe101a3a072bc937f5b6a6886dcb458d`。

### 新确认：Match tick 调用候选 handoff

Movement Commit Run #8 的机器 CALL xref：
- `0x3FEF0 → 0x5DBD0`，site `0x40001`；
- `0x5DBD0 → 0x61660`，sites `0x5E050`、`0x5FC1C`。

这确认 `0x61660` 的候选状态 handoff 由 match-candidate tick dispatcher `0x5DBD0` 在 tick 流程中调用。它和此前确认的 `0x61660 → MATCH_PLAYER+0x1BB0` 写入链相连。

### 新确认：movement record → action output dispatcher

机器 CALL xref 确认：
- `0x4862CB0 → 0x4863C40`（两处）；
- `0x4862CB0 → 0x4915090`；
- `0x4863C40 → 0x4911C10`；
- `0x4863C40 → 0x4915090`（两处）；
- `0x4911C10 → 0x4915090`；
- `0x4915090 → 0x4863C40`（一处直接 CALL；尚不把它解释为普通递归，需继续解码具体分支）。

Handoff Run #6 中 `0x4863C40` 的反编译显示：它根据输入 flag 在 `0x4911C10` 动作候选构建和 `0x4915090` movement-record 判定之间分派；部分分支再次执行记录验收，并输出坐标/向量、阈值和状态标签等缓冲区字段。它读取当前球员位置相关字段 `MATCH_PLAYER+0x140/+0x144` 用于空间比较，但该函数内未见写入这两个字段。

`0x4911C10` 构造四 float 分量的候选/动作输出与元数据；`0x4915090` 读取 `MATCH_PLAYER+0x1BB0` 记录，结合 tick、阶段、PI/OOP、边界、历史样本及关联球员冲突进行验收并向调用者输出候选信息。

**严格结论：**已从“候选记录被写入 MATCH_PLAYER”推进到“match tick 驱动 handoff，并有候选记录 reader / action builder / dispatcher 形成下游输出缓冲区”的中间链。仍未证明当前坐标、速度/加速度或 Unity/native Transform 的最终写回。

### 新确认：Movement Director 的空间映射层

Run #56 对 `MATCH_MOVEMENT_DIRECTOR` vtable 15 槽进行分析。slot 7（`0x4993230`）是 FNV-1a 风格 32-bit key 的 hash/map 查找；命中项的类型 byte 位于 `entry+0x14`，类型不是 10 时调用 `0x492D060`，未命中/类型 10 则复制 fallback coordinate record。

`0x492D060` 按类型 0–9 选择 Director 内部几何/锚点数据，使用 side 分组记录生成坐标，计算并归一化空间方向后做投影；在较新版本分支中，还扫描对方 11 个位置槽寻找最近对手，并使用对手朝向 `+0xA0/+0xA4` 调整目标点，最终调用 `0x492D840` 后处理。

这确认存在“键映射 → 类型选择 → 几何投影/对手近邻修正”的空间变换层。类型 0–9 尚无 UI/战术语义映射，不得直接把它们命名为角色或跑位指令。

### Movement Record Run #5 扫描覆盖

- PE runtime functions：144,876；
- 候选函数 572，扫描 566；
- 原始命中 2,445；代码扫描量 5,870,779 bytes；
- movement-record 字段引用 2,091，唯一消费者函数 295；
- 选出 32 个动态 Ghidra seeds（候选集合 244 个）。

新增候选消费者覆盖 `0x489DEA0`、`0x48ECA60`、`0x481A6A0`、`0x48A8440`、`0x4878680`、`0x4829050`、`0x496F840`、`0x4856010`、`0x4917C20` 等。此扫描扩大了记录消费者样本，但不构成最终 Transform 写入证据。

### 主线现状与下一轮（修正）

当前已确认中间链：

```text
0x3FEF0 → 0x5DBD0 (match-candidate tick)
                 ↓
              0x61660
                 ↓
MATCH_PLAYER+0x1BB0 / +0x1C64 state
                 ↓
0x4915090 (record decision/reader)
                 ↓
0x4911C10 (4-float action candidate builder)
                 ↓
0x4863C40 (movement decision/action output dispatcher)
                 ↓
action/output buffer
```

独立的 Movement Director 空间链：
``0x4993230`` hash lookup → type 0–9 → `0x492D060` spatial projection → `0x492D840` post-transform。两条链是否在实际运动写回点汇合，尚未证明。

下一轮不再重复全量扫描，锁定：
1. 在字段扫描器加入 `MATCH_PLAYER+0x140/+0x144` 当前 XY 候选偏移；筛选同一函数中同时访问 movement-record 字段与当前 XY 写入字段的函数，并另行检查两坐标均为写访问的候选。
2. 修复 `TraceMovementHandoff.java` 的 caller 集合迭代并发修改问题：在遍历 callers 前复制稳定快照；恢复完整动态 consumer pass。
3. 对坐标写入候选反查 caller，确认是否来自 `0x4863C40`、`0x4911C10`、`0x4915090` 或 match tick/update 路径；仅有 +0x140/+0x144 偏移不能证明对象身份。
4. 并行保留战术参数数据源问题：继续追 `MATCH_PLAYER+0x480..+0x4C4` 参数向量及 TEAM `+0x149E4..+0x14A00` 系数区的真实初始化/复制路径。
5. 移动执行链闭合后，转向传球、射门质量和比分事件写入机制，再用真实赛季数据反向设计四后卫战术。



### 当前续接任务：实际坐标写入点专项扫描（已提交，Actions 运行中）

为解决本日志前文反复标记的“最终 Transform/速度写回未定位”，本轮已把下一步转成字段级定位，而不是再重复全量引擎扫描：

- 修改 `scripts/engine_analysis/scan_movement_record_fields.py`，加入 `0x140`、`0x144` 两个当前坐标候选偏移；字段名明确标为 candidate，避免仅凭偏移就假定对象身份。
  - Commit：`7c775dfad3425d56ec254a3ba427ffd9c9ed6d79`。
- 修改 `scripts/ghidra/TraceMovementHandoff.java`：把函数按“记录字段 + 当前 XY 写入”“同一基址寄存器共现”“X/Y 两字段同时写入”评分；优先反编译候选坐标 writer；新增 match tick 上游 caller seed `0x3FEF0`。
  - 同时修复 caller 集合遍历中的并发修改：遍历前复制 `callers` 快照，防止 `collect()` 在遍历中继续向原集合加入 caller。
  - Commit：`19a4e4a0355e010f767722d8b54f78880ba930d2`。
- Movement Record consumer Run：[Actions](https://github.com/eslaulau/FM27-Exporter/actions/runs/46136282836)，Run ID `46136282836`，当前 `in_progress`，正在执行新增字段扫描。
- Movement Handoff Run：[Actions](https://github.com/eslaulau/FM27-Exporter/actions/runs/46136282842)，Run ID `46136282842`，当前 `in_progress`，正在执行修复后的 Ghidra handoff 反编译。

本轮筛选只是定位候选，不会将全模块任意 `+0x140/+0x144` 访问自动归因给 MATCH_PLAYER。最终结论必须结合相同对象基址、函数调用关系和输出缓冲区来源判断。待 Artifact 生成后，优先检视写访问（W）候选以及它们是否由 `0x4863C40 / 0x4911C10 / 0x4915090` 或 tick/update 链调用。


### 动作输出缓冲区的 XY 计算细节（反编译复核）

对 `0x4911C10` 特定状态分支再次逐指令核对：函数先调用 `0x4986090` 家族 helper 取得内部表索引，从表项 `+0xA0` 读取 64-bit 二维偏移，再分别与 `MATCH_PLAYER+0x140/+0x144` 当前 XY 相加，写入调用者 `param_8[4]/[5]`；同一分支将 `MATCH_PLAYER+0x148/+0x14C` 写入 `param_8[6]/[7]` 并继续经过状态/速度门控。

这使 `param_8[4]/[5]` 可以在该分支下被确认是“当前球员 XY + 内部偏移表二维向量”的候选目标坐标，而不是实际当前 XY 写回。内部索引/表的 UI 语义和输出记录最终消费者仍未破解。技术报告已补充该细节。


### Handoff 修复后 Run #7 已完成：tick 上游 caller 得到反编译

- Workflow：[Movement Handoff Run #7](https://github.com/eslaulau/FM27-Exporter/actions/runs/46136282842)，Run ID `46136282842`，success。
- Artifact：`15260420090`，200,845 bytes，SHA-256 `e2c907f0e21a81ca51091ab48f2bc9eb4dc384b251fbd68f96838cf5067a9766`。
- 本轮新增 seed `0x3FEF0`，函数体 1,824 bytes；`TraceMovementHandoff.java` caller 稳定快照修复生效，Ghidra 控制台无 `ConcurrentModificationException`。
- 反编译 `0x3FEF0` 显示它先执行常规 match update 与状态/时间检查，在处理相关 player/record 上下文后，依次调用 `0x83A490`、`0x5DBD0`、`0x51820`。机器 xref 直接确认 `0x3FEF0 → 0x5DBD0`（site `0x40001`）。
- `0x5DBD0` 内两处调用 `0x61660`（sites `0x5E050`、`0x5FC1C`），本轮再次核实。
- 本工作流仍未传入 dynamic movement-record TSV（摘要为 `MOVEMENT_FIELD_TSV_MISSING`），所以只用于校验 handoff / tick 调用者，坐标 writer 搜索由 Record Run #6 承担。

**下一项坐标 writer 扫描状态：**Movement Record Run #6 [Actions](https://github.com/eslaulau/FM27-Exporter/actions/runs/46136282836) 已完成新增字段扫描步骤，当前 Ghidra 在反编译候选 reader/writer，Artifact 尚未生成。


### Position writer 候选突破：Movement Record Run #6（尚待调用入口验证）

- Workflow：[Movement Record Run #6](https://github.com/eslaulau/FM27-Exporter/actions/runs/46136282836)，success。
- Artifact：`15259702827`，1,045,237 bytes；SHA-256 `71a5a1f48e28b0ee430a7ac500fc1ad6508bcc7e7cf437d0c0217d8da30cf0d4`。
- 新增 scanner 同时分析 `MATCH_PLAYER+0x140/+0x144` 和 `+0x1BB0..+0x1C7C` movement record 字段。
- 候选统计：632 个 ranked functions；292 个 movement-record field functions；343 个 position-write functions；40 个动态函数进入 Ghidra 优先反编译。
- 只有一个函数满足“movement record + position write + 同一基址寄存器”最高强度条件：`0x2AFB290`，函数体 2,279 bytes。

**0x2AFB290 新证据：**
- 机器指令显示同一基址寄存器上写入 `+0x140`、`+0x1BB0`、`+0x1BC0)、状态 `+0x1C64` 及 `+0x1C6C/+0x1C70`；同时读取 `+0x1C44) 和 `+0x140`。
- 伪代码明确遍历 team/player pointer 数组（`param_1+0x138`，计数 `+0x72E`），并逐个处理 player 对象。
- 根据 player 时间字段（`puVar6[0x82]`，偏移 `+0x208`）与 match tick（`+0x154EC`）比较，在时间条件满足时把缓存数据 `+0x150/+0x158` 复制到活动字段 `+0x140/+0x148`。
- 同函数还使用二维差值查 `0x1858B6748` 方向表，更新每球员方向缓存；并写入 movement record 与状态标签。

该函数因此是目前最高置信度的“每球员位置状态 + movement record 更新”候选。但它的 Ghidra 直接 CALL caller 计数为 0，且尚未证明它就是 `0x61660` 候选 handoff 的下游 consumer；必须继续检查间接入口、vtable/静态函数指针与 match update caller。

详细报告：[PositionWriterCandidate 0x2AFB290](https://github.com/eslaulau/FM27-Exporter/blob/main/docs/reverse-engineering/FM27_27.1.1_PositionWriterCandidate_0x2AFB290_20261128.md)，Commit `a94f884de99b05278b133cbb92e185942e25ae5f`。

### 下一轮调用图与 post-handoff 消费者扫描

- Movement Commit Run #10：[Actions](https://github.com/eslaulau/FM27-Exporter/actions/runs/46136817103)，修复 shell continuation 后执行 `0x2AFB290`、`0x51820`、`0x83A490` 的 CALL/JMP/static pointer 扫描，目前 Ghidra 正在反编译 caller。
- Handoff Run #8：[Actions](https://github.com/eslaulau/FM27-Exporter/actions/runs/46136666185)，success；Artifact `15259403569`，212,259 bytes。
  - `0x3FEF0` 再次确认调用顺序 `0x83A490 → 0x5DBD0 → 0x51820)。
  - `0x51820) 有 25 个 direct callees，并且是 `0x3FEF0) 的直接 callee。
  - 它读取 `MATCH_PLAYER+0x1BB0/+0x1BB4` 等 movement record 字段，依据双方 tick/阶段/slot 状态与位置边界进行判断；随后组织玩家/记录上下文并调用 `0x84D000`、`0x5AFE0`、`0x47E44C0`、`0x2B08DF0` 等后续处理函数。
  - `0x83A490) 是时间/任务队列预处理路径：钳制更新参数并处理队列记录；暂不能命名为 movement 算法。
- Handoff Run #9：[Actions](https://github.com/eslaulau/FM27-Exporter/actions/runs/46136889150)，正在反编译上述 `0x51820) 后续消费者。
- Movement Record Run #7：[Actions](https://github.com/eslaulau/FM27-Exporter/actions/runs/46136889158)，重新运行动态 writer/consumer seeds；Run #6 曾在新增 post-handoff seeds 时被新提交取消，不产生部分结论。

**脚本/工作流修复记录：**
- 加入 `+0x140/+0x144` 和同基址优先级评分：`7c775dfad3425d56ec254a3ba427ffd9c9ed6d79`、`19a4e4a0355e010f767722d8b54f78880ba930d2`。
- 修复 Handoff caller 集合并发修改：`19a4e4a0355e010f767722d8b54f78880ba930d2`。
- 扩展 match tick pre/post handoff seeds：`4cbd98090049d12f0d5b6ba1e7bd513eef0d7e3f`。
- 扩展 post-handoff record consumers：`8ebca595907802c1430ef5710eed617caeaa639f`。
- Movement Commit workflow 增加 position-writer target，shell continuation 修正：`2c233c436e8c0ff13515cb046966478857cfaad5`、`8cbf5ba49b5fc3b74d567d9b38f1883752706bb3`、`9ce61d276bbc9976da6bb3ebeaaad5228e1b464a`。前两次工作流分别因并发取消/错误续行未产生有效扫描结果；当前以 Run #10 结果为准。



### Run #10 caller 扫描：Position writer 候选存在两个真实直接调用者

- Workflow：[Movement Commit Run #10](https://github.com/eslaulau/FM27-Exporter/actions/runs/46136817103)，success；Artifact `15260112078`，996,063 bytes。
- Scanner 统计：27 个目标；144,876 runtime functions；6,158 个候选函数解码；确认 19,789 个 CALL/JMP/Jcc；28 个静态函数指针命中。
- 新确认 `0x42D3910` 在 CALL site `0x42D4C4C` 调用 `0x2AFB290`。
- 新确认 `0x42D58E0` 在 CALL site `0x42D5BEB` 调用 `0x2AFB290`。
- `.xcode` 区域还有 module-relative 32-bit 静态引用指向 `0x2AFB290`。
- 这纠正了单独 Ghidra 引用表的 `CALLERS=0`：全模块 Capstone 直接扫描找到了两个真实调用点。现阶段仍待反编译这两个 caller 以及它们的上游 caller，才能确认是否接入 match tick 主链。
- 同轮还确认 `0x3FEF0 → 0x51820`（site `0x4002E`），`0x3FEF0 → 0x83A490`（site `0x3FFE6`）；`0x83A490` 另有 `0x7DACE0` 与 `0x83BBC0` 两组直接调用者。

修复 Ghidra caller 优先级筛选器，将 `MATCH_PLAYER_MOVEMENT_RECORD_AND_POSITION_WRITER`、`MATCH_UPDATE_POST_HANDOFF_STAGE` 和 `MATCH_UPDATE_PRE_HANDOFF_STAGE` 加入最高优先级，Commit `d07e7bbec8dc9f02b063762b024c2f8049881684`。Movement Commit Run #11：[Actions](https://github.com/eslaulau/FM27-Exporter/actions/runs/46137041278)，专门反编译以上 caller。

Position writer 专项报告已同步更新，Commit 见报告末尾。


### Run #9 行为计算器细化：0x47E44C0 的方向/对手轨迹计算已解码

Movement Handoff Run #9（Workflow `46136889150`，Artifact `15260231729`）对 `0x47E44C0` 的完整反编译进一步确认：

- `0x51820`（match tick post-handoff stage）直接在 CALL site `0x51F6F` 调用 `0x47E44C0`。
- 函数入口读取 player `+0x1C64/+0x1C6C` 状态以及 match tick `+0x154EC)，以角色/阶段和多个时间窗口决定是否计算。
- 通过 `0x47F1E70` 取得指定时间样本的二维位置，与 player 当前 `+0x140/+0x144` 比较；按二维差值查询 `0x1858B6748` 方向表。
- 将当前与候选方向索引做 360 单位环绕差，只有最小差值小于 `0x5B`（91 个方向单位）时，才进入方向偏移计算。
- 从 `0x185890D98` 方向/距离表取二维偏移，叠加到候选位置；随后遍历对方球队位置槽（容器 `+0x388`、数量 `+0x730`），结合 opponent `+0x1C64/+0x1C6C` 状态、时间，以及 `0x47F1E70` / `0x48A6E20` 的预测数据进行时空冲突检查。

这说明 `0x47E44C0` 是 **match tick 中的 per-player 方向/轨迹空间行为计算器**，包含候选位置计算、方向容差和对手预测位置筛选。UI role/PI/duty 语义及最终输出接收点仍待确认。详见 MovementActionChain 报告 Section 7–8。

### Run #7 对 0x2AFB290 的边界修订

Movement Record Run #7（Workflow `46136889158`，Artifact `15260027793`）再次反编译 `0x2AFB290`：
- `+0x23C6 == 1` 状态分支主要刷新方向缓存和 movement record；
- 另一个 `+0x1233 > 0x84` 分支在 player `+0x208` 时间早于当前 match tick 时，把缓存 `+0x150..+0x15F` 应用到活动位置区 `+0x140..+0x14F`；
- 同函数写入 `+0x1BB0/+0x1BC0` 与 `+0x1C64/+0x1C6C/+0x1C70)。

因此将 `0x2AFB290` 定义为“按状态/时间门控的运动记录更新与缓存位置应用器”，而不是直接宣称是 `0x61660` 的最终候选提交器。它有两个真实 CALL callers（`0x42D3910`、`0x42D58E0`），其上游是否接入 handoff 主线仍待反编译。

### Run #11 caller 反编译优先级修正

Run #11（Workflow `46137041278`，Artifact `15260182294`）扫描成功，确认目标 caller xrefs 仍为：
- `0x42D3910 → 0x2AFB290`（site `0x42D4C4C`）；
- `0x42D58E0 → 0x2AFB290`（site `0x42D5BEB`）。

但 Ghidra xref-decompile 的 160 函数上限被大量泛化 `CANDIDATE_POSITION_RECORD_COPY_OR_TRANSFORM` 调用点占满，两个关键 caller 未进入伪代码输出。已把 `MATCH_PLAYER_MOVEMENT_RECORD_AND_POSITION_WRITER` 精确标签升级为优先级 -10（高于普通候选/复制引用），Commit `9e07bcc71b7e8ce6fa50a1d30734bbe2a740fc54`。Movement Commit Run #12：[Actions](https://github.com/eslaulau/FM27-Exporter/actions/runs/46137296905)，将重新专门反编译这两个 caller。


### Run #12：0x2AFB290 已连接到 match-level tick/update routine

- Workflow：[Movement Commit Run #12](https://github.com/eslaulau/FM27-Exporter/actions/runs/46137296905)，success。
- Artifact：`15260501406`，1,022,188 bytes；SHA-256 `c03ae634ba1ac7a2dbf7dafe97f2851c07aa6cfda5dac0acc37f205534d4c44f`。
- 精确升级 position writer caller 的 Ghidra 优先级后，成功反编译 `0x42D3910` 和 `0x42D58E0`。

**新确认的调用关系：**
- `0x42D3910` 在 site `0x42D4C4C` 直接调用 `0x2AFB290`。
- `0x42D3910` 在 site `0x42D45FF` 调用 `0x42D58E0`。
- `0x42D58E0` 在 site `0x42D5BEB` 再调用 `0x2AFB290`。

**0x42D3910 的功能证据：**
- 读取 match 当前 tick `+0x154EC)、双方 team 对象 `+0x15380/+0x15388) 和 player arrays（team `+0x138`、count `+0x72E`）。
- 遍历球员槽、读取 player 状态（包括 `+0x23C6`）并调用 per-player/team update helpers。
- 操作 match update/event queue（`+0x12EE0..+0x12F30`、`+0x13E40)），按时间窗口、双方活动/待更新计数分支，写入事件 type `0x11/0x12) 等。
- 在更新分支直接调用 `0x2AFB290`，也会调用 `0x42D58E0` 子阶段。

**0x42D58E0 的功能证据：**
- 读取 match tick 与当前 team/player 上下文，处理事件 type `0x13) 及下一更新窗口；
- 在对应更新分支再次调用 `0x2AFB290)；
- 后续对 `+0x23C6 == 1` 的 player 调用历史/时间样本 helper `0x19E0)。

这使 `0x2AFB290` 从字段写入候选升级为**已确认被 match-level update routine 及其子阶段调用的每球员运动记录/缓存位置更新器**。它按 player state 与时间条件维护方向缓存、movement record，并在特定分支将缓存位置 `+0x150..+0x15F` 应用到活动位置区 `+0x140..+0x14F)。

详细报告：[MatchTickPositionUpdater Run #12](https://github.com/eslaulau/FM27-Exporter/blob/main/docs/reverse-engineering/FM27_27.1.1_MatchTickPositionUpdater_Run12_20261128.md)，Commit `dc3aae23d192d250ebc6635067e046c4438fd00a`。

**关键未闭合点仍保留：**`0x61660` 将候选记录写入 `+0x1BB0)，`0x51820` 读取该记录并调用 `0x47E44C0)；`0x42D3910 → 0x2AFB290` 是 match-level updater 的另一条已证实调用链。尚无直接证据说明 `0x61660` 写入的记录由 `0x2AFB290` 哪个分支读取并提交。两段链可能在共享 player state/时间队列中汇合，但不能提前画成直接边。

### Run #13 / #14：追踪 match-level updater 的上游调度入口

为定位 `0x42D3910` 的 caller，已在 `fm27-movement-commit-analysis.yml` 添加目标 `0x42D3910`、`0x42D58E0)、`0x3FEF0`，并将其 caller 伪代码优先级提升到 generic record-copy references 之前。

- Run #13：[Actions](https://github.com/eslaulau/FM27-Exporter/actions/runs/46137512772)，由 workflow target 更新触发；
- Run #14：[Actions](https://github.com/eslaulau/FM27-Exporter/actions/runs/46137515853)，由优先级修复触发；后续以包含两项更新的最新运行产物为准。

下一轮只追 `0x42D3910` 的直接 caller / 函数指针 / vtable scheduler，并确认是否进入 `0x3FEF0`、`0x5DBD0` 或其他 match tick 调度路径。
