# 🦞 小龙虾

一个基于 QQ 交互的本地 AI 智能体，支持技能插件化、视觉操作、定时任务、永久记忆。

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