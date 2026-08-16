# ============================================================================
#  IMPORTANT / 重要说明
#  This code is for EDUCATIONAL PURPOSES only. / 本代码仅供教育用途。
#  Do NOT use for illegal or commercial activities. / 严禁用于非法或商业活动。
#  The author assumes NO RESPONSIBILITY for any misuse. / 作者不对任何滥用行为负责。
# ============================================================================


"""
备份指定目录到目标目录
"""

import shutil
from pathlib import Path

def execute(src, dst):
    src = Path(src).resolve()
    dst = Path(dst).resolve()
    if not src.exists():
        return f"源目录不存在: {src}"
    try:
        shutil.copytree(src, dst, dirs_exist_ok=True)
        return f"已备份 {src} 到 {dst}"
    except Exception as e:
        return f"备份失败: {e}"
