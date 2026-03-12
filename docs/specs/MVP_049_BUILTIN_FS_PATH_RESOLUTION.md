# MVP_049_BUILTIN_FS_PATH_RESOLUTION

- 状态（Status）：Draft
- 日期（Date）：2026-03-07
- 目标版本（Target）：MVP_049
- 相关规范（Related Specs）：
  - `docs/specs/MVP_030_CAPABILITY_SCHEMA.md`
  - `docs/specs/MVP_042_PA_TASK_GRAPH.md`
  - `docs/specs/SANDBOXING.md`

## 目的（Purpose）

定义内置文件/命令能力（builtin `fs.read` / `fs.list` / `fs.write` / `shell.exec`）在工作区根目录（Workspace Root）内的最小路径解析契约，避免 Personal Assistant 在跨机器、跨用户目录或 `~` 表达下把同一仓库误判为“文件不存在”或“越权路径”。

## 范围（Scope）

本规范覆盖：
- `builtin://fs.read`
- `builtin://fs.list`
- `builtin://fs.write`
- `builtin://shell.exec`

本规范不覆盖：
- 非文件类 builtin
- 沙箱外路径授权
- 网络路径、挂载点发现与符号链接策略扩展

## 语义（Semantics）

### 工作区根目录（Workspace Root）解析（MUST）

- 运行时必须（MUST）先确定当前工作区根目录。
- 若 `policy_context.workspace_root` 存在且非空，运行时必须（MUST）使用该值作为工作区根目录。
- 否则运行时必须（MUST）回退到当前进程 `cwd` 的绝对路径。

默认值（MUST）：
- `workspace_root = cwd.resolve()`

### 相对路径解析（MUST）

- 相对路径必须（MUST）相对于工作区根目录解析。
- 解析结果若落到工作区根目录之外，运行时必须（MUST）拒绝执行并返回 `E_EXECUTION_FAILED`。

### 用户目录展开（Home Expansion，MUST）

- 输入路径若以 `~` 或 `~/` 开头，运行时必须（MUST）先做本机用户目录展开，再继续路径校验。
- 展开后的结果若位于当前工作区根目录内，运行时必须（MUST）视为合法路径。

### 路径别名（Path Alias）重映射（SHOULD）

- 对绝对路径输入，若其不在当前工作区根目录内，但其尾部仓库片段与当前工作区根目录一致，运行时应该（SHOULD）将其重映射到当前工作区根目录下的对应子路径。
- 重映射只可以（MAY）用于“同一仓库不同机器/用户目录前缀”的情况，例如：
  - `/Users/runner/codex/agentos-next`
  - `/home/oai/codex/agentos-next`
  - `/root/codex/agentos-next`
- 运行时禁止（MUST NOT）把无法证明属于当前工作区的任意绝对路径映射进工作区。

默认值（MUST）：
- 路径别名匹配最小锚点为当前工作区根目录的末尾两个路径段。

### shell.exec 的 cwd（MUST）

- `builtin://shell.exec` 的 `cwd` 必须（MUST）复用同一套路径解析规则。
- 若 `cwd` 无法解析到工作区根目录内，运行时必须（MUST）拒绝执行，不得把命令落到未知目录。

## 错误码（Error Codes）

- `E_EXECUTION_FAILED`

错误详情（MUST）：
- 越界路径必须（MUST）返回 `access denied: <raw_path> is outside workspace root`
- 缺失文件必须（MUST）返回 `file not found: <raw_path>`
- 缺失目录必须（MUST）返回 `directory not found: <raw_path>`

## 边界条件（Boundary Conditions）

- 解析后命中工作区根目录本身时，`fs.list` 必须（MUST）允许执行。
- 绝对路径别名若只匹配到单个目录名，运行时必须（MUST）拒绝，避免误命中同名项目。
- 路径展开与重映射必须（MUST）发生在最终越界校验之前。
- 任一路径解析都不得（MUST NOT）放宽既有的工作区越界限制。

## 兼容策略（Compatibility）

- 本规范为 additive change。
- 旧调用方继续传相对路径时，行为必须（MUST）保持不变。
- 新增的 `workspace_root` 仅作为策略上下文提示，不改变顶层 `ExecuteRequest` 结构。

## 测试与验收（Tests/Acceptance）

必须（MUST）满足：
1. `~` 路径可解析到当前工作区根目录中的同名文件。
2. 跨主机仓库绝对路径别名可重映射到当前工作区。
3. `shell.exec` 的绝对路径别名 `cwd` 可在当前工作区内成功执行。
4. 与当前工作区无关的绝对路径必须继续拒绝。

回归命令（MUST）：
- `PYTHONPATH=src python3 -m unittest tests/test_thread049_builtin_fs_path_resolution.py -v`
