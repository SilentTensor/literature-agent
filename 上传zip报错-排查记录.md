# 上传 zip 到「导入智能体」报错的排查记录

> 结论：**不是 zip 的问题，是那个平台把 zip 当成 Android 安装包（APK）在解析。**
> 本文记录完整证据，方便你以后遇到类似情况时直接放弃这条路，或者拿去问平台客服。

---

## 报错原文

```
导入智能体 → 上传文件 → 本地文件不超过 100 MiB → 上传 zip
No signature found after EOCD record.
```

---

## 排查过程与证据

### 第 1 次上传：18.3 MB 的包

第一次的 `智能文献调研.zip` 是**直接压缩整个项目文件夹**得到的，里面混进了大量无关内容：

| 内容 | 条目数 | 原始大小 |
|---|---|---|
| `.venv\Lib`（本机 Python 环境） | 6375 | 46 MB |
| `logs\node_modules` | 292 | 1.1 MB |
| `.git\objects`（版本库历史） | 148 | 175 KB |
| **真正的项目文件** | **25** | **约 200 KB** |

当时的判断是"包太大/条目太多导致传输截断"。**这个判断后来被证明是错的。**

### 第 2 次上传：重新打包的 74.7 KB 干净包

重新生成了只含 25 个项目文件的包（74.7 KB），结构经过多重校验：

| 校验方式 | 结果 |
|---|---|
| Python `zipfile` 读取 | ✅ 25 个条目，无损坏 |
| EOCD 结构自洽性（条目数 / 中央目录偏移 / 长度一致性） | ✅ 全部自洽 |
| Windows 自带 `Expand-Archive` 解压 | ✅ 成功，25 个文件 |
| PowerShell `Compress-Archive` 生成的对照包 | ✅ 同样被接受 |

**仍然报同一个错。** 这就排除了"包坏了""包太大""条目太多"这几种可能。

### 真正的根因

`No signature found after EOCD record` 这句话不是通用 zip 解析器的报错，而是
**Android APK 签名验证库（`apksig` / `apkzlib`）** 的专属信息。

它的逻辑是：先定位 zip 的 EOCD（中央目录结束记录），然后在 EOCD **之后**
寻找 `APK Sig Block 42` —— 也就是 APK Signature Scheme v2/v3 的签名块。

普通 zip 文件里**根本不存在**这个块（实测确认：本项目生成的所有 zip 都不含该标记），
所以这个验证**必然失败**，与 zip 本身正确与否完全无关。

> 相关源码片段可参考 Android 官方仓库 `platform/tools/apkzlib` 与 `platform/tools/apksig`
> 中关于 `foundEocdSignatureIdx` / APK 签名块的实现。

---

## 结论与建议

**这是平台侧的问题，不是你文件的问题。** 普通 zip 不可能通过 APK 签名校验。

可行的做法：

1. **放弃"导入智能体"这条路**，改用平台提供的其它接入方式（如果有的话），
   例如直接填写一个公网 URL 让平台去访问 —— 本项目的公网地址见 `public-url.txt`。
2. 或者去问平台客服：为什么导入普通 zip 会触发 APK 签名校验？上传格式到底要求什么？
   把本文的报错原文和"这是 apksig 的报错"这两条信息给他们，通常能较快定位。
3. 最省事：**不依赖那个平台**，直接用本项目自带的公网地址分享给别人。

---

## 以后自己打 zip 的正确姿势

**不要右键压缩整个项目文件夹**，那会把 `.venv`（46 MB 本机环境）、`logs`、`.git` 全部打进去。

正确做法：进到 `literature-agent` 文件夹**里面**，只选中这些再压缩：

```
app.py                 static\              requirements.txt
README.md              render.yaml          Dockerfile
verify.py              其余说明文件
```

或者更省事——**双击 `一键上传到GitHub.bat`**：它的忽略规则已经配好，
永远不会把 `.venv` 和 `logs` 传上去（这也是我推送到 GitHub 用的方式）。
