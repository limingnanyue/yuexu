# 本地语音识别运行环境（可选）

QQ 原生通话是可选能力，依赖 Windows 上的 NapCat AV 接口、虚拟音频线路与本地 ASR。
组件齐备后，可用 `start-call.ps1` 依次启动虚拟音频混音器、QQ 原生桥、ASR 和连接器；
后端仍按原有方式启动。脚本启动成功不等于 QQ 已登录或通话已验收。

## ASR 服务

`start-asr.ps1` 会在 `data/voice_call/asr/` 下运行 SenseVoiceSmall int8 与独立的 Python 环境。
服务只监听 `127.0.0.1:50000`，不需要 PyTorch、GPU 或外部识别 API，也不影响主项目的虚拟环境与配置。

项目根目录执行：

```powershell
.\deploy\voice_call\start-asr.ps1
```

脚本会隐藏运行窗口、复用已启动的服务，并把输出、错误和 PID 写到
`data/voice_call/asr/stdout.log`、`stderr.log`、`service.pid`。服务不会注册为开机启动项。

健康检查：`GET http://127.0.0.1:50000/health`。
识别入口：`POST http://127.0.0.1:50000/api/v1/asr`，接收 16kHz、单声道、16 位 PCM WAV，
最长 30 秒；multipart 参数为 `files`、`keys`、`lang=auto`、`use_itn=true`，
与 `ASRService` 客户端一致。不支持 MP3、多文件和强制切换语言。

## 重建环境

用 Python 3.12 创建 `data/voice_call/asr/.venv`，安装 `deploy/voice_call/asr-requirements.txt`；
模型目录默认为 `data/voice_call/asr/models`，也可以用 `YUEXU_ASR_MODEL_DIR` 指定。

模型使用 [sherpa-onnx 官方发布的 SenseVoiceSmall int8](https://k2-fsa.github.io/sherpa/onnx/sense-voice/pretrained.html)，
版本 `2024-07-17`：

```text
https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2
```

归档 SHA256 为 `7d1efa2138a65b0b488df37f8b89e3d91a60676e416f515b952358d83dfd347e`，
大小 163002883 字节。解压后的 `model.int8.onnx`、`tokens.txt` 和 `LICENSE`
保留在模型目录中。普通话使用该原版模型；2025-09 的粤语微调版不支持标点，未采用。

> 语音通话涉及第三方协议端与虚拟音频驱动，配置在不同机器上差异很大。
> 仓库只保留脚本与协议说明，不附带任何账号数据、驱动或模型文件。
