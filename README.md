# 🦞 小龙虾

一个基于 QQ 交互的本地 AI 智能体，支持技能插件化、视觉操作、定时任务、永久记忆。

> **⚠️ 重要声明 / IMPORTANT NOTICE**
> 
> 本项目 **仅用于教育和研究目的**，严禁用于任何非法或商业用途。
> 使用者应自行承担因违规使用而产生的全部法律责任。
> 作者不对任何第三方使用本软件的行为负责。
> 
> 使用前请确保您的行为符合所在地区的法律法规和相关服务条款。
> 详见 [免责声明](DISCLAIMER.md)。
> 
> ---
> 
> This project is **intended solely for educational and research purposes**. It is strictly prohibited to use it for any illegal or commercial activities.
> Users bear full legal responsibility for any misuse of this software.
> The author assumes no responsibility for any third-party use of this software.
> 
> Before using, please ensure your actions comply with applicable laws and Terms of Service.
> See [DISCLAIMER](DISCLAIMER.md) for details.

## 快速开始

1. 安装依赖：
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

2. 修改 bot.py 中的 CONFIG["admin_qq"] 为你的 QQ 号。
3. 配置 NapCat（OneBot 协议端），确保 WebSocket 地址为 ws://127.0.0.1:6700。
4. 运行：
   ```bash
   python bot.py
   ```
   或双击 run.bat
5. 在 QQ 中发送 #auth add <QQ号> <昵称> 添加授权用户。
