# 技能包签名与验证（ASVP, Agent Skill Verification Protocol）

## 目的（Purpose）

定义技能包（Skill Package）的签名与验证流程，保证：
- 完整性（Integrity）：文件未被篡改、无额外文件注入
- 真实性（Authenticity）：包来自声明的签名者（signer）

## 范围（Scope）

涵盖：
- 包结构
- `manifest.json` 字段
- `signature.sig` 生成与验证

不涵盖：沙箱隔离与 secrets 模型（见 `SANDBOXING.md`、`SECRETS_BROKER.md`）。

## 核心概念（Concepts）

- 清单（Manifest）：列出包内内容文件的哈希与元数据（Manifest）。
- 签名者（Signer）：拥有 Ed25519 私钥、发布技能包的实体（Signer）。

## 包结构（Package Structure）

一个技能包必须（MUST）是一个目录，包含：
1. `manifest.json`
2. `signature.sig`
3. 内容文件（Content Files）：除隐藏文件外的所有文件

必须（MUST）排除：
- 以 `.` 开头的隐藏文件
- `manifest.json`、`signature.sig` 本身

## 清单（manifest.json）

必须（MUST）字段：
```json
{
  "version": "1.0.0",
  "signer_id": "string",
  "timestamp": 0,
  "files": {
    "relative/path/file.ext": "sha256-hex"
  }
}
```

- `files` 的路径分隔符必须（MUST）使用 `/`（posix 风格）。
- `files` 必须（MUST）覆盖包内所有内容文件，并且不得遗漏。

## 签名（Signature）

- 算法必须（MUST）为 Ed25519（Ed25519）。
- `manifest.json` 必须（MUST）以“规范化 JSON”序列化后再签名：
  - key 按字典序排序
  - 分隔符无空格：`,` 与 `:`
  - UTF-8 编码
- `signature.sig` 内容必须（MUST）为签名 bytes 的 hex 编码（小写/大写均可，验证应接受）。

## 验证（Verification）

验证必须（MUST）包含：
1. 真实性：用 `signer_id.pub` 校验 `signature.sig` 对 `manifest.json` 的签名
2. 完整性：对每个文件计算 SHA-256，与 `files` 匹配
3. 防注入：磁盘上不得存在清单未声明的额外内容文件

## 测试与验收（Tests/Acceptance）

- 任意内容文件被修改：验证必须失败。
- 添加一个额外文件（未进 manifest）：验证必须失败。
- 替换 `signature.sig`：验证必须失败。

