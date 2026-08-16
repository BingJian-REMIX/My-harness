---
name: clean_temp
description: 清理系统临时文件，释放磁盘空间。
parameters:
  days: 可选，保留最近N天的文件，默认7天。
---

```python
import os, shutil, time
from pathlib import Path

def execute(days=7):
    total_freed = 0
    temp_dirs = [
        Path(os.environ.get('TEMP', 'C:\\Temp')),
        Path(os.environ.get('TMP', 'C:\\Temp')),
        Path('C:\\Windows\\Temp'),
        Path(os.path.expandvars('%USERPROFILE%\\AppData\\Local\\Temp'))
    ]
    now = time.time()
    for temp_dir in temp_dirs:
        if temp_dir.exists():
            for item in temp_dir.iterdir():
                try:
                    if item.is_file() and (now - item.stat().st_mtime) > days * 86400:
                        total_freed += item.stat().st_size
                        item.unlink()
                    elif item.is_dir() and (now - item.stat().st_mtime) > days * 86400:
                        shutil.rmtree(item, ignore_errors=True)
                except Exception:
                    pass
    return f"清理完成，释放了约 {total_freed // (1024*1024)} MB 空间。"
```
