# ============================================================================
#  IMPORTANT / 重要说明
#  This code is for EDUCATIONAL PURPOSES only. / 本代码仅供教育用途。
#  Do NOT use for illegal or commercial activities. / 严禁用于非法或商业活动。
#  The author assumes NO RESPONSIBILITY for any misuse. / 作者不对任何滥用行为负责。
# ============================================================================

"""
获取系统信息
"""

import subprocess
import re

def execute():
    try:
        result = subprocess.run(["systeminfo"], capture_output=True, text=True, timeout=30, encoding='gbk')
        output = result.stdout
        fields = {
            'OS Name': r'OS Name:\s*(.+)',
            'OS Version': r'OS Version:\s*(.+)',
            'System Manufacturer': r'System Manufacturer:\s*(.+)',
            'System Model': r'System Model:\s*(.+)',
            'Processor(s)': r'Processor\(s\):\s*(.+)',
            'Total Physical Memory': r'Total Physical Memory:\s*(.+)',
        }
        info_lines = []
        for key, pattern in fields.items():
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                info_lines.append(f"{key}: {match.group(1).strip()}")
        return "\n".join(info_lines[:8])
    except Exception as e:
        return f"获取系统信息失败: {e}"