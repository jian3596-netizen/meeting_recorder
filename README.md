# 会议录音机 (Meeting Recorder)

常驻 Windows 系统托盘（右下角）的轻量会议录音工具。可同时录制**系统音频（扬声器输出）**和**麦克风**，混音保存为单个 WAV 文件。

## 功能

- 启动后最小化到系统托盘，后台常驻。
- **左键双击**托盘图标：开始 / 停止录音（图标变红表示录音中）；也可在右键菜单里单击切换。
- **右键菜单**：开始/停止录音、设置（自动探测、录音源、设备、保存目录）、打开文件夹、退出。
  - 设置里的「保存目录」点击会直接打开该目录；如需更改保存位置，编辑配置文件
    `%APPDATA%\MeetingRecorder\config.json` 里的 `output_dir` 即可。
- 同时捕获系统音频 + 麦克风，自动混音并防削波。
- **自动探测会议**：检测到 Teams / 腾讯会议开始占用麦克风（即进入会议）时，
  弹窗询问是否开始录音；会议结束时自动停止并保存（仅限自动开始的录音）。
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
- 输出为 48 kHz、双声道、16-bit PCM WAV。

## 已知限制 / 可扩展方向

- 录制的是**默认**扬声器与麦克风；也可在「设置 → 设备」中指定。
- 全程音频缓存在内存中，超长会议（数小时）会占用较多内存——如有需要可改为边录边写盘。
- 自动探测依赖「麦克风占用」信号：若开会时未开麦（纯听），则不会触发提示。
- 暂未提供 MP3 压缩、开机自启动等功能，可按需扩展。
