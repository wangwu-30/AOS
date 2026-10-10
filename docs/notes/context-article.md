
AlexZ 🦀
@blackanger
像 Rust Arena Allocator 一样管理上下文
昨天的短推里有位犀利哥（评论很犀利），他给了我很大启发。
es05
@es05988399
·
22h
Replying to 
@blackanger
Stop "writing prompts", start managing like a Rust Arena Allocator. The Context Window is a contiguous memory block.
Append-only AMAP
Dynamic loading skills
Spatial locality of relevant content
Reasoning in Goldilocks Zone
BTW: Pruning and RAG are tricks, not principles.
Stop "writing prompts", start managing like a Rust Arena Allocator.The Context Window is a contiguous memory block. Append-only AMAP. Dynamic loading skills. Spatial locality of relevant content. Reasoning in Goldilocks Zone.BTW: Pruning and RAG are tricks, not principles.
他提到 Rust Arena Allocator 。我后面又仔细思考了，还真是这么回事。所以结合我昨天发的《Agent 设计的核心约束和原则》，再展开说说。
AlexZ 🦀
@blackanger
·
19h
Agent 设计的核心约束与原则
昨天，我发了一篇短推，
 
这条推引发了不少讨论。其实我从年前就开始做 claw-rs“小螃蟹”，后面重构迭代，从 agent 先做起。这个过程让我对 agent...
一、Prompt Engineering 的隐喻危机
"Prompt Engineering" 这个词“害”了整个行业。
它让人觉得，和 LLM 打交道的核心能力是"写出好的文字"。措辞精准、格式漂亮、Few-shot 示例到位。于是所有人都在研究怎么写更好的 system prompt，怎么措辞让模型"听话"，怎么在一段文字里塞入更多指令。
这就像一个操作系统工程师说："我的核心工作是写出漂亮的注释。"
不。
你的核心工作是 内存管理。
当你运行一个 LLM Agent，一个需要执行几十轮工具调用、消耗 100K+ token 上下文、持续工作数小时的系统，"写提示词"只是最表层的事。真正决定系统生死的，是你如何管理那块有限的、昂贵的、有物理约束的内存空间。
而 Rust 社区的 Arena Allocator，恰好是这个问题最精确的心智模型。
二、Arena Allocator：30 秒速览
Rust 的 Arena Allocator（也叫 bump allocator）是内存管理的极简范式：
预留一大块连续内存
  ↓
每次分配：指针往前推（bump），永不回退
  ↓
所有分配都在这块内存中连续排列
  ↓
需要释放时：整块一起丢（reset），不单独回收
它的核心特性：
Append-only：新分配的内存总在前一次的后面，指针只会向前。
连续内存块：所有数据在一块物理连续的区域内，没有碎片。
空间局部性（Spatial Locality）：时间上相近的分配，在内存中物理相邻，对 CPU cache 极其友好。
按需分配（Lazy/Dynamic）：不预分配所有可能用到的结构，用到时再 bump。
批量释放而非逐个回收：你不能 free 单个对象。要么全留着，要么整块 reset。
这些不是实现细节，是设计原则。每一条都精确映射到 LLM 上下文管理的核心约束。
三、Context Window 就是一块 Arena
把 LLM 的上下文窗口想象成一块预先分配好的连续内存：
这块"内存"有三条铁律：
铁律一：它有固定上限。128K token 就是 128K，不可能变成 256K。和物理内存一样，它是你最稀缺的资源。
铁律二：前缀改变的代价是灾难性的。KV Cache 的匹配规则是从第一个 token 逐一比对。第一个不同的 token 之后，后面全部 cache miss。这不只是"多花钱"，DualPath 论文证明了在推理系统中，KV Cache 命中率 ≥ 95%，瓶颈在于把缓存搬回来的 I/O 带宽。一旦 prefix 变化，整条带宽被打满。
铁律三：注意力不均匀。LLM 对开头和末尾的 token 注意力最强，中间会衰减（Lost in the Middle）。你的上下文不只是"一块内存"，它更像一块两端热、中间冷的 cache line。
这三条铁律，逼出了和 Arena Allocator 完全一致的设计原则。
四、五条 Arena 原则在上下文工程中的映射
以下原则也是在之前 Agent 设计的核心约束和原则文章里提到过的。
原则 1：Append-Only AMAP
Arena Allocator 最核心的约束：指针只往前推，永不回退。
对上下文来说，这意味着：
✓ 在末尾追加 user / assistant / tool_result 消息
✓ 打 tag、读 status（只读元数据，不修改消息）

✗ 在中间插入新消息
✗ 重排消息顺序
✗ 修改 system prompt（任何原因）
✗ 删除消息后让后续消息"前移"
AMAP (As Much As Possible)。不是绝对不能回退（pruning 有时必须发生），而是把 append-only 作为默认模式，任何违反都需要付出代价并显式标记。
我曾尝试设计 "滑动窗口 + 动态组装上下文"的架构（记作 V1 版），每轮根据需要从记忆库中抽取片段插入上下文中间。这条路走进了死胡同。
根本矛盾：
滑动窗口要求：每轮上下文内容不同（按需组装）
KV Cache 要求：连续调用的前缀相同（追加增长）

这两个要求在数学上不可调和。
v1 的每一次"优化"，都在把方案往 append-only 方向拉。当我们把动态部分缩到足够小来保住 cache，方案就退化成了带有额外复杂度的 append-only。演化路径是这样的：
"不做压缩" → "动态组装" → "破坏 cache" → "优化 cache"
→ "把动态部分推到末尾" → "把静态部分做成追加式"
→ "等等，这不就是 append-only 吗" → "是的"
这和 Rust 社区的经验一模一样。每次有人尝试用更"灵活"的 allocator 替代 arena，最后都会发现 arena 的约束就是它的力量。
你以为你在优化，其实你在重新发明 bump pointer。
我们现在的架构把这条原则刻进了“骨头”：System Prompt 构建一次不变，所有信息回流上下文的方式只有一条，作为 tool_result 追加到末尾。序列化用 BTreeMap 保证 key 顺序。
技能指南不改 system prompt 而是附着在 tool_result 上。连 Extension API 都在编译期强制 append-only。hook 的类型定义里根本没有 set_system() 或 insert_at() 方法。
原则 2：Dynamic Loading Skills（Demand Paging）
Arena Allocator 不预分配所有可能用到的对象。你不会在 arena 初始化时就把未来可能需要的每一种数据结构都实例化。那会把 arena 塞满，给真正需要的数据留不下空间。
对上下文来说，这是按需加载：
全预装（反模式）：
  [System Prompt: 身份 + 核心规则 + 浏览器指南(2k) + Shell指南(1k)
   + 代码重构指南(3k) + 数据库指南(2k) + 测试指南(2k) + 部署指南(1.5k)]
  → System Prompt 总计 15-30k tokens
  → Agent 写代码时，"浏览器操作指南"占了 2k 却完全用不上
  → 15k 指南中当前只需要 2k，其余 13k 全是噪声

按需加载（Demand Paging）：
  System Prompt 放一行摘要（~50 tokens/skill）
  首次使用工具时 → 完整指南（~2K tokens）附着在 tool_result 上
  后续使用（5-20 轮后）→ 关键提醒（~100 tokens）
这是操作系统 Demand Paging 的精确类比：
操作系统：
  程序有 100MB 代码，但任何时刻只有 ~10MB 在物理内存
  用到哪个页面才加载（page fault → load from disk）
  长时间不用的页面被 swap out

Agent：
  30k tokens 的技能知识，但任何一步只需要 ~3k
  当前步骤需要什么技能才加载什么
  agent 看到的是"在需要的时候，指南就出现在旁边"
判断标准：如果一段信息放进 system prompt 后，有 >30% 的 session 不会用到它，就不该预装。
我们把技能加载设计成三层：摘要始终在 system prompt（~50 tokens/技能，永不变，prefix 完全稳定）、完整指南在首次使用时注入、关键提醒在后续使用时注入。还加了错误触发重载：连续 2 次同类工具出错 → 自动重新注入完整指南。顺利时省 token，犯错时加强引导。
原则 3：Spatial Locality（空间局部性）
Arena Allocator 保证了一个天然属性：时间上相近的分配，在内存中物理相邻。这对 CPU cache 极其友好。当你访问一个对象时，它旁边的对象大概率也在同一条 cache line 里。
对上下文来说，空间局部性意味着：相关信息应该在 token 序列中物理相邻，而不是散落在上下文各处。
这解释了为什么把技能指南塞进 system prompt 是错的。agent 在第 42 轮执行浏览器操作时，需要看到浏览器指南，但指南在 system prompt 里（上下文最开头），和当前操作隔了几万个 token。LLM 的注意力在中间衰减（Lost in the Middle），这段距离就是死亡地带。
正确的做法：
... | tool_call(browser_navigate, url) | tool_result(浏览器操作指南 + 实际结果)
                                                      ^^^^^^^^^^^^^^^^^
                                        指南和它指导的操作紧密相邻 → 空间局部性
技能指南作为 tool_result 的一部分追加到末尾，和它指导的那次工具调用物理相邻。Agent 在做决策时，相关指南就在它刚刚"看到"的位置，这就是 cache hit。
同样的逻辑也适用于工作状态的复述。Agent 30 轮前设定的任务目标在哪？在上下文开头附近，已经沉入注意力衰减区。解法不是把它固定在开头（那会破坏 prefix），而是让 agent 主动把关键信息"搬到"末尾：
Agent 读取 todo.md → 工作状态作为 tool_result 出现在末尾
→ LLM 在做决策时直接"看到"当前进度
→ 不需要额外的"工作记忆"抽象
→ 复用已有的文件读写工具
这就是 Manus（百万用户级 Agent 产品）在生产中验证的"复述模式"：通过复述操控注意力，比在 system prompt 中塞工作记忆更有效。 本质上就是 CPU prefetch 的上下文版本，主动把即将需要的数据搬到 cache 最热的位置。
原则 4：Reasoning in Goldilocks Zone
Arena Allocator 有一个最佳大小。太小会频繁 reset（丢弃所有数据重来），太大会浪费物理内存且降低 cache 效率（数据分散在更大的地址空间中，局部性变差）。
上下文同理。并非越大越好。
太空（20% usage）：
  → 可能预装了太多无关信息
  → Agent 在噪声中迷失方向

太满（90%+ usage）：
  → Pruning 频繁触发，丢失关键历史
  → Agent 变成金鱼——记不住 10 轮前做了什么
  → 系统在"保信息"和"留空间"之间挣扎

Goldilocks Zone（40-70% usage）：
  → 上下文只包含当前决策需要的信息
  → 有足够空间给接下来的工具调用
  → Pruning 不触发或只做最轻量的 Soft Trim
  → 信噪比最优
维持 Goldilocks Zone 的手段是两层压缩：
Layer A: Agent 主动压缩
  Agent 判断"这段研究/调试已完成" → tag 起点 → squash 为 summary
  → 压缩质量高：agent 知道什么是 signal vs noise
  → 如果 agent 自觉好，Layer B 可能永远不触发

Layer B: 系统自动 Pruning（安全网）
  三阶段：Soft Trim → Hard Clear → 分级压缩
  → Agent 不自觉时的兜底机制
Agent 主动管理自己的"内存使用"，这不是比喻。我们给 Agent 提供了 context_status 工具，让它看到自己的上下文仪表盘：
[Context Dashboard]
• Usage:           78.2% (100k/128k)
• Steps since tag: 35 (last: 'auth-refactor')
• Pruning status:  Stage 1 approaching
• Est. turns left: ~12
Agent 看到 78% 使用率、距上次 checkpoint 35 步 → 决定主动压缩。Agent 看到 12% 使用率 → 继续工作。这不是 prompt engineering，这是 memory pressure monitoring。
原则 5：批量释放而非逐个回收
Arena Allocator 不支持逐个 free——你不能释放 arena 中间的某个对象然后让后面的对象"紧凑"过来。要释放，就整块 reset。
上下文的约束更严格：你甚至不能真正 reset，因为 reset 意味着丢失所有对话历史。但 arena 的 reset 思维模型仍然适用——当你必须"释放内存"时，单位不是单条消息，而是连续区间：
Agent squash：
  tag("auth-start") → 工作 35 步 → squash("auth-start"到现在, summary)
  → 这 35 步被替换为一段 summary → 释放了大块连续空间
  → backup tag 保留原始历史（arena 的 snapshot 语义）

系统 Pruning：
  不是"删掉第 17 条消息"，而是"从 Turn 5 到 Turn 20 的 tool_result 全部缩减"
  → 连续区间操作，不产生碎片
这和 arena 的 reset 语义一致，批量操作连续区间，而非逐个回收离散对象。
五、Pruning 和 RAG 是补救手段，不是设计原则
原文中最犀利的一句话："Pruning and RAG are tricks, not principles."
这不是在否定 pruning 和 RAG 的价值。它们在生产系统中不可或缺。但它们在概念层级上被高估了。
Pruning 是什么？ 是你的"内存管理"失败后的止损操作。如果你的上下文布局足够好。按需加载、不预装垃圾、Agent 主动保持 Goldilocks Zone，pruning 触发的次数应该极少。就像一个 well-tuned 的 arena allocator 几乎不需要 reset：
如果 arena 频繁 reset → 说明你的 arena 太小，或者你分配了太多短命对象
如果 pruning 频繁触发 → 说明你预装了太多无关信息，或者 agent 不会管理上下文
我们的两层压缩模型把这个逻辑体现得很清楚：
Layer A（agent 主动压缩） → 根本不是 pruning，是 agent 自觉的上下文整理
Layer B（系统 pruning）   → 安全网，理想情况下 永不触发

Layer B 的三个 Stage：
  Stage 1 (Soft Trim)  → 止血（缩减大 tool result）
  Stage 2 (Hard Clear)  → 截肢（旧 tool result 替换为占位符）
  Stage 3 (分级压缩)    → 器官移植（按事件类型差异化处理）
越到后面，信息损失越大。每一个 Stage 都是一次承认："我们的布局没能阻止上下文膨胀。"如果 pruning 是你的核心策略，你已经输了。
RAG 是什么？ 是在上下文中"page fault"后的磁盘读取。Agent 需要一条 20 轮前的决策记录，上下文里已经被 prune 掉了，于是调用 memory_search 从旁路存储中找回来。这是有价值的，它让 prune 掉的信息仍然可召回，而不是永久丢失。但它不应该是你的主要信息传递机制。
操作系统类比：
  在内存中直接访问 → 1 纳秒（L1 cache hit）
  从磁盘 page in  → 10 毫秒（disk I/O）
  
  如果你的系统频繁 page fault → 说明你的内存管理有问题
  如果你的系统频繁 memory_search → 说明你的上下文布局有问题
我在 v1 架构把 RAG 当成核心设计：每轮从记忆库中检索片段插入上下文。这意味着每一步都是 page fault。结果就是 KV Cache 完全失效。因为插入的片段每次都不同，prefix 永远不稳定。
而我的新架构（v2）有修正："检索是 fallback，不是核心路径。" memory_search 是一个 Agent 按需调用的工具，返回结果作为 tool_result 追加到末尾。大部分信息应该已经在上下文里（因为 append-only + 审慎的 pruning），检索只在信息确实被 prune 掉之后才需要。
所以：
原则（布局）：
  Append-only → 前缀稳定 → Cache 命中
  Demand Paging → 只加载需要的 → 不浪费空间
  Spatial Locality → 相关信息相邻 → 注意力集中
  Goldilocks Zone → 信噪比最优 → Agent 不迷失

补救手段（trick）：
  Pruning → 布局失效后的止损
  RAG → 信息被 prune 后的恢复
先把布局做对，补救手段自然用得少。
六、一个完整的心智模型
把所有 Arena 原则组合起来，我们得到一个完整的上下文工程心智模型：
你的工作不是"写好 system prompt"。你的工作是管理这块 arena。
布局决定了 cache 命中率。加载策略决定了空间利用率。局部性决定了注意力效率。压缩策略决定了信息保持率。这些不是语言学问题，不是修辞学问题，它们是内存管理问题。
同样的信息，放在上下文的不同位置、不同时机、以不同密度呈现，效果可以差 10 倍。不是因为模型"没理解"你的文字，而是因为你的布局违反了物理约束。
从今天开始，别说"我在写 prompt"了，说"我在管理一块 128K token 的 arena"。
附：Arena 原则 ↔ 本文的设计映射表
