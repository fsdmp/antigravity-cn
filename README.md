# antigravity-cn — Antigravity IDE 简体中文汉化包

针对 Google Antigravity IDE（VS Code 1.107 内核 fork，bundle id `com.google.antigravity-ide`）的离线简体中文汉化方案。

**核心原则：完全不修改 `/Applications` 下的任何应用文件** —— 应用签名、ElectronAsarIntegrity 完整性校验、官方自动更新均不受影响。

## 为什么坚持零修改（对比改 asar 的方案）

社区汉化方案（asar 补丁）的路线是解包 `app.asar` → 改字符串 → 重打包。**`app.asar` 与 `default_app.asar` 均在代码签名的封签资源清单内**（已在本机 `Contents/_CodeSignature/CodeResources` 验证），改动即触发一条完整的连锁反应：

| 连锁后果 | 改 asar（社区做法） | 零修改注入（本项目） |
|---|---|---|
| **代码签名** | `codesign --verify` 当场失效，与官方发布物不再一致 | 完整有效（已实测） |
| **系统拦截** | 失效签名可能被判「已损坏」——xattr 隔离、系统更新、迁移助手后可能直接拒绝启动，需手动放行 | Gatekeeper 照常接受 |
| **Electron 运行时校验** | `ElectronAsarIntegrity` 在 Info.plist 里记录 asar 目录头哈希，校验 fuse 启用时哈希不符**拒绝启动**；要绕过就得连 Info.plist 一起改，破坏进一步加深 | 校验天然通过 |
| **官方自动更新** | 更新器覆盖 bundle 后补丁消失（汉化无声失效，每次升级都得重打）；若更新器校验现有安装完整性，改过的包可能直接更新失败 | 升级流程完全不受影响；词典以英文原文为键，新版本自动命中旧译文 |
| **杀软 / EDR / 企业管控** | 「已签名应用被篡改」是经典告警特征，MDM 管控的机器可能直接隔离 | 无文件级差异，零告警面 |
| **被官方察觉的风险** | 改动后的文件哈希可被官方完整性检查收集，构成可检测异常 | 不产生任何可被远端采集的文件差异 |
| **长期维护成本** | 每个新版本重新解包-改-打包-对哈希 | 磁盘上永远没有需要维护的补丁 |

一句话：**改 asar 是「为了汉化把应用改成了另一个东西」，零修改是「应用始终是官方原件，汉化只存在于运行时」。** 前者的全部代价都来自签名失效这一个根因。

本项目的两条注入通道也都不是灰色地带：
- **IDE 侧**：语言包（`contributes.localizations`）是 VS Code 官方支持的本地化机制，走的是产品自带正门
- **管理器侧**：`--remote-debugging-port` 是官方 main.js 显式兼容的开关（检测到该开关时保留 active-port 文件），CDP 注入全程不落盘

自验命令（装机后随时可跑）：

```bash
codesign --verify --deep --strict /Applications/Antigravity.app        # 签名完整性
spctl -a -t exec /Applications/Antigravity.app                          # Gatekeeper 评估
python3 scripts/manager/integrity_check.py                              # asar 与官方哈希比对
```

## 快速开始

```bash
# 安装（离线，重启 IDE 后生效）
python3 scripts/install.py

# 卸载（完整还原安装前状态）
python3 scripts/uninstall.py

# IDE 升级到新版本后：重新生成并安装
python3 scripts/update.py --install

# Antigravity.app 管理器中文界面（双击「管理器汉化.command」等价）
python3 scripts/manager/zh_hub.py --relaunch        # 前台守护
python3 scripts/manager/zh_hub.py --background      # 后台守护
python3 scripts/manager/zh_hub.py --stop            # 停止守护
python3 scripts/manager/zh_hub.py --status          # 查看状态
```

安装内容：
1. 离线安装语言包 VSIX（走 IDE 自带 CLI，失败时自动落盘手动安装；全程不联网、不访问扩展市场）
2. `argv.json` 设置 `locale: zh-cn`
3. `settings.json` 关闭遥测上报（telemetryLevel=off）
4. Antigravity.app 管理器设置 AppleLanguages 偏好（远程 UI 若官方支持中文则自动切换）
5. 主动维护 `languagepacks.json`（主进程发现语言包的唯一入口，见下文）

## 原理

Antigravity IDE 是 VS Code fork，全部界面字符串位于应用内 `out/nls.messages.json`（扁平英文数组），索引由 `out/nls.keys.json`（`[模块路径, [键名...]]`）描述。安装 `contributes.localizations` 语言包扩展后，主进程按「模块路径 + 键名」在语言包的 `translations/main.i18n.json` 中查找译文，**查不到自动回退英文**。

译文来源两层：
- `reference/zhpack-*/` — 官方 [MS-CEINTL.vscode-language-pack-zh-hans](https://open-vsx.org/extension/MS-CEINTL/vscode-language-pack-zh-hans)（MIT 许可），覆盖约 1336 个上游模块
- `translations/antigravity-ext.i18n.json` — 翻译记忆（**以英文原文为键**），覆盖 Antigravity 专有模块（代理/后台流程/管理面板等约 51 个模块）

## 关键设计

### 为什么支持后续版本升级
翻译记忆以**英文原文**为键，而非模块路径或内部键名。IDE 升级后即使模块重组、键名变更，只要英文原文未变就自动命中；新增未翻译的字符串按 NLS 默认行为回退英文，不影响使用。升级后运行 `scripts/update.py --install` 即可重新生成针对新版本的包（脚本会列出官方包和记忆都未覆盖的新增英文串供补充）。

### 缓存失效机制（重要）
VS Code 主进程读 `~/Library/Application Support/Antigravity IDE/languagepacks.json` 发现语言包，其中 `hash = md5(扩展ID + 版本号)`，**与译文内容无关**；`clp/` 缓存目录名为 `<hash>.<语言>`，hash 不变就永远复用旧缓存。因此 `build_vsix.py` 将版本号 patch 位设为译文内容的 md5 派生值——内容一变版本号自动变化，缓存随之失效。`install.py` 会主动重写 `languagepacks.json` 并清理旧 hash 缓存目录（CLI 安装后该文件经常不被立即更新）。

### 不被官方远端捕捉
- 扩展 ID 为自定义 publisher（`antigravity-cn`），离线安装，不经过 Open VSX / marketplace，无安装来源上报
- 安装时将 `telemetry.telemetryLevel` 设为 `off`、关闭 crash reporter
- 语言包本身是纯本地 JSON 数据，不做任何网络请求

### Intel / Apple Silicon 双芯片通用
语言包是纯 JSON 文本 + PNG，不含任何原生二进制，x86_64 与 arm64 通用；构建产物只有一份 VSIX。

### Antigravity.app 管理器（CDP 注入，零文件修改）
管理器 Hub UI 是本地语言服务器（`Resources/bin/language_server`）在 `https://127.0.0.1:<动态端口>` 托管的 Web 应用，LS 二进制内置英文界面、无中文资源；应用受 ElectronAsarIntegrity 保护，改 asar 会破坏签名/更新（社区项目的做法）。

本项目的做法是**从进程外注入**：
1. 以 `--remote-debugging-port=0`（随机回环端口）启动管理器——官方 main.js 显式兼容该开关（检测到时会保留 active-port 文件）
2. 从 stderr 读取 DevTools 地址，通过 CDP 对每个 Hub 页面执行 `Page.addScriptToEvaluateOnNewDocument` 注入翻译脚本
3. 脚本做「文本节点精确词典匹配」替换 + 少量动态正则，输入区/contenteditable/Monaco/消息正文容器物理免疫，词典未命中的文本一律不碰

约束与代价：
- 必须通过本工具启动管理器（Dock 直接点开无注入）；已在运行时用 `--relaunch`
- 守护进程需保持运行（`--background` 后台化），管理器退出后守护自动跟随退出
- 顶部菜单栏/托盘菜单是主进程原生 UI，保持英文（CDP 够不到）
- `plugin://` 插件 iframe 与用户消息正文不翻译（防止误伤用户内容）
- 零持久化状态：无需"卸载"，`--stop` 停守护即可；`/tmp/antigravity-cn-hub/` 重启自动清空

词典来源：`translations/hub-community.i18n.json` 来自社区项目 [antigravity-cn-community/Antigravity-Chinese-Localization](https://github.com/antigravity-cn-community/Antigravity-Chinese-Localization)（MIT，许可文件 `hub-community.LICENSE`）+ 本项目补充 `hub-ext.i18n.json`。管理器升级后如遇新增未翻界面串，补进 `hub-ext.i18n.json` 后重跑 `python3 scripts/manager/build_hub_dict.py`。

## 目录结构

```
antigravity-cn/
├── README.md
├── 管理器汉化.command        # 管理器中文界面双击启动器
├── scripts/
│   ├── fetch_reference.py   # 从 Open VSX 下载官方语言包作翻译底料 (MIT)
│   ├── build_vsix.py        # 合并官方翻译 + 翻译记忆, 生成 VSIX (版本号随内容)
│   ├── install.py           # 离线安装 + locale + 遥测关闭 + languagepacks.json 维护
│   ├── uninstall.py         # 完整卸载还原 (含被污染备份的兜底识别)
│   ├── update.py            # IDE 升级后一键重新构建/安装
│   └── manager/
│       ├── zh_hub.py        # 管理器 CDP 注入启动器/守护 (纯 stdlib)
│       ├── inject.js        # 注入的 Hub 翻译引擎 (词典精确匹配 + 免疫规则)
│       └── build_hub_dict.py# 合并社区词典 + 本项目补充 → hub.i18n.json
├── translations/
│   ├── antigravity-ext.i18n.json   # IDE 翻译记忆: 英文原文 → 中文
│   ├── hub-community.i18n.json     # 管理器词典底料 (社区 MIT)
│   ├── hub-community.LICENSE       # 社区词典许可文件
│   ├── hub-ext.i18n.json           # 管理器词典本项目补充
│   └── hub.i18n.json               # 管理器词典构建产物
├── reference/               # 官方语言包解包 (本地底料)
│   ├── zhpack-1.106.0/
│   └── zhpack-1.108.0/
└── build/                   # 产物: antigravity-ide-zh-hans-1.106.<patch>.vsix
```

## 常见问题

- **IDE 装完没变中文？** 必须完整退出并重启 IDE（Cmd+Q 后重开）；同会话新开窗口不会重新解析 NLS
- **管理器从 Dock 直接点开变英文了？** 正常 —— 必须经本工具启动才有注入。先 `--stop` 停守护，再双击「管理器汉化.command」或 `--relaunch`
- **守护进程怎么排错？** 日志在 `/tmp/antigravity-cn-hub/daemon.log`（`--background` 输出会提示路径）；`--status` 查看运行状态
- **IDE 升级 / 管理器升级后出现新的英文串？** IDE 按「IDE 升级后怎么办」补充翻译记忆；管理器把英文原文 → 中文补进 `translations/hub-ext.i18n.json`，重跑 `python3 scripts/manager/build_hub_dict.py` 后重启管理器
- **想彻底回到原生英文？** IDE 跑 `python3 scripts/uninstall.py`；管理器跑 `python3 scripts/manager/zh_hub.py --stop`（零持久化，无需其他清理）

## 已验证结论（2026-11-26，IDE 2.8.0 / 内核 1.107.0）- 界面汉化实际生效：`clp/<hash>.zh-cn/<commit>/nls.messages.json` 缓存生成，16558 条中 16348 条为中文，其余为 Ctrl/LF/CRLF/URL/Copilot 等官方风格本就保留英文的键
- 启动日志无语言包相关错误；CLI 安装时输出的 `[createInstance] extensionManagementService depends on antigravityAnalytics` 为无害 stderr 噪音
- 安装 → 重启 → 中文界面；卸载 → 重启 → 英文界面，全部配置精确还原
- 注意：安装后需**完整退出并重启** IDE（同会话新开窗口不会重新解析 NLS）

## IDE 升级后怎么办

1. 正常让 Antigravity IDE 自动升级（语言包不影响升级）
2. 升级完成后运行 `python3 scripts/update.py --install`
3. 构建输出会列出暂无译文的新增英文串，按需补充到 `translations/antigravity-ext.i18n.json`（键为英文原文），再运行一次即可
