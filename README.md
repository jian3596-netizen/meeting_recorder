# 会议录音机 (Meeting Recorder)

常驻 Windows 系统托盘（右下角）的轻量会议录音工具。可同时录制**系统音频（扬声器输出）**和**麦克风**，混音保存为单个 WAV 文件。

## 功能

- 启动后最小化到系统托盘，后台常驻。
- **左键双击**托盘图标：开始 / 停止录音（图标变红表示录音中）；也可在右键菜单里单击切换。
- **右键菜单**：开始/停止录音、设置（自动探测、录音源、设备、保存目录）、打开文件夹、退出。
  - 设置里的「保存目录」点击会直接打开该目录；如需更改保存位置，编辑配置文件
    `%APPDATA%\MeetingRecorder\config.json` 里的 `output_dir` 即可。
- 同时捕获系统音频 + 麦克风，自动混音并防削波。
- **自动探测会议**：检测到 Teams / 腾讯会议开始占用麦克风（进入会议）时，
  气泡询问是否开始录音；会议结束（停止占用麦克风）时，若在录音则气泡询问是否停止。
- **最大时长 2 小时**：距上限还剩 10 分钟时气泡提示（可选择立即停止），
  到达 2 小时自动停止并保存。
- 所有提示统一为右下角浅色半透明圆角气泡卡片。
- 录音保存到 `C:\Users\<你>\Meeting Recordings\meeting_<时间戳>.wav`。

## 直接使用（exe）

打包好的可执行文件在 `dist\MeetingRecorder.exe`，双击即可运行，无需安装 Python。

## 从源码运行

依赖管理使用 [uv](https://github.com/astral-sh/uv)：

```bash
uv sync          # 安装依赖
uv run python main.py
```

## 重新打包 exe

直接双击运行 `build.bat`（会自动同步依赖并打包），或在命令行执行：

```bash
uv run pyinstaller --noconfirm --onefile --windowed \
    --name MeetingRecorder --icon icon.ico \
    --collect-all soundcard main.py
```

生成的文件位于 `dist\MeetingRecorder.exe`（单文件，约 30 MB）。

## 图标

- `icon.ico`（麦克风）用作 exe 图标（PyInstaller `--icon`），由 `icon.svg` 转换而来。
- 托盘图标为程序绘制的圆点：空闲灰色、录音中红色。

## 技术说明

- **录音**：`soundcard` 库，通过 Windows WASAPI loopback 抓取默认扬声器输出，同时录制默认麦克风；两路各用一个线程，停止时按较短长度对齐并相加混音。
- **自动探测**：轮询注册表 `CapabilityAccessManager\ConsentStore\microphone`，
  当 Teams（`MSTeams…`）/ 腾讯会议（`WeMeetApp.exe`）的 `LastUsedTimeStop` 为 0
  （表示正在占用麦克风）时判定为进入会议。
- **托盘**：`pystray` + `Pillow` 绘制圆点图标。
- 输出为 48 kHz、单声道、16-bit PCM WAV（约 330 MB/小时，不做有损压缩）。

## 出错排查

- 程序出现警告/错误时，会在 **exe（或脚本）同目录**生成 `error.log`，
  记录完整堆栈；运行正常时不会生成该文件。
- 所有托盘回调与后台线程都做了异常捕获并落盘，避免单个异常把程序卡住。
- 反馈问题时可附上这个 `error.log`。

## 已知限制 / 可扩展方向

- 录制的是**默认**扬声器与麦克风；也可在「设置 → 设备」中指定。
- 全程音频以单声道 int16 缓存在内存中，停止时混音写盘；超长会议（数小时）
  仍会占用一定内存——如有需要可改为边录边写盘。
- 自动探测依赖「麦克风占用」信号：若开会时未开麦（纯听），则不会触发提示。
- 暂未提供压缩、开机自启动等功能，可按需扩展。
