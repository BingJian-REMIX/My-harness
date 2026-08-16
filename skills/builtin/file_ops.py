# ============================================================================
#  IMPORTANT / 重要说明
#  This code is for EDUCATIONAL PURPOSES only. / 本代码仅供教育用途。
#  Do NOT use for illegal or commercial activities. / 严禁用于非法或商业活动。
#  The author assumes NO RESPONSIBILITY for any misuse. / 作者不对任何滥用行为负责。
# ============================================================================

"""
文件操作技能：列出目录、读取文件、写入文件
"""

import os
from pathlib import Path

WORKSPACE_ROOT = Path(os.environ.get('LOBSTER_WORKSPACE', './workspace')).resolve()

def _sandbox_check(path):
    """漏洞6：路径沙盒校验，文件路径必须位于 workspace/{uid}/ 内"""
    uid = os.environ.get('LOBSTER_CURRENT_UID', 'shared')
    base = (WORKSPACE_ROOT / str(uid)).resolve()
    try:
        resolved = Path(path).resolve()
    except Exception:
        return False, f"路径无效: {path}"
    if str(resolved) == str(base) or str(resolved).startswith(str(base) + os.sep):
        return True, ""
    return False, f"⛔ 路径越权：{path} 不在沙盒 {base} 内"

def execute(action, path, content=None):
    """
    action: 'list', 'read', 'write'
    path: 文件或目录路径
    content: 写入内容（仅 write 需要）
    """
    path = Path(path).resolve()
    ok, reason = _sandbox_check(path)
    if not ok:
        return reason
    if action == 'list':
        if not path.exists():
            return f"路径不存在: {path}"
        return "\n".join([str(p) for p in path.iterdir()])
    elif action == 'read':
        if not path.exists():
            return f"文件不存在: {path}"
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()[:5000]
    elif action == 'write':
        if not content:
            return "写入内容不能为空"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"文件已写入: {path}"
    else:
        return f"不支持的操作: {action}"