# native_hud — 弈仙牌同域原生 HUD 注入器

frida 把一段 C# 注入游戏自己的 ILRuntime 热更 AppDomain，**直接在游戏画布上画原生
HUD**：记牌器「剩X」、整板 8 回合造伤（matchup）、对手血量/修为、危险牌警告。配一个
tkinter 设置窗口 + 托盘。

**相比旧的代理+网页工具：不需要证书 / mitmproxy / 管理员**——同域读游戏自解码的
protobuf，不碰网络/TLS。

打包成 `YiXianHUD.exe`，双击即用。

**下载**：[Releases](https://github.com/Airexplosion/yixian-card-counter/releases) → `YiXianHUD.exe`（自带 node，无需安装任何东西）。

---

## 功能

| HUD 元素 | 说明 |
|---|---|
| 记牌器 **剩X** | 每张牌剩余可抽数（牌名分隔符 `·/•`、配对牌已对齐） |
| 造伤 **T1–T8** | yisim 整板逐回合累计伤害；**matchup** 模式对着对手板面算，附 `必胜/可赢/会输@Tn` |
| 对手 **命/修 (预估)** | 上轮血量 +2、修为 +5（游戏看不到对手当前回合，只能估） |
| **危险牌警告** | 对手板面出现控制/困锁牌（缚仙古藤、天音困仙曲…共 10 张）就闪红 |
| 离场隐藏 | 进对决/回大厅自动收起覆盖层（去抖防闪） |
| 设置窗口 | 各元素显隐开关 + solo/matchup + 退出 + 最小化到右下角托盘 |

---

## 用法（跑 exe）

> **无需安装任何东西**：exe 自带 node（yisim 伤害模拟用），自带选游戏。

1. **彻底关闭弈仙牌**（spawn 要从头拉起游戏，hook 先于第一帧 → 记牌器从 round 1 全准）。
2. 双击 **`YiXianHUD.exe`**。
3. 找游戏的顺序：同目录有 `YiXianPai.exe` → 直接拉；否则**弹文件框选一次**（记到
   `YiXianHUD_config.json`，下次不再问）。
4. 游戏自己起来 + 弹设置窗口 + 托盘图标。登录开局即见全部 HUD。
5. 停：设置窗口「退出」(关 HUD+游戏)，或托盘右键→退出。

环境变量（可选）：`YX_GAME_EXE`（指定游戏路径）、`YX_ATTACH=1`（挂到已运行的游戏，不
spawn——但记牌器需在开局前挂才全准）、`YX_NOGUI=1`（无窗口，控制台 Ctrl-C 停）。

---

## 从源码构建

### 前置（已随仓库提供，无需自己生成）
`_refs/` 已含构建所需的引用 DLL：
- `DarkSun.HotUpdate.dll` — 游戏热更逻辑（明文未加密），用 UnityPy 从
  `YiXianPai_Data/StreamingAssets/aa/.../0ec79bda…bundle` 的 TextAsset 提取
  （`UnityPy.config.FALLBACK_UNITY_VERSION="2020.3.49f1"`）。
- Unity/TMP/UniRx 等 DummyDll — Il2CppDumper 从 `GameAssembly.dll`+`global-metadata.dat` 反出。

> 这些是游戏版权产物，由仓库所有者选择随仓库提供。游戏更新后需重新提取。

### 工具链
- .NET SDK（`dotnet build`，net40 目标）
- Node + `npm i frida-compile frida-il2cpp-bridge`（编 frida agent）
- Python：`pip install frida blackboxprotobuf msgpack UnityPy pyinstaller pystray pillow`

### 步骤
```bash
# 1) 编 C# → DLL（输出在 csharp/bin/Release/net40/，构建脚本会拷到 _build/）
dotnet build csharp/Hud.csproj    -c Release   # YiXianHud23.dll（HUD）
dotnet build csharp/SimData.csproj -c Release   # YiXianSimData.dll

# 2) 编 frida agent（在仓库根目录）
node node_modules/frida-compile/dist/cli.js autoplay/inject/capture.ts -o native_hud/_build/capture.agent.js
node node_modules/frida-compile/dist/cli.js native_hud/agents/bot_glue3.ts -o native_hud/_build/bot_glue3.agent.js

# 3) 拷 DLL 到 _build/，再打包 exe（在仓库根目录）
python build_hud.py        # → YiXianHUD.exe
```

> 改了 `Hud.cs` 要**改类名 Hud23→Hud24**（csproj 的 AssemblyName 同步），ILRuntime 才会
> 把新代码当新身份加载——这就是 Hud19→Hud23 一路迭代的原因。`OLD_HUDS` 列表负责隐藏旧的。

---

## 架构

```
YiXianHUD.exe (PyInstaller 打包 hud_launcher.py)
  └─ frida.spawn(游戏)  → 先于第一帧挂两段 agent：
       ├─ capture.agent.js — hook ProtobufParser 进/出站
       │     → addon.process_msgpack → shadow_state + Counter（复用代理那套逻辑）
       └─ bot_glue3.agent.js — RPC：把 YiXianHud23.dll 载入 ILRuntime AppDomain，
             调 Show / SetRemaining / SetTotal / SetOpponent / SetWarning / SetPos / SetShowLeft
  · consumer 线程：每个游戏状态 → 算 remaining → 推 SetRemaining（名字展开对齐）+ 对手 + 警告
  · total 线程：每 1.5s → node yisim_marginal.js（matchup vs 对手板面）→ 推 SetTotal
  · Hud23.OnTick(0.5s)：用游戏自己的 FindILRPanel 找 CardPanel（不扫堆 → 不卡），画 HUD
```

**扫描**：全程唯一的 `gc.choose` 是启动时找一次 AppDomain（缓存）；打牌时零扫描。

## 目录
- `csharp/` — 注入的 C# 源（`Hud.cs`=HUD、`SimData.cs`=读牌喂 yisim、`Actions.cs`=动作）。
- `agents/` — frida agent TS（`bot_glue3.ts`=加载/调用胶水）。`capture.ts` 在 `../autoplay/inject/`。
- `bridge/` — `hud_launcher.py`(主) · `hud_gui.py`(设置窗口) · `yisim_marginal.js`(node 算伤害)。
  开发工具：`feed_probe.py`(抓流)、`replay_feed.py`(离线回放)、`nudge.py`(实时调位)、
  `warntest.py`(测警告)、`spawn_launcher.py`/`弈仙牌-注入启动.bat`(裸启动器)。
- `_refs/` — 构建引用 DLL（版权产物）。
- `_build/` — 构建产物（agent.js + DLL，部分随仓库）。

## 状态（2026-06-16）
✅ 同域加载/读写、原生 HUD、记牌器对齐、yisim matchup 伤害、对手信息、危险牌警告、对决隐藏、
设置窗口+托盘、免证书、打包 exe（~94MB，**自带 node**，无需用户安装任何东西）。全部实战验证。
