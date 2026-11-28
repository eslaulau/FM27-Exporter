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
