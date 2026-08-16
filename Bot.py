#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================
#  IMPORTANT / 重要说明
#  This code is for EDUCATIONAL PURPOSES only. / 本代码仅供教育用途。
#  Do NOT use for illegal or commercial activities. / 严禁用于非法或商业活动。
#  The author assumes NO RESPONSIBILITY for any misuse. / 作者不对任何滥用行为负责。
# ============================================================================

"""
小龙虾 v2.0 —— DeepSeek 主脑 + Kimi 视觉专家
功能：QQ消息接入、双模型协作、技能插件化、交互式Shell、永久记忆、定时任务、屏幕视觉操作
"""

import os
import sys
import time
import json
import re
import subprocess
import threading
import contextvars
import queue
import importlib
import importlib.util
import inspect
import logging
import concurrent.futures
import hashlib
from pathlib import Path
from collections import deque
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

import requests
import websockets.sync.client as websockets
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import yaml
import pyautogui
from PIL import Image
import schedule  # 需安装：pip install schedule

# ==================== 全局配置 ====================
CONFIG = {
    "admin_qq": "123456789",               # 管理员QQ号（必须修改）
    "workspace": "./workspace",
    "auth_file": "authorized_users.json",
    "skills_config": "skills_config.json",
    "skills_dir": "skills",
    "memory_file": "memory.json",
    "deepseek_state_file": "deepseek_state.json",
    "kimi_state_file": "kimi_state.json",
    "context_limit": 5,
    "poll_interval": 1,
    "headless": False,
    "napcat_ws": "ws://127.0.0.1:6700",
    "napcat_http": "http://127.0.0.1:5700",
    "only_mention": True,
    "bot_nickname": "小龙虾",
    "direct_cmd_prefix": "#",
    "code_review_enabled": True,
    "response_timeout": 30,
    "max_collab_rounds": 10,
    "max_review_rounds": 5,                 # 双AI审查最大轮次，超过则请求人工介入
    "max_message_chars": 3000,              # 单条消息硬截断阈值（字）
    "command_guard_blacklist": True,        # 高危命令黑名单（第一层）
    "command_guard_semantic": True,         # Kimi 语义鉴定（第二层）
    "long_command_chars": 200,              # 行为指纹：单条命令超过此长度视为“长指令”
    "long_command_review_threshold": 3,     # 行为指纹：连续 N 次长指令触发人工审核
    "max_sub_agents": 3,                     # 子 Agent（网页版 AI）并发上限，避免狂热申请浏览器实例
    "playwright_global_timeout": 30,        # Playwright 全局超时（秒）
    "enable_conversation_log": True,
    "enable_context_compression": True,
    "context_compression_threshold": 8000,
    "context_keep_recent": 5,
    "conversation_log_dir": "logs/conversations",
    "enable_gathering_phase": True,
    "max_gathering_rounds": 5,
    "log_file": "logs/lobster.log",
    "log_level": "INFO",
    "schedule_enabled": True,
}

WORKSPACE = Path(CONFIG["workspace"]).resolve()
WORKSPACE.mkdir(parents=True, exist_ok=True)

# ==================== 日志初始化 ====================
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)
log_path = log_dir / "lobster.log"
logging.basicConfig(
    level=getattr(logging, CONFIG.get("log_level", "INFO")),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.handlers.TimedRotatingFileHandler(log_path, when='midnight', interval=1, backupCount=30),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("lobster")

# ==================== 登录状态检查 ====================
def check_login_state():
    def check_and_login(name, url, state_file):
        if os.path.exists(state_file):
            logger.info(f"{name} 已登录")
            return True
        print(f"🔐 {name} 尚未登录，正在打开浏览器，请手动登录...")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            page = browser.new_page()
            page.goto(url)
            input(f"请完成 {name} 登录后按 Enter 继续...")
            context = page.context
            context.storage_state(path=state_file)
            browser.close()
            logger.info(f"{name} 登录状态已保存")
            return True
    logger.info("检查 AI 服务登录状态...")
    check_and_login("DeepSeek", "https://chat.deepseek.com", CONFIG["deepseek_state_file"])
    check_and_login("Kimi", "https://kimi.com", CONFIG["kimi_state_file"])
    print("✅ 所有 AI 服务登录状态正常")

# ==================== 权限管理 ====================
def load_auth_users():
    if os.path.exists(CONFIG["auth_file"]):
        with open(CONFIG["auth_file"], 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_auth_users(data):
    with open(CONFIG["auth_file"], 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def is_authorized(qq):
    data = load_auth_users()
    return qq in data and data[qq].get('enabled', False)

def add_authorized_user(qq, nickname):
    data = load_auth_users()
    data[qq] = {"nickname": nickname, "enabled": True}
    save_auth_users(data)

def remove_authorized_user(qq):
    data = load_auth_users()
    if qq in data:
        del data[qq]
        save_auth_users(data)
        return True
    return False

def list_authorized_users():
    data = load_auth_users()
    if not data:
        return "暂无授权用户"
    lines = ["已授权用户列表："]
    for qq, info in data.items():
        lines.append(f"  {qq}  ({info.get('nickname', '未命名')}) {'[启用]' if info.get('enabled', True) else '[禁用]'}")
    return "\n".join(lines)

# ==================== 永久记忆管理 ====================
class MemoryManager:
    def __init__(self, file_path="memory.json"):
        self.file_path = Path(file_path)
        self.memories = []
        self.load()

    def load(self):
        if self.file_path.exists():
            with open(self.file_path, 'r', encoding='utf-8') as f:
                self.memories = json.load(f)
        else:
            self.memories = []

    def save(self):
        with open(self.file_path, 'w', encoding='utf-8') as f:
            json.dump(self.memories, f, ensure_ascii=False, indent=2)

    def add(self, content, tags=None):
        memory = {
            "id": hashlib.md5(f"{content}{time.time()}".encode()).hexdigest()[:8],
            "content": content,
            "tags": tags or [],
            "created_at": datetime.now().isoformat()
        }
        self.memories.append(memory)
        self.save()
        return memory["id"]

    def remove(self, memory_id):
        self.memories = [m for m in self.memories if m["id"] != memory_id]
        self.save()
        return True

    def list_all(self):
        return self.memories

    def clear(self):
        self.memories = []
        self.save()

memory_manager = MemoryManager(CONFIG["memory_file"])

# ==================== 技能插件加载器 ====================
class SkillPlugin:
    def __init__(self, name, func, description="", parameters={}, enabled=True):
        self.name = name
        self.func = func
        self.description = description
        self.parameters = parameters
        self.enabled = enabled

    def execute(self, **kwargs):
        if not self.enabled:
            return f"技能 {self.name} 已禁用"
        try:
            # 漏洞6：向支持沙盒参数的技能注入当前用户上下文（uid 来自真实发送者）
            sig = inspect.signature(self.func)
            if '__uid__' in sig.parameters:
                kwargs['__uid__'] = get_current_uid()
            if '__sandbox_root__' in sig.parameters:
                kwargs['__sandbox_root__'] = str(get_sandbox_root())
            return self.func(**kwargs)
        except Exception as e:
            return f"执行技能 {self.name} 失败: {e}"

def load_skills_plugin(skills_dir="skills", config_file="skills_config.json"):
    skills = {}
    config = {}
    if os.path.exists(config_file):
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)

    skills_path = Path(skills_dir)
    if not skills_path.exists():
        return skills

    for file_path in skills_path.rglob("*"):
        if file_path.suffix == '.py':
            skill = load_py_skill(file_path, config)
            if skill:
                skills[skill.name] = skill
        elif file_path.suffix == '.md':
            skill = load_md_skill(file_path, config)
            if skill:
                skills[skill.name] = skill
    return skills

def load_py_skill(file_path, config):
    name = file_path.stem
    try:
        spec = importlib.util.spec_from_file_location(name, file_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        func = getattr(module, 'execute', None)
        if not func or not callable(func):
            return None
        desc = module.__doc__ or func.__doc__ or ""
        enabled = config.get(name, {}).get('enabled', True)
        sig = inspect.signature(func)
        params = {p.name: str(p.default) for p in sig.parameters.values() if p.default != inspect.Parameter.empty}
        return SkillPlugin(name, func, desc.strip(), params, enabled)
    except Exception as e:
        logger.error(f"加载 .py 技能 {name} 失败: {e}")
        return None

def load_md_skill(file_path, config):
    name = file_path.stem
    try:
        content = file_path.read_text(encoding='utf-8')
        frontmatter = {}
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 3:
                try:
                    frontmatter = yaml.safe_load(parts[1]) or {}
                except:
                    pass
                body = parts[2]
            else:
                body = content
        else:
            body = content

        code_match = re.search(r'```python\n(.*?)```', body, re.DOTALL)
        if not code_match:
            return None
        code = code_match.group(1).strip()

        namespace = {}
        exec(code, namespace)
        func = namespace.get('execute')
        if not func or not callable(func):
            return None

        name = frontmatter.get('name', name)
        desc = frontmatter.get('description', '')
        if not desc:
            first_para = re.split(r'\n\n', body)[0].strip()
            desc = first_para if len(first_para) < 200 else ""
        params = frontmatter.get('parameters', {})
        enabled = config.get(name, {}).get('enabled', True)

        return SkillPlugin(name, func, desc, params, enabled)
    except Exception as e:
        logger.error(f"加载 .md 技能 {name} 失败: {e}")
        return None

# ==================== AI 通信模块 ====================
def _fill_and_send(page, full_prompt, textarea_selector, send_btn_selector,
                   file_paths=None, file_input_selector=None):
    """在网页版 AI 输入框填充提示并（可选）上传附件后发送。

    附件上传原理：网页版 AI（DeepSeek/Kimi 等）通常挂一个隐藏的 <input type="file">，
    Playwright 的 set_input_files 直接把本地文件塞进该控件（无需先点上传按钮、控件可不可见都行），
    AI 服务端收到图片后会自动进行视觉理解/OCR。发送前等待片刻让附件预览就绪，避免发空附件。
    """
    page.wait_for_selector(textarea_selector)
    # 1) 先上传附件（若存在）
    if file_paths:
        files = [file_paths] if isinstance(file_paths, str) else list(file_paths)
        exist = [f for f in files if os.path.exists(f)]
        if not exist:
            logger.warning(f"附件不存在，跳过上传: {files}")
        else:
            sel = file_input_selector or "input[type=file]"
            inputs = page.locator(sel)
            if inputs.count():
                inputs.first.set_input_files(exist)
                page.wait_for_timeout(CONFIG.get("file_upload_wait_ms", 2000))
            else:
                logger.warning(f"未找到文件上传控件（{sel}），跳过附件上传")
    # 2) 填提示 + 点发送
    input_box = page.locator(textarea_selector).first
    input_box.fill(full_prompt)
    send_btn = page.locator(send_btn_selector)
    if not send_btn.count():
        send_btn = page.locator("button[aria-label='发送']")
    send_btn.click()


def call_ai_web(model, messages, state_file, url, textarea_selector, send_btn_selector, answer_selector,
                file_paths=None, file_input_selector=None):
    global_timeout_ms = CONFIG.get("playwright_global_timeout", 30) * 1000
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=CONFIG["headless"])
        context = browser.new_context()
        if os.path.exists(state_file):
            context = browser.new_context(storage_state=state_file)
        else:
            page = context.new_page()
            page.goto(url)
            if page.locator("text=登录").count() > 0:
                print(f"请手动登录 {url}，完成后按 Enter 继续...")
                input()
                context.storage_state(path=state_file)
            page.close()
        page = context.new_page()
        page.set_default_timeout(global_timeout_ms)
        # 构建完整提示
        if isinstance(messages, list):
            full_prompt = "\n".join([f"{m['role']}: {m['content']}" for m in messages])
        else:
            full_prompt = messages
        try:
            page.goto(url)
            _fill_and_send(page, full_prompt, textarea_selector, send_btn_selector, file_paths, file_input_selector)
            page.wait_for_selector("text=停止生成", state="detached", timeout=120000)
            answers = page.locator(answer_selector)
            reply = answers.last.inner_text()
            browser.close()
            return reply
        except Exception as e:
            # 漏洞2：全局超时兜底，重载页面重试一次（保留 cookie 与 localStorage 登录态）
            logger.warning(f"[{model}] 页面操作异常/超时，重载浏览器会话: {e}")
            try:
                # 先保存当前登录态（cookie + localStorage），避免重载后跳登录页
                try:
                    context.storage_state(path=state_file)
                except Exception as se:
                    logger.warning(f"[{model}] 保存 storage_state 失败: {se}")
                # 用保留的 storage_state 重建 context，确保重试后仍在登录态
                if os.path.exists(state_file):
                    context = browser.new_context(storage_state=state_file)
                else:
                    context = browser.new_context()
                page = context.new_page()
                page.set_default_timeout(global_timeout_ms)
                page.evaluate('console.log("页面正在恢复")')
                page.wait_for_timeout(1000)
                page.goto(url)
                _fill_and_send(page, full_prompt, textarea_selector, send_btn_selector, file_paths, file_input_selector)
                page.wait_for_selector("text=停止生成", state="detached", timeout=120000)
                answers = page.locator(answer_selector)
                reply = answers.last.inner_text()
                browser.close()
                logger.info(f"[{model}] 浏览器会话已重置并成功重试")
                return reply
            except Exception as e2:
                try:
                    browser.close()
                except Exception:
                    pass
                logger.error(f"[{model}] 重试后仍失败: {e2}")
                return f"[{model}] 调用失败（会话已重置仍超时）: {e2}"

def call_deepseek(messages):
    """调用 DeepSeek（主决策者）"""
    return call_ai_web(
        'DeepSeek',
        messages,
        CONFIG["deepseek_state_file"],
        "https://chat.deepseek.com",
        "textarea",
        "button:has-text('发送')",
        ".ds-markdown"
    )

def call_kimi(prompt):
    """调用 Kimi（视觉专家 / 审查助手）"""
    return call_ai_web(
        'Kimi',
        prompt,
        CONFIG["kimi_state_file"],
        "https://kimi.com",
        "textarea",
        "button:has-text('发送')",
        ".markdown"
    )

# ==================== 网页版 AI 提供方（可扩展 Agent 池） ====================
# 主脑可通过 web_ai_agent 调度任意网页版 AI 作为子 Agent。
# 新增 AI：复制一项，填对 url 与页面选择器即可（选择器需按实际页面结构调整）。
WEB_AI_PROVIDERS = {
    'deepseek': {
        'url': 'https://chat.deepseek.com',
        'textarea': 'textarea',
        'send_btn': "button:has-text('发送')",
        'answer': '.ds-markdown',
        'state_file': 'deepseek_state.json',
        'file_input': "input[type=file]",
    },
    'kimi': {
        'url': 'https://kimi.com',
        'textarea': 'textarea',
        'send_btn': "button:has-text('发送')",
        'answer': '.markdown',
        'state_file': 'kimi_state.json',
        'file_input': "input[type=file]",
    },
    # 示例：其他网页版 AI（按实际页面结构调整选择器后取消注释即可）
    # 'qwen': {
    #     'url': 'https://tongyi.aliyun.com/qianwen',
    #     'textarea': 'textarea',
    #     'send_btn': "button:has-text('发送')",
    #     'answer': '.markdown',
    #     'state_file': 'qwen_state.json',
    # },
}

def web_ai_agent(provider='deepseek', prompt='', system=None, image_path=None, file_paths=None):
    """调度指定网页版 AI 作为子 Agent 回答问题（主脑可调用的新 skill）。

    支持传图片/文件：image_path 或 file_paths（列表）会被上传给网页版 AI，由其自动视觉理解/OCR。
    """
    cfg = WEB_AI_PROVIDERS.get(provider)
    if not cfg:
        available = ', '.join(WEB_AI_PROVIDERS.keys())
        return f"未知 AI 提供方: {provider}，当前可用: {available}"
    messages = []
    if system:
        messages.append({'role': 'system', 'content': system})
    messages.append({'role': 'user', 'content': prompt})
    files = list(file_paths) if file_paths else []
    if image_path:
        files.append(image_path)
    return call_ai_web(
        provider, messages, cfg['state_file'],
        cfg['url'], cfg['textarea'], cfg['send_btn'], cfg['answer'],
        file_paths=files or None,
        file_input_selector=cfg.get('file_input'),
    )

# ==================== 子 Agent 并发调度器（LobsterScheduler） ====================
# 控制同时拉起的网页版 AI / 浏览器实例数量，避免狂热申请浏览器实例。
# 采用「常驻消费者线程 + 线程池」实现（与本项目同步 Playwright 栈一致，
# 不引入第二套事件循环），并发上限由 ThreadPoolExecutor 把守。
_SENTINEL = object()

class LobsterScheduler:
    """并发受限的子 Agent 调度器。

    - 队列无界，submit 永不阻塞（契合“绝不阻塞”诉求）。
    - 单一常驻消费者线程从队列取任务并派发到线程池，杜绝消费者协程 fan-out。
    - 并发硬上限由 ThreadPoolExecutor(max_workers) 把守；取不到任务不占槽位，无幽灵 worker。
    - run_sub_agent 异常被隔离并记录行为指纹，绝不静默消失。
    - 支持 task_done() / shutdown() 做优雅关闭。
    """
    def __init__(self, max_workers: int = 3):
        self._max_workers = max_workers
        self._queue = queue.Queue()                      # 默认无界：put 永不阻塞
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix='lobster-sub'
        )
        self._shutdown = threading.Event()
        self._consumer = threading.Thread(target=self._process_queue, daemon=True)
        self._consumer.start()

    def submit(self, task_payload):
        """提交一个子 Agent 任务。队列无界，永不阻塞。"""
        if self._shutdown.is_set():
            raise RuntimeError("scheduler 已关闭，拒绝新任务")
        self._queue.put(task_payload)

    def _process_queue(self):
        # 单一常驻消费者：阻塞取任务并派发到线程池；收到哨兵即退出。
        while True:
            task = self._queue.get()
            if task is _SENTINEL:
                self._queue.task_done()
                break
            self._executor.submit(self._run_guarded, task)

    def _run_guarded(self, task):
        try:
            run_sub_agent(task)
        except Exception as exc:
            logger.error(f"[LobsterScheduler] 子 Agent 执行失败: {exc}")
            try:
                log_behavior_fingerprint(
                    uid=task.get('uid') if isinstance(task, dict) else None,
                    op='sub_agent_error', command=str(exc)[:200],
                )
            except Exception:
                pass
        finally:
            self._queue.task_done()

    def shutdown(self, grace: float = 30.0):
        """停止接收新任务并等待在途子 Agent 完成。"""
        self._shutdown.set()
        self._queue.put(_SENTINEL)
        self._executor.shutdown(wait=True)        # 等待在途子 Agent 完成（run_sub_agent 自带 30s 超时兜底）
        if self._consumer.is_alive():
            self._consumer.join(timeout=grace)


def run_sub_agent(task):
    """执行一个子 Agent 任务：内部复用 web_ai_agent 拉起网页版 AI，并把结果回传触发会话。"""
    provider = (task or {}).get('provider', 'deepseek')
    prompt = (task or {}).get('prompt', '')
    system = (task or {}).get('system')
    image_path = (task or {}).get('image_path')
    file_paths = (task or {}).get('file_paths') or []
    answer = web_ai_agent(provider=provider, prompt=prompt, system=system,
                          image_path=image_path, file_paths=file_paths)
    # 结果路由：其他用户触发的 → 回传该用户会话；主脑(admin)触发的 → 回传主脑会话。
    # 二者统一为「回传到提交任务时记录的触发 identifier」，由 execute_agent_loop 在工作线程内写入。
    identifier = task.get('identifier')
    if identifier and answer and GLOBAL_SOURCE is not None:
        try:
            GLOBAL_SOURCE.send_reply(identifier, f"🤖 [{provider}] 子 Agent 回复：\n{truncate_text(answer)}")
        except Exception as exc:
            logger.error(f"[LobsterScheduler] 回传子 Agent 结果失败: {exc}")
    return answer


def dispatch_sub_agent(provider='deepseek', prompt='', system=None, image_path=None, file_paths=None):
    """非阻塞地把子 Agent 任务交给 LobsterScheduler（供主脑提示词触发）。

    支持附图/附件：image_path 或 file_paths 会随任务上传给网页版 AI 做视觉理解/OCR。
    触发会话标识（identifier）在提交时从当前上下文捕获，子 Agent 完成后据此回传：
    - 由其他用户消息触发 → 结果回传该用户；
    - 由主脑(admin)自身触发 → 结果回传主脑会话。
    """
    lobster_scheduler.submit({
        'provider': provider, 'prompt': prompt, 'system': system,
        'uid': get_current_uid(), 'identifier': get_current_identifier(),
        'image_path': image_path, 'file_paths': file_paths,
    })
    return f"✅ 已提交子 Agent 任务（provider={provider}），由调度器并发执行（上限 {lobster_scheduler._max_workers}），完成后将回传至触发会话。"


# 全局调度器实例（并发上限取 CONFIG.max_sub_agents）
lobster_scheduler = LobsterScheduler(max_workers=CONFIG.get('max_sub_agents', 3))

# 供调度线程回传子 Agent 结果到触发会话（在 main() 中绑定为当前 NapCatSource）
GLOBAL_SOURCE = None

# ==================== 安全防护（漏洞加固） ====================

# 漏洞1：高危命令黑名单（第一层，正则匹配关机/格式化/删盘/改启动项等）
DANGEROUS_COMMAND_PATTERNS = [
    # 高危动作关键词
    r'\bshutdown\b', r'\breboot\b', r'\bstop-computer\b', r'\brestart-computer\b',
    r'\bformat\b', r'\bdiskpart\b', r'\bfdisk\b', r'\bmkfs\b',
    r'\bdel\b.*[\\/]system32', r'\brm\s+-rf\s+/', r'\bdeltree\b',
    r'\bbcdedit\b', r'\breg\s+(add|delete)\b.*\b(run|runonce|autostart|boot)\b',
    r'\bwmic\b.*\bdelete\b', r'\bremove-item\b.*\bsystem\b',
    r'\bdd\s+if=.*of=/dev/(sd|nvme|hd|vd)',
    # 二次执行入口（拼接/绕过载体，如 cmd /c shutdown）
    r'\bcmd(\.exe)?\s+/[ck]\b',
    r'\bpowershell(\.exe)?\b[^\r\n]*-(c|command|enc|encodedcommand)\b',
    r'\bbash\s+-c\b', r'\bsh\s+-c\b',
    r'\bwscript(\.exe)?\b', r'\bcscript(\.exe)?\b', r'\bmshta(\.exe)?\b',
    # 元字符注入 / 命令替换 / 命令链连续使用
    r'\$\s*\(', r'`[^`]*`', r';\s*;', r'&&', r'\|\|',
]

def truncate_text(text, max_chars=None):
    """漏洞4：本地硬截断，优先在换行符处截断，避免生切代码行导致语法错误"""
    if not text:
        return text
    limit = max_chars or CONFIG.get("max_message_chars", 3000)
    if len(text) <= limit:
        return text
    # 在 limit 之前找最近的换行符，尽量在完整行边界截断
    window = text[:limit]
    cut = window.rfind('\n')
    if cut > limit * 0.5:
        head = text[:cut]
    else:
        head = text[:limit]
    return head + f"\n... [内容过长已截断，原长度 {len(text)} 字]"

def normalize_newlines(text):
    """漏洞5：统一换行符为 \\n，避免 Windows \\r\\n 在 Linux 下 command not found"""
    if not text:
        return text
    return text.replace('\r\n', '\n').replace('\r', '\n')

# 漏洞6：协程/线程级用户上下文（uid 来自真实消息发送者，非任意传入字符串）
# 用 contextvars 而非 threading.local：Playwright 运行在异步事件循环下，同一线程内多个协程会并发切换，
# threading.local 无法隔离协程级上下文，contextvars 才是异步模式下的“线程本地存储”替代品。
_actor_uid = contextvars.ContextVar('lobster_uid', default='shared')
_actor_msgtype = contextvars.ContextVar('lobster_msgtype', default='private')
_actor_group = contextvars.ContextVar('lobster_group', default=None)
_actor_identifier = contextvars.ContextVar('lobster_identifier', default=None)

def set_current_message(msg):
    """设置当前正在处理的消息上下文（contextvars 隔离，兼容 Playwright 异步事件循环）"""
    _actor_uid.set(str(msg.get('sender_id', '') or 'shared'))
    _actor_msgtype.set(msg.get('message_type', 'private'))
    _actor_group.set(str(msg.get('group_id')) if msg.get('group_id') else None)
    _actor_identifier.set(msg.get('identifier'))   # 触发会话标识，供子 Agent 结果回传

def get_current_uid():
    """获取当前操作用户 UID（真实发送者，未设置时回退 shared）"""
    return _actor_uid.get() or 'shared'

def get_current_identifier():
    """获取当前触发会话标识符（用于把子 Agent 结果回传给正确的会话）"""
    return _actor_identifier.get()

def get_sandbox_root():
    """当前用户沙盒根：私聊 workspace/{uid}/，群聊 workspace/group_{gid}/{uid}/"""
    uid = get_current_uid()
    msg_type = _actor_msgtype.get()
    group_id = _actor_group.get()
    if msg_type == 'group' and group_id:
        return WORKSPACE / f"group_{group_id}" / uid
    return WORKSPACE / uid

def sandbox_path_check(path, uid=None, sandbox_root=None):
    """漏洞6：路径沙盒校验，文件路径必须位于当前用户的沙盒根内"""
    try:
        base = Path(sandbox_root).resolve() if sandbox_root else get_sandbox_root().resolve()
        resolved = Path(path).resolve()
        if str(resolved) == str(base) or str(resolved).startswith(str(base) + os.sep):
            return True, ""
        return False, f"路径越权：{path} 不在沙盒 {base} 内"
    except Exception as e:
        return False, f"路径校验失败: {e}"

def semantic_danger_check(command):
    """漏洞1：Kimi 操作意图语义鉴定（第二层）。返回 (是否放行, 原因)"""
    try:
        prompt = (
            "你是安全审查员。判断下面这条命令是否存在高危操作意图"
            "（关机/重启、格式化磁盘、删除系统文件、修改系统启动项、破坏系统等）。"
            f"只回答两个字「通过」或「高危」，不要解释。\n命令：{command}"
        )
        review = call_kimi(prompt)
        if any(k in review for k in ("高危", "不通过", "DANGER", "FAIL")):
            return False, review.strip()[:120]
        return True, ""
    except Exception as e:
        logger.warning(f"语义鉴定失败，按黑名单结果放行: {e}")
        return True, ""

def guard_command(command):
    """漏洞1：命令执行统一防护入口。返回 (是否放行, 拦截原因)"""
    cmd = normalize_newlines(command)
    if CONFIG.get("command_guard_blacklist", True):
        low = cmd.lower()
        for pat in DANGEROUS_COMMAND_PATTERNS:
            if re.search(pat, low):
                return False, f"高危命令已拦截（命中: {pat}）"
    # 仅高危操作触发 Kimi 语义鉴定（降本增效：低风险指令直接放行，省去一轮 AI 调用）
    if CONFIG.get("command_guard_semantic", True) and classify_operation_risk(cmd) == 'high':
        ok, reason = semantic_danger_check(cmd)
        if not ok:
            return False, f"高危操作不通过：{reason}"
    return True, ""

# ==================== 意图等级分类（降本增效：仅高危操作触发 Kimi 双AI审查） ====================
HIGH_RISK_OP_PATTERNS = [
    # 网络修改
    r'\b(netsh|iptables|ufw|firewalld|route\s+add|ip\s+route\s+add|crontab\s+-)\b',
    r'\b(set-netfirewallrule|new-netfirewallrule|add-netfirewallrule|remove-netfirewallrule)\b',
    # 文件权限
    r'\b(chmod|chown|chattr|icacls|attrib\s+[+-]|set-acl)\b',
    # 系统命令执行 / 磁盘 / 进程服务
    r'\b(shutdown|reboot|halt|poweroff|format|diskpart|mkfs|fdisk|del\s+/[fq]|sdelete|rm\s+-rf|schtasks|sc\s+create|net\s+(stop|start|user)|systemctl|service\s+\w+\s+(stop|start|restart)|taskkill|kill\s+-9|pkill|Stop-Computer|Restart-Computer)\b',
    # 注册表 / 启动项 / 持久化
    r'\b(bcdedit|reg\s+(add|delete)|update-rc\.d|systemctl\s+enable)\b',
    # 磁盘数据破坏
    r'\b(dd\s+if=|wipefs|shred\s+)\b',
    # 用户 / 权限
    r'\b(useradd|adduser|usermod|passwd|net\s+user|sudo)\b',
    # 下载即执行（夹带私货的高危载体）
    r'(curl|wget|iwr|invoke-webrequest).*(\|\s*(sh|bash|pwsh|powershell|iex)|downloadstring|clipsex)',
    r'\b(invoke-expression|iex)\b',
    # 注册表持久化路径
    r'\b(HKLM|HKCU)\\',
]

def classify_operation_risk(text):
    """意图等级分类：检测高危操作（网络修改/文件权限/系统命令/磁盘/注册表/用户权限/下载即执行）。
    命中任一高危模式返回 'high'，否则返回 'low'（写UI、读普通文本等低风险操作直接放行，不触发 Kimi 双AI审查）。"""
    if not text:
        return 'low'
    low = text.lower()
    for pat in HIGH_RISK_OP_PATTERNS:
        if re.search(pat, low):
            return 'high'
    return 'low'

# ==================== 动态行为指纹日志（在既有安全补丁之上再加一层异常行为雷达） ====================
_behavior_counter = {}  # uid -> 连续长指令计数

def log_behavior_fingerprint(uid, action, command, cwd=None, env=None):
    """记录命令执行的动态行为指纹（cwd/env/命令/uid），并对连续长指令做人工审核阈值检测。
    防止 AI 在大量正常指令中夹带私货——一旦某 uid 连续 N 次发出超长指令，触发人工审核。"""
    fp = {
        "ts": datetime.now().isoformat(timespec='seconds'),
        "uid": uid,
        "action": action,
        "command": command[:500],
        "cwd": str(cwd) if cwd else os.getcwd(),
        "env_keys": sorted(env.keys()) if env else "inherited",
    }
    logger.info(f"[行为指纹] {json.dumps(fp, ensure_ascii=False)}")
    # 连续长指令阈值检测
    threshold = CONFIG.get("long_command_chars", 200)
    if len(command) > threshold:
        _behavior_counter[uid] = _behavior_counter.get(uid, 0) + 1
    else:
        _behavior_counter[uid] = 0
    if _behavior_counter[uid] >= CONFIG.get("long_command_review_threshold", 3):
        logger.warning(f"[行为指纹] uid={uid} 连续 {_behavior_counter[uid]} 次长指令，触发人工审核！")
        _behavior_counter[uid] = 0  # 重置，避免重复告警风暴
        return True  # 需要人工审核
    return False

# ==================== 视觉操作（Kimi 视觉专家） ====================
def builtin_screen_ops(action, target=None, use_kimi_vision=False, **kwargs):
    """屏幕操作：点击、输入、OCR等，支持 Kimi 视觉辅助（截图会真实上传给 Kimi 网页版）"""
    if use_kimi_vision:
        # 截屏
        screenshot = pyautogui.screenshot()
        temp_path = WORKSPACE / f"_vision_{int(time.time())}.png"
        screenshot.save(temp_path)
        # 调用 Kimi 分析：改走 web_ai_agent 并上传截图，让 Kimi 真正"看到"图片。
        # 旧的 call_kimi(vision_prompt) 只发文本、Kimi 收不到图，视觉分析实际上从未生效。
        vision_prompt = f"""请分析这张截图，并执行以下任务：
动作：{action}
目标：{target}
附加信息：{kwargs}

返回 JSON 格式操作指令：
{{"actions": [{{"type": "click|type|scroll|wait|ocr", "x": 123, "y": 456, "text": "输入内容"}}]}}
只输出 JSON，不要额外文字。"""
        kimi_response = web_ai_agent(provider='kimi', prompt=vision_prompt, image_path=str(temp_path))
        try:
            # 稳健提取：Kimi 网页版可能用 ```json 包裹，取首个 {{...}} 块解析
            _m = re.search(r'\{.*\}', kimi_response, re.DOTALL)
            instructions = json.loads(_m.group() if _m else kimi_response)
        except Exception:
            return f"Kimi 视觉分析失败: {kimi_response[:200]}"
        # 执行指令
        for cmd in instructions.get('actions', []):
            if cmd['type'] == 'click':
                pyautogui.click(cmd.get('x', 0), cmd.get('y', 0))
            elif cmd['type'] == 'type':
                pyautogui.write(cmd.get('text', ''))
            elif cmd['type'] == 'scroll':
                pyautogui.scroll(cmd.get('amount', 0))
            elif cmd['type'] == 'wait':
                time.sleep(cmd.get('seconds', 1))
            elif cmd['type'] == 'ocr':
                # 识别文字（需要 pytesseract）
                try:
                    import pytesseract
                    text = pytesseract.image_to_string(Image.open(temp_path))
                    return f"OCR 识别结果: {text[:500]}"
                except:
                    return "OCR 未安装 pytesseract"
        return "UI 操作完成"
    else:
        # 简单非视觉操作（如截图保存）
        if action == 'screenshot':
            path = kwargs.get('path', WORKSPACE / f"screenshot_{int(time.time())}.png")
            pyautogui.screenshot().save(path)
            return f"截图已保存至 {path}"
        elif action == 'locate':
            # 使用图像匹配查找位置
            try:
                pos = pyautogui.locateCenterOnScreen(target)
                return f"找到 {target} 位置: {pos}"
            except:
                return f"未找到 {target}"
        else:
            return f"不支持的操作: {action}"

def builtin_screenshot(path=None, save_path=None, **kwargs):
    """内置操作：屏幕截图并保存到沙盒工作区（独立封装，仅负责截图落盘）。

    与 builtin_screen_ops 的视觉分析路径解耦——本函数只做"截图 + 保存"，不做 OCR/视觉识别。
    - path / save_path: 保存路径；缺省落到 WORKSPACE/screenshot_<时间戳>.png
    - 多余字段(action/target/use_kimi_vision 等)由 **kwargs 吸收，保证与 builtin(**args) 调用约定兼容
    - 需要视觉理解请走 builtin(op='screen_ops', args={'action':'screenshot','use_kimi_vision':True})
    截图属敏感操作，执行会写入行为指纹日志。
    """
    # 行为指纹（截图留痕，便于审计谁截了屏）
    log_behavior_fingerprint(get_current_uid(), 'screenshot', str(path or save_path or 'default'),
                             cwd=os.getcwd(), env=os.environ)
    save_to = path or save_path or (WORKSPACE / f"screenshot_{int(time.time())}.png")
    try:
        pyautogui.screenshot().save(save_to)
    except Exception as e:
        return f"截图失败: {e}"
    return f"截图已保存至 {save_to}"

# ==================== 内置操作 ====================
def builtin_install_software(name, mode='winget', install_location='D:\\Software', script_code=None):
    if mode == 'winget':
        Path(install_location).mkdir(parents=True, exist_ok=True)
        cmd = normalize_newlines(f'winget install --accept-package-agreements --install-location "{install_location}" "{name}"')
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=180)
            if result.returncode == 0:
                return f"软件 {name} 已成功安装至 {install_location}"
            else:
                return f"winget 安装失败: {result.stderr}\n提示：可尝试 mode='script' 并提供安装脚本。"
        except Exception as e:
            return f"安装异常: {e}"
    elif mode == 'script' and script_code:
        tmp_script = Path(WORKSPACE) / f"_install_{name}_{int(time.time())}.py"
        with open(tmp_script, 'w', encoding='utf-8') as f:
            f.write(normalize_newlines(script_code))
        # 动态行为指纹日志
        log_behavior_fingerprint(get_current_uid(), 'install_script', script_code[:2000], cwd=str(tmp_script.parent), env=os.environ)
        try:
            result = subprocess.run(['python', str(tmp_script)], capture_output=True, text=True, timeout=300)
            tmp_script.unlink()
            if result.returncode == 0:
                return f"脚本安装成功：\n{result.stdout}"
            else:
                return f"脚本安装失败：\n{result.stderr}"
        except Exception as e:
            return f"执行安装脚本异常: {e}"
    else:
        return "无效的安装模式或缺少脚本代码"

def builtin_open_app(path):
    # 动态行为指纹日志
    log_behavior_fingerprint(get_current_uid(), 'open_app', path, cwd=os.getcwd(), env=os.environ)
    try:
        subprocess.Popen([normalize_newlines(path)], shell=True)
        return f"已打开 {path}"
    except Exception as e:
        return f"打开失败: {e}"

def builtin_system_info():
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
        if not info_lines:
            lines = output.splitlines()
            for i, line in enumerate(lines):
                if ':' in line and i < 15:
                    info_lines.append(line.strip())
        return "\n".join(info_lines[:8])
    except Exception as e:
        return f"获取系统信息失败: {e}"

def builtin_browser(action, **kwargs):
    try:
        with sync_playwright() as p:
            headless = kwargs.get('headless', False)
            browser = p.chromium.launch(headless=headless)
            page = browser.new_page()
            result = None
            if action == 'goto':
                page.goto(kwargs['url'])
                result = f"已打开 {kwargs['url']}"
            elif action == 'screenshot':
                page.goto(kwargs['url'])
                path = kwargs.get('path', f'workspace/screenshot_{int(time.time())}.png')
                page.screenshot(path=path)
                result = f"截图已保存至 {path}"
            elif action == 'click':
                page.goto(kwargs['url'])
                page.click(kwargs['selector'])
                result = f"已点击 {kwargs['selector']}"
            elif action == 'fill':
                page.goto(kwargs['url'])
                page.fill(kwargs['selector'], kwargs['text'])
                result = f"已填写 {kwargs['selector']}"
            elif action == 'evaluate':
                page.goto(kwargs['url'])
                res = page.evaluate(kwargs['script'])
                result = f"执行结果: {res}"
            elif action == 'html':
                page.goto(kwargs['url'])
                html = page.content()
                result = html[:5000]
            else:
                result = f"未知操作 {action}"
            browser.close()
            return result
    except Exception as e:
        return f"浏览器操作失败: {e}"

def builtin_help():
    lines = ["🦞 小龙虾命令帮助", "=" * 30]
    lines.append("\n📌 可用命令（以 # 开头）：")
    lines.append("  #help               - 显示此帮助")
    lines.append("  #status             - 显示系统状态")
    lines.append("  #skills_list        - 列出所有可用技能")
    lines.append("  #skills <名> [参数] - 调用技能")
    lines.append("  #exec <命令>        - 一次性执行命令（Win+R 风格，无回显）")
    lines.append("  #tools <shell>      - 启动交互式 Shell (cmd/powershell/python)")
    lines.append("  #tools <shell> <命令> - 在 Shell 中执行命令（有回显）")
    lines.append("  #auth add <qq> <昵称>  - 添加授权用户（仅管理员）")
    lines.append("  #auth remove <qq>     - 删除授权用户（仅管理员）")
    lines.append("  #auth list            - 列出所有授权用户（仅管理员）")
    lines.append("  #memory add <内容>    - 添加永久记忆（仅管理员）")
    lines.append("  #memory remove <id>   - 删除记忆（仅管理员）")
    lines.append("  #memory list          - 列出所有记忆（仅管理员）")
    lines.append("  #memory clear         - 清空记忆（仅管理员）")
    lines.append("  #schedule add <cron> <命令> - 添加定时任务（仅管理员）")
    lines.append("  #schedule list        - 列出定时任务（仅管理员）")
    lines.append("  #schedule remove <id> - 删除定时任务（仅管理员）")
    lines.append("\n🔧 已启用技能：")
    for name, skill in SKILLS.items():
        params_str = ', '.join(skill.parameters.keys()) if skill.parameters else '无'
        lines.append(f"  {name}  - {skill.description or '无描述'} (参数: {params_str})")
    lines.append("\n⚙️ 内置操作（可通过 #skills 调用）：")
    for op in BUILTIN_OPS:
        lines.append(f"  {op}")
    return "\n".join(lines)

BUILTIN_OPS = {
    'install_software': builtin_install_software,
    'open_app': builtin_open_app,
    'system_info': builtin_system_info,
    'screenshot': builtin_screenshot,
    'browser': builtin_browser,
    'screen_ops': builtin_screen_ops,
    'help': builtin_help,
}

# ==================== 定时任务 ====================
class Scheduler:
    def __init__(self):
        self.tasks = {}
        self._running = False
        self._thread = None

    def add_task(self, task_id, cron_expr, command):
        """添加定时任务，cron_expr格式: 'min hour day month day_of_week'"""
        # 简化：使用schedule库
        schedule.clear(task_id)
        schedule.every().day.at("10:30").do(self._execute, command)  # 示例，实际需解析cron
        self.tasks[task_id] = {"cron": cron_expr, "command": command}
        return True

    def remove_task(self, task_id):
        schedule.cancel_job(task_id)
        if task_id in self.tasks:
            del self.tasks[task_id]
        return True

    def list_tasks(self):
        return self.tasks

    def _execute(self, command):
        # 在QQ中执行命令（需注入消息源）
        pass

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self):
        while self._running:
            schedule.run_pending()
            time.sleep(1)

scheduler = Scheduler()

# ==================== 交互式 Shell 会话管理 ====================
sessions = {}

def get_session(identifier, shell_type):
    if identifier in sessions:
        return sessions[identifier].get(shell_type)
    return None

def set_session(identifier, shell_type, session):
    if identifier not in sessions:
        sessions[identifier] = {}
    sessions[identifier][shell_type] = session

def remove_session(identifier, shell_type):
    if identifier in sessions and shell_type in sessions[identifier]:
        del sessions[identifier][shell_type]
        if not sessions[identifier]:
            del sessions[identifier]

def start_shell(identifier, shell_type):
    if shell_type not in ['cmd', 'powershell', 'python']:
        return "不支持的 Shell，可选: cmd, powershell, python"

    existing = get_session(identifier, shell_type)
    if existing:
        try:
            existing['process'].terminate()
            existing['process'].wait(timeout=2)
        except:
            pass
        remove_session(identifier, shell_type)

    if shell_type == 'cmd':
        args = ['cmd.exe']
    elif shell_type == 'powershell':
        args = ['powershell.exe', '-NoLogo', '-Command', '-']
    else:
        args = ['python.exe', '-i']

    proc = subprocess.Popen(
        args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding='gbk' if shell_type in ['cmd', 'powershell'] else 'utf-8',
        creationflags=subprocess.CREATE_NO_WINDOW
    )

    output_queue = queue.Queue()

    def reader_thread():
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            output_queue.put(line)
    threading.Thread(target=reader_thread, daemon=True).start()

    session = {
        'process': proc,
        'output_queue': output_queue,
        'shell_type': shell_type
    }
    set_session(identifier, shell_type, session)

    time.sleep(0.5)
    init_output = []
    while not output_queue.empty():
        init_output.append(output_queue.get_nowait())
    return f"已启动 {shell_type} 会话。\n" + ''.join(init_output)

def send_to_shell(identifier, shell_type, command):
    session = get_session(identifier, shell_type)
    if not session:
        return f"没有活动的 {shell_type} 会话，请先使用 #tools {shell_type} 启动。"

    proc = session['process']
    output_queue = session['output_queue']

    # 动态行为指纹日志（连续长指令人工审核阈值，详见 log_behavior_fingerprint）
    log_behavior_fingerprint(get_current_uid(), 'shell_write', command, cwd=os.getcwd(), env=os.environ)
    try:
        proc.stdin.write(normalize_newlines(command) + '\n')
        proc.stdin.flush()
    except Exception as e:
        return f"写入命令失败: {e}"

    time.sleep(0.5)
    output_lines = []
    while not output_queue.empty():
        try:
            line = output_queue.get_nowait()
            output_lines.append(line)
        except queue.Empty:
            break
    if not output_lines:
        time.sleep(1)
        while not output_queue.empty():
            try:
                line = output_queue.get_nowait()
                output_lines.append(line)
            except queue.Empty:
                break

    return ''.join(output_lines) if output_lines else "命令已执行，无输出（可能正在运行或已退出）。"

# ==================== NapCat 消息源 ====================
class NapCatSource:
    def __init__(self):
        self.ws_url = CONFIG["napcat_ws"]
        self.http_url = CONFIG["napcat_http"]
        self.msg_queue = queue.Queue()
        self._running = False
        self._thread = None
        self.histories = {}

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._ws_loop, daemon=True)
        self._thread.start()

    def _ws_loop(self):
        while self._running:
            try:
                with websockets.connect(self.ws_url) as ws:
                    while self._running:
                        try:
                            raw = ws.recv(timeout=1)
                            data = json.loads(raw)
                            self._process_event(data)
                        except TimeoutError:
                            continue
                        except Exception as e:
                            logger.error(f"WebSocket 接收错误: {e}")
            except Exception as e:
                logger.error(f"WebSocket 连接失败，5秒后重试: {e}")
                time.sleep(5)

    def _process_event(self, data):
        if data.get('post_type') == 'message':
            self._handle_message(data)

    def _handle_message(self, data):
        msg_type = data.get('message_type')
        sender = data.get('sender', {})
        user_id = str(sender.get('user_id', ''))
        nickname = sender.get('nickname', '未知')
        raw_message = data.get('raw_message', '')
        message = re.sub(r'\[CQ:[^\]]+\]', '', raw_message).strip()
        if not user_id or not message:
            return
        group_id = None
        if msg_type == 'private':
            identifier = f"private_{user_id}"
        elif msg_type == 'group':
            group_id = str(data.get('group_id', ''))
            identifier = f"group_{group_id}"
            if CONFIG["only_mention"]:
                at_self = False
                for segment in data.get('message', []):
                    if segment.get('type') == 'at' and str(segment.get('data', {}).get('qq', '')) == 'self':
                        at_self = True
                        break
                if not at_self:
                    return
        else:
            return
        msg = {
            'sender_id': user_id,
            'sender_nick': nickname,
            'content': message,
            'identifier': identifier,
            'message_type': msg_type,
            'group_id': group_id,
        }
        self.msg_queue.put(msg)

    def get_new_messages(self):
        msgs = []
        while not self.msg_queue.empty():
            msgs.append(self.msg_queue.get_nowait())
        return msgs

    def send_reply(self, identifier, text):
        if identifier.startswith('private_'):
            user_id = identifier.split('_', 1)[1]
            url = f"{self.http_url}/send_private_msg"
            payload = {"user_id": int(user_id), "message": text}
        elif identifier.startswith('group_'):
            group_id = identifier.split('_', 1)[1]
            url = f"{self.http_url}/send_group_msg"
            payload = {"group_id": int(group_id), "message": text}
        else:
            return False
        try:
            resp = requests.post(url, json=payload, timeout=5)
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"发送消息异常: {e}")
            return False

    def get_history(self, identifier):
        if identifier not in self.histories:
            self.histories[identifier] = deque(maxlen=CONFIG["context_limit"])
        return self.histories[identifier]

# ==================== 系统提示生成 ====================
def build_system_prompt():
    skill_desc = "\n".join([
        f"- {name}({', '.join([f'{k}: {v}' for k, v in skill.parameters.items()])}) : {skill.description}"
        for name, skill in SKILLS.items()
    ])
    builtin_desc = "\n".join([f"- builtin(op='{op}', args={{...}}) : {BUILTIN_OPS[op].__doc__ or ''}" for op in BUILTIN_OPS])
    
    # 注入永久记忆
    memories = memory_manager.list_all()
    memory_text = ""
    if memories:
        memory_text = "\n【永久记忆】\n" + "\n".join([f"- {m['content']}" for m in memories]) + "\n"

    prompt = f"""你是一个AI助手，与本地脚本协同工作。你可以调用技能、内置操作或自然对话完成任务。
{memory_text}
可用技能：
{skill_desc}

内置操作：
{builtin_desc}

特殊技能：
- write_skill(name, description, parameters, code, base_skill=None) : 创建新技能，代码将自动经过双AI审查。

【任务复杂度评估】
在收到用户消息后，先进行复杂度评估（内部）：
- 简单任务：无需额外信息，直接执行（输出 finish 或调用技能）。
- 中等任务：需要部分澄清，使用 ask_user 提问 1-2 个关键问题。
- 复杂任务：需要完整信息收集，逐步提问。
评估标准：参数数量、外部依赖、用户偏好。

【信息收集阶段】
如果缺少必要信息，你应该进入信息收集阶段：
1. 列出所有需要确认的信息点。
2. 依次通过 ask_user 向用户提问，每次只问一个核心问题。
3. 用户回复后，记录答案并继续下一个问题，直到所有信息完整。
4. 信息收集完成后，输出一个总结并询问用户是否确认。

【ask_user 用法】
当需要向用户提问时，输出：
{{"action": "ask_user", "params": {{"question": "您的具体问题", "options": ["选项A", "选项B"]}}}}

【与Kimi协作（视觉专家）】
当任务需要操作屏幕上的图形界面（如点击按钮、输入文本、识别窗口）时，请调用 screen_ops 并设置 use_kimi_vision=True，Kimi 会作为视觉专家提供精确的坐标和操作指令。

【调度其他 AI 作为子 Agent】
你可以使用 web_ai_agent 技能打开其他网页版 AI 作为子 Agent 辅助完成任务：
- 当需要第二意见、交叉验证、或让其他模型独立完成某个子任务时，调用 web_ai_agent。
- 用法示例：{{"action": "web_ai_agent", "params": {{"provider": "kimi", "prompt": "请审查这段代码..."}}}}
- provider 可选：deepseek, kimi（可在 WEB_AI_PROVIDERS 中扩展更多）。
- 注意：这是通过浏览器打开网页版 AI，每次调用较慢，仅在确实需要时使用。

你可以使用 dispatch_sub_agent 技能把多个子 Agent 任务交给 LobsterScheduler 并发调度（上限 CONFIG.max_sub_agents，默认 3）：
- 当需要一次性派发多条独立子任务、又不想同步阻塞主脑回复时，用 dispatch_sub_agent 替代 web_ai_agent。
- 用法示例：{{"action": "dispatch_sub_agent", "params": {{"provider": "deepseek", "prompt": "并行分析这 5 个日志文件..."}}}}
- 需要让子 Agent 看图/OCR：params 里加 "image_path"（单图）或 "file_paths"（多文件列表），会自动上传给网页版 AI 做视觉理解。
- 调度器自带并发上限，狂热派发也不会同时拉起超过上限的浏览器实例；失败会被隔离并记录行为指纹。
- 若需要同步拿到结果再继续，仍用 web_ai_agent。

【交互协议】
你与脚本的每一次交互都必须遵循以下格式：
- 输出必须是 JSON 对象，包含 "action" 和 "params" 字段。
- 如果任务完成或无需操作，action 为 "finish"，params 中放入回复内容。
- 如果需要调用技能或内置操作，action 为对应的名称，params 为参数字典。

【非创作状态】
即使你决定直接回复，也必须返回 JSON，例如：
{{"action": "finish", "params": {{"result": "今天天气不错，祝你好心情！"}}}}

不要输出任何非 JSON 内容，思考过程仅在内部，不要输出给用户。
"""
    return prompt

# ==================== AI 处理循环 ====================
# 挂起上下文
pending_contexts = {}

def execute_agent_loop(user_message, history, identifier, source, max_steps=5):
    # 路由上下文：线程池工作线程不会继承提交线程的 contextvars，必须在此（同一工作线程内）
    # 用 identifier 重建上下文，供 dispatch_sub_agent 回传子 Agent 结果，并修复沙盒按用户隔离。
    # identifier 形如 private_{user_id} / group_{group_id}
    if identifier and identifier.startswith('group_'):
        set_current_message({'sender_id': 'shared', 'message_type': 'group', 'group_id': identifier[6:], 'identifier': identifier})
    elif identifier and identifier.startswith('private_'):
        set_current_message({'sender_id': identifier[8:], 'message_type': 'private', 'group_id': None, 'identifier': identifier})
    else:
        set_current_message({'sender_id': 'shared', 'message_type': 'private', 'group_id': None, 'identifier': identifier})
    # 漏洞4：对每条消息做本地硬截断，避免撑爆网页端上下文
    messages = [
        {"role": m.get("role", "user"), "content": truncate_text(m.get("content", ""))}
        for m in history[-CONFIG["context_limit"]:]
    ]
    messages.append({"role": "user", "content": truncate_text(user_message)})

    # 1. 主决策者 DeepSeek 分析
    system_prompt = build_system_prompt()
    full_messages = [{"role": "system", "content": system_prompt}] + messages
    raw = call_deepseek(full_messages)

    # 解析 JSON
    try:
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not json_match:
            return "AI 响应格式错误，未找到 JSON"
        data = json.loads(json_match.group())
        action = data.get('action')
        params = data.get('params', {})
    except json.JSONDecodeError:
        return f"JSON解析失败: {raw[:200]}"

    # 2. 处理动作
    if action == 'finish':
        return params.get('result', '任务完成')
    elif action == 'ask_user':
        question = params.get('question', '请提供必要信息')
        options = params.get('options', [])
        if options:
            question += f"\n可选: {', '.join(options)}"
        source.send_reply(identifier, f"❓ {question}")
        # 保存上下文，等待用户回复
        pending_contexts[identifier] = {
            'messages': messages,
            'history': history,
            'step': 0
        }
        return None  # 挂起
    elif action == 'write_skill':
        # 执行代码生成（DeepSeek 生成）
        result = skill_write_skill(**params)
        return result
    elif action == 'builtin':
        op = params.get('op')
        args = params.get('args', {})
        if op in BUILTIN_OPS:
            return BUILTIN_OPS[op](**args)
        else:
            return f"未知内置操作: {op}"
    elif action in SKILLS:
        return SKILLS[action].execute(**params)
    else:
        return f"未知动作: {action}"

# ==================== 技能写入（含双AI审查）====================
def skill_write_skill(**kwargs):
    name = kwargs.get('name')
    description = kwargs.get('description', '')
    parameters = kwargs.get('parameters', {})
    code = kwargs.get('code', '')
    base_skill = kwargs.get('base_skill', None)

    if not name or not code:
        return "缺少技能名称或代码"

    if CONFIG.get("code_review_enabled"):
        # 降本增效：意图等级分类，仅高危操作触发 Kimi 双AI审查；写UI/读普通文本等低风险直接放行
        risk = classify_operation_risk(code)
        if risk == 'low':
            logger.info(f"[{name}] 代码意图等级=低危，跳过 Kimi 双AI审查，直接生成")
        else:
            # 漏洞3：多轮审查 + 死循环斩断，最多 max_review_rounds 轮，超限请求人工介入
            max_rounds = CONFIG.get("max_review_rounds", 5)
            current_code = code
            review_log = []          # 记录每轮分歧，便于人工介入时定位是谁的问题
            approved = False
            for round_no in range(1, max_rounds + 1):
                review_prompt = (
                    "你是代码审查员。判断以下代码是否安全可用。"
                    "只回答「通过」，或「不通过：<原因与修改建议>」。\n"
                    f"```python\n{current_code}\n```"
                )
                review = call_kimi(review_prompt)
                if "不通过" not in review and "FAIL" not in review.upper():
                    approved = True
                    code = current_code
                    break
                review_log.append(f"第 {round_no} 轮 · Kimi 否决：{review.strip()[:300]}")
                # 让 DeepSeek 按审查意见修改，进入下一轮
                fix_prompt = (
                    "根据以下审查意见修改代码，只输出完整可运行的 Python 代码，不要任何解释。\n"
                    f"审查意见：\n{review}\n\n"
                    f"原代码：\n```python\n{current_code}\n```"
                )
                fixed = call_deepseek([{"role": "user", "content": fix_prompt}])
                m = re.search(r'```(?:python)?\n(.*?)```', fixed, re.DOTALL)
                current_code = m.group(1).strip() if m else fixed.strip()
                review_log.append(f"第 {round_no} 轮 · DeepSeek 修改后代码（前 200 字）：{current_code[:200]}")
            if not approved:
                detail = "\n".join(review_log)
                return (
                    f"代码经 {max_rounds} 轮审查仍未通过，已主动终止避免死循环。\n"
                    f"请用户提供更多信息或放宽约束。\n【分歧过程】\n{detail}"
                )

    generated_dir = Path(CONFIG["skills_dir"]) / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    file_path = generated_dir / f"{name}.py"
    header = f"# 基于 {base_skill or '新创建'} 迭代生成\n"
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(header + code)

    config_path = Path(CONFIG["skills_config"])
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
    else:
        config = {"skills": {}}
    config['skills'][name] = {
        "enabled": True,
        "description": description,
        "parameters": parameters,
        "module": f"generated.{name}",
        "function": "execute"
    }
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    global SKILLS
    SKILLS = load_skills_plugin()
    return f"技能 {name} 已创建并启用。"

# ==================== 直接命令处理 ====================
def handle_direct_command(content, sender_id, identifier, message_type='private', group_id=None):
    # 漏洞6：设置当前线程用户上下文（uid 来自真实发送者，区分群聊/私聊）
    set_current_message({'sender_id': sender_id, 'message_type': message_type, 'group_id': group_id})
    if not content.startswith(CONFIG["direct_cmd_prefix"]):
        return False, None
    rest = content[1:].strip()
    if not rest:
        return True, "请提供命令"
    parts = rest.split(maxsplit=1)
    cmd = parts[0].lower()
    tail = parts[1] if len(parts) > 1 else ""

    # 帮助
    if cmd == 'help':
        return True, builtin_help()

    # 状态
    if cmd == 'status':
        import platform, sys
        lines = [
            f"🦞 小龙虾状态",
            f"系统: {platform.system()} {platform.release()}",
            f"Python: {sys.version.split()[0]}",
            f"工作目录: {os.getcwd()}",
            f"已启用技能: {len(SKILLS)} 个",
            f"永久记忆: {len(memory_manager.list_all())} 条",
            f"代码审查: {'开启' if CONFIG.get('code_review_enabled', True) else '关闭'}",
            f"QQ连接: 已连接 NapCat",
        ]
        if identifier in sessions:
            active = ', '.join(sessions[identifier].keys())
            lines.append(f"活动Shell会话: {active if active else '无'}")
        else:
            lines.append("活动Shell会话: 无")
        return True, "\n".join(lines)

    # 技能列表
    if cmd == 'skills_list':
        if not SKILLS:
            return True, "当前没有可用的技能。"
        lines = ["📋 可用技能列表："]
        for name, skill in SKILLS.items():
            params_str = ', '.join(skill.parameters.keys()) if skill.parameters else '无'
            lines.append(f"  {name}  - {skill.description or '无描述'} (参数: {params_str})")
        return True, "\n".join(lines)

    # 技能调用
    if cmd == 'skills':
        if not tail:
            return True, "用法: #skills <技能名> [参数]"
        parts2 = tail.split(maxsplit=1)
        skill_name = parts2[0]
        args_str = parts2[1] if len(parts2) > 1 else ""
        params = {}
        if args_str:
            for item in args_str.split():
                if '=' in item:
                    k, v = item.split('=', 1)
                    params[k] = v
                else:
                    params['arg'] = item
        if skill_name in SKILLS:
            result = SKILLS[skill_name].execute(**params)
            return True, f"技能执行结果:\n{result}"
        elif skill_name in BUILTIN_OPS:
            try:
                result = BUILTIN_OPS[skill_name](**params)
                return True, f"内置操作结果:\n{result}"
            except Exception as e:
                return True, f"执行内置操作失败: {e}"
        else:
            return True, f"未找到技能或内置操作: {skill_name}"

    # 一次性命令
    if cmd == 'exec':
        if not tail:
            return True, "用法: #exec <命令>"
        allowed, reason = guard_command(tail)
        if not allowed:
            return True, f"⛔ {reason}"
        # 动态行为指纹日志 + 连续长指令人工审核阈值
        manual = log_behavior_fingerprint(get_current_uid(), 'exec', tail, cwd=os.getcwd(), env=os.environ)
        try:
            subprocess.Popen(normalize_newlines(tail), shell=True, creationflags=subprocess.CREATE_NO_WINDOW)
            reply = f"已启动: {tail}"
            if manual:
                reply += "\n⚠️ 行为指纹异常：连续多次长指令，已触发人工审核，请管理员复核。"
            return True, reply
        except Exception as e:
            return True, f"启动失败: {e}"

    # 交互式 Shell
    if cmd == 'tools':
        if not tail:
            return True, "用法: #tools <shell> 或 #tools <shell> <命令>"
        parts2 = tail.split(maxsplit=1)
        shell = parts2[0].lower()
        if shell not in ['cmd', 'powershell', 'python']:
            return True, "不支持的 Shell，可选: cmd, powershell, python"

        if len(parts2) == 1:
            if get_session(identifier, shell):
                return True, f"{shell} 会话已存在，可直接发送命令。"
            else:
                result = start_shell(identifier, shell)
                return True, result
        else:
            command = parts2[1]
            allowed, reason = guard_command(command)
            if not allowed:
                return True, f"⛔ {reason}"
            if not get_session(identifier, shell):
                start_shell(identifier, shell)
            output = send_to_shell(identifier, shell, command)
            return True, output

    # 权限管理
    if cmd == 'auth':
        if sender_id != CONFIG['admin_qq']:
            return True, "❌ 只有管理员可执行权限管理命令"
        parts2 = tail.split(maxsplit=1)
        if not parts2:
            return True, "用法: #auth add <qq> <昵称>  |  #auth remove <qq>  |  #auth list"
        subcmd = parts2[0].lower()
        args = parts2[1] if len(parts2) > 1 else ""
        if subcmd == 'add':
            add_parts = args.split(maxsplit=1)
            if len(add_parts) < 2:
                return True, "用法: #auth add <qq> <昵称>"
            qq, nickname = add_parts[0].strip(), add_parts[1].strip()
            add_authorized_user(qq, nickname)
            return True, f"✅ 已授权用户 {nickname}（QQ：{qq}）"
        elif subcmd == 'remove':
            if not args:
                return True, "用法: #auth remove <qq>"
            qq = args.strip()
            if remove_authorized_user(qq):
                return True, f"✅ 已撤销 QQ {qq} 的权限"
            else:
                return True, f"❌ 未找到 QQ {qq}"
        elif subcmd == 'list':
            return True, list_authorized_users()
        else:
            return True, f"❌ 未知子命令: {subcmd}，可用: add, remove, list"

    # 永久记忆
    if cmd == 'memory':
        if sender_id != CONFIG['admin_qq']:
            return True, "❌ 只有管理员可管理永久记忆"
        parts2 = tail.split(maxsplit=1)
        if not parts2:
            return True, "用法: #memory add <内容>  |  #memory remove <id>  |  #memory list  |  #memory clear"
        subcmd = parts2[0].lower()
        args = parts2[1] if len(parts2) > 1 else ""
        if subcmd == 'add':
            if not args:
                return True, "用法: #memory add <内容>"
            memory_id = memory_manager.add(args)
            return True, f"✅ 记忆已添加 (ID: {memory_id})"
        elif subcmd == 'remove':
            if not args:
                return True, "用法: #memory remove <id>"
            if memory_manager.remove(args.strip()):
                return True, f"✅ 记忆已删除"
            else:
                return True, f"❌ 未找到记忆 ID: {args}"
        elif subcmd == 'list':
            memories = memory_manager.list_all()
            if not memories:
                return True, "暂无永久记忆"
            lines = ["📋 永久记忆列表："]
            for m in memories:
                lines.append(f"  {m['id']} - {m['content']} (创建于 {m['created_at'][:10]})")
            return True, "\n".join(lines)
        elif subcmd == 'clear':
            memory_manager.clear()
            return True, "✅ 所有记忆已清空"
        else:
            return True, f"❌ 未知子命令: {subcmd}，可用: add, remove, list, clear"

    # 定时任务
    if cmd == 'schedule':
        if sender_id != CONFIG['admin_qq']:
            return True, "❌ 只有管理员可管理定时任务"
        parts2 = tail.split(maxsplit=1)
        if not parts2:
            return True, "用法: #schedule add <cron> <命令>  |  #schedule list  |  #schedule remove <id>"
        subcmd = parts2[0].lower()
        args = parts2[1] if len(parts2) > 1 else ""
        if subcmd == 'add':
            # 简化：格式 'min hour day month day_of_week command'
            items = args.split(maxsplit=5)
            if len(items) < 6:
                return True, "用法: #schedule add <分> <时> <日> <月> <周> <命令>  (例如: 30 10 * * * #exec backup)"
            cron_expr = ' '.join(items[:5])
            command = items[5]
            # 生成ID
            task_id = hashlib.md5(f"{cron_expr}{command}{time.time()}".encode()).hexdigest()[:8]
            # 利用 schedule 库简单实现（实际应解析cron，这里简化）
            if cron_expr == '* * * * *':  # 每分钟
                schedule.every().minute.do(lambda: execute_scheduled_task(command))
            elif cron_expr == '0 * * * *':  # 每小时
                schedule.every().hour.do(lambda: execute_scheduled_task(command))
            else:
                # 简化处理，只支持每天定时
                parts_cron = cron_expr.split()
                if len(parts_cron) >= 2 and parts_cron[0] != '*' and parts_cron[1] != '*':
                    hour = int(parts_cron[1])
                    minute = int(parts_cron[0])
                    schedule.every().day.at(f"{hour:02d}:{minute:02d}").do(lambda: execute_scheduled_task(command))
                else:
                    return True, "不支持的cron格式，当前仅支持每天固定时间"
            scheduler.tasks[task_id] = {"cron": cron_expr, "command": command}
            return True, f"✅ 定时任务已添加 (ID: {task_id})"
        elif subcmd == 'list':
            tasks = scheduler.list_tasks()
            if not tasks:
                return True, "暂无定时任务"
            lines = ["📋 定时任务列表："]
            for tid, info in tasks.items():
                lines.append(f"  {tid} - {info['cron']} -> {info['command']}")
            return True, "\n".join(lines)
        elif subcmd == 'remove':
            if not args:
                return True, "用法: #schedule remove <id>"
            if scheduler.remove_task(args.strip()):
                return True, f"✅ 定时任务已删除"
            else:
                return True, f"❌ 未找到任务 ID: {args}"
        else:
            return True, f"❌ 未知子命令: {subcmd}，可用: add, list, remove"

    # 未匹配命令，交给 AI
    return False, None

def execute_scheduled_task(command):
    # 在后台执行命令，可通过消息源发送结果（这里简化为日志）
    logger.info(f"执行定时任务: {command}")
    # 可扩展为通过QQ发送结果

# ==================== 消息处理函数 ====================
processing = {}
queues = {}
executor = concurrent.futures.ThreadPoolExecutor(max_workers=5)

def process_message(identifier, msg, source):
    # 漏洞6：设置当前线程用户上下文（uid 来自真实发送者，线程隔离）
    set_current_message(msg)
    try:
        logger.info(f"处理消息: identifier={identifier}, sender={msg['sender_id']}, content={msg['content']}")
        history = source.get_history(identifier)
        history.append({"role": "user", "content": msg['content']})

        # 检查是否有挂起的上下文（ask_user 回复）
        if identifier in pending_contexts:
            context = pending_contexts.pop(identifier)
            # 将用户回复追加到历史
            context['history'].append({"role": "user", "content": msg['content']})
            # 继续执行
            reply = execute_agent_loop(msg['content'], context['history'], identifier, source)
            if reply is not None:
                source.send_reply(identifier, reply)
                history.append({"role": "assistant", "content": reply})
            return

        # 正常处理
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as inner_executor:
            future = inner_executor.submit(execute_agent_loop, msg['content'], list(history), identifier, source)
            try:
                reply = future.result(timeout=CONFIG["response_timeout"])
                if reply is not None:
                    source.send_reply(identifier, reply)
                    history.append({"role": "assistant", "content": reply})
                    logger.info(f"回复: {reply[:100]}...")
            except concurrent.futures.TimeoutError:
                source.send_reply(identifier, "⏳ 任务正在处理中，可能项目较大，请耐心等待...")
                reply = future.result()
                if reply is not None:
                    source.send_reply(identifier, reply)
                    history.append({"role": "assistant", "content": reply})
                    logger.info(f"超时后回复: {reply[:100]}...")
    except Exception as e:
        source.send_reply(identifier, f"❌ 处理失败: {e}")
        logger.error(f"处理消息异常: {e}")
    finally:
        processing[identifier] = False
        q = queues.get(identifier, deque())
        if q:
            next_msg = q.popleft()
            process_message(identifier, next_msg, source)
        else:
            if identifier in queues:
                del queues[identifier]

# ==================== 主程序 ====================
def main():
    check_login_state()
    global SKILLS
    SKILLS = load_skills_plugin()
    # 动态注册「调度其他网页版 AI」能力为一个新 skill，供主脑调度子 Agent
    SKILLS['web_ai_agent'] = SkillPlugin(
        'web_ai_agent',
        web_ai_agent,
        '调度指定的网页版 AI（deepseek/kimi 等）作为子 Agent 回答问题',
        {'provider': 'AI 名', 'prompt': '要它回答的问题', 'system': '可选系统提示'},
        True,
    )
    # 动态注册「并发调度子 Agent」能力为一个新 skill，供主脑通过提示词触发
    SKILLS['dispatch_sub_agent'] = SkillPlugin(
        'dispatch_sub_agent',
        dispatch_sub_agent,
        '将子 Agent 任务（网页版 AI）交给 LobsterScheduler 并发调度，不阻塞主脑回复',
        {'provider': 'AI 名(deepseek/kimi)', 'prompt': '要它回答的问题', 'system': '可选系统提示', 'image_path': '可选：附图路径', 'file_paths': '可选：多文件路径列表'},
        True,
    )
    logger.info(f"已加载 {len(SKILLS)} 个技能")

    # 启动定时任务调度器
    if CONFIG.get("schedule_enabled", True):
        scheduler.start()
        logger.info("定时任务调度器已启动")

    source = NapCatSource()
    source.start()
    global GLOBAL_SOURCE
    GLOBAL_SOURCE = source   # 供 LobsterScheduler 的调度线程回传子 Agent 结果
    logger.info("NapCat 已启动，等待消息...")
    print("🦞 小龙虾 v2.0 已启动，等待QQ消息...")

    while True:
        try:
            msgs = source.get_new_messages()
            for msg in msgs:
                identifier = msg['identifier']
                sender_id = msg['sender_id']
                content = msg['content']

                if sender_id != CONFIG['admin_qq'] and not is_authorized(sender_id):
                    logger.info(f"⛔ 用户 {msg['sender_nick']}({sender_id}) 无权限")
                    continue

                handled, reply = handle_direct_command(content, sender_id, identifier, msg.get('message_type', 'private'), msg.get('group_id'))
                if handled:
                    source.send_reply(identifier, reply)
                    continue

                if processing.get(identifier, False):
                    queues.setdefault(identifier, deque()).append(msg)
                    logger.info(f"⏳ {identifier} 当前忙，消息已排队")
                    continue

                processing[identifier] = True
                executor.submit(process_message, identifier, msg, source)
        except KeyboardInterrupt:
            logger.info("用户中断，退出程序")
            try:
                lobster_scheduler.shutdown()
            except Exception:
                pass
            break
        except Exception as e:
            logger.error(f"主循环异常: {e}")
        time.sleep(CONFIG["poll_interval"])

if __name__ == "__main__":
    SKILLS = {}
    main()