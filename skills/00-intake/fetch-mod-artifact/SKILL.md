---
id: fetch-mod-artifact
version: 0.1.0
stage: 00-intake
execution: deterministic
status: implemented
reads: []
writes: []
depends_on: []
acceptance: ["下载产物记录 url / size / sha256", "产物只落在 work/ 等被 .gitignore 排除的目录", "校验和不一致即失败"]
---

# fetch-mod-artifact

## 目的

从官方源获取第三方 mod 产物并记录 provenance，为双轨实验提供可复现的输入。**产物绝不入库。**

## 版权边界（硬性）

TaCZ 源码为 GPL-3.0，资产为 CC BY-NC-ND 4.0。本仓库只保留统计、unit_id 与规则，不保留任何源码、jar、贴图、模型或音效。`.gitignore` 已排除 `work/`、`*.jar`、`*.class`、`*.png` 等。

## 输入输出

```
输入: --url（官方源码包 / 编译 jar / 反编译器）
输出: work/ 下的二进制 + 可选的 provenance JSON
```

不写 manifest。provenance 记录 `url` / `size_bytes` / `sha256`，供后续实验复核「输入是否同一个」。

## 实测来源（TaCZ 1.20.1 Forge 1.2.0）

- 源码包：`https://codeload.github.com/MCModderAnchor/TACZ/zip/refs/heads/1.20.1`（799 个 `.java`）
- 编译产物：Modrinth `tacz-forge-1.20.1-1.2.0.jar`（1061 个 `.class`）
- 反编译器：Maven 镜像上的 Vineflower 1.12.0
- 版本清单：`api.github.com` / `api.modrinth.com` 的公开 API

本机代理只放行网页与上述 CDN/API 域名，`.git` smart-HTTP 端点被拒——因此获取产物走 HTTP 下载，不走 git clone。

## 边界

- 不下载任何来源不明的镜像；不把凭据写进命令或日志。
- 不跳过校验和；校验失败必须中止。
- 不检查、不修改产物内容，只做获取与记录。

## 运行

```bash
python skills/00-intake/fetch-mod-artifact/run.py \
  --url "<official-url>" --out work/artifact.zip \
  --provenance-out work/artifact.provenance.json
```
