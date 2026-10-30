#!/usr/bin/env python3
"""
Day 3 盲測用 bug 注入器
=======================
!! 想練「盲測」的話,請不要往下讀這個檔案 !!

用法(在放 docker-compose.yml 的那一層資料夾執行):
    python3 break_it.py             埋一個隨機 bug(不會告訴你是哪個)
    python3 break_it.py --restore   還原成原本的檔案
    python3 break_it.py --reveal    揭曉答案(定位完再看)

只會動 chatbot-backend/main.py 或 chatbot-backend/Dockerfile 其中一個。
原始檔案備份在 ~/.day3_bug_state/,不會弄髒你的 repo。
"""
import argparse
import base64
import json
import random
import shutil
import sys
from pathlib import Path

REPO = Path.cwd()
BACKEND = REPO / "chatbot-backend"
FILES = {"main.py": BACKEND / "main.py", "Dockerfile": BACKEND / "Dockerfile"}
STATE_DIR = Path.home() / ".day3_bug_state"
STATE_FILE = STATE_DIR / "state.json"
ORIG_DIR = STATE_DIR / "orig"


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"applied": False, "last_id": None, "answer_b64": None}


def save_state(state):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def check_location():
    if not (REPO / "docker-compose.yml").exists() or not BACKEND.is_dir():
        sys.exit(
            "找不到 docker-compose.yml 或 chatbot-backend/ 。\n"
            "請先 cd 到專案根目錄(docker-compose.yml 那一層)再執行。"
        )
    for name, path in FILES.items():
        if not path.exists():
            sys.exit(f"找不到 {path},無法繼續。")


def apply():
    check_location()
    state = load_state()
    if state["applied"]:
        sys.exit(
            "已經埋過一個 bug 了。\n"
            "請先把它 debug 完,或用 --restore 還原後再重新埋。"
        )

    contents = {n: p.read_text(encoding="utf-8") for n, p in FILES.items()}
    usable = [b for b in BUGS if contents[b["file"]].count(b["old"]) == 1]
    if not usable:
        sys.exit("你的檔案內容跟我預期的差太多,沒有任何 bug 能安全埋入。什麼都沒改。")

    pool = [b for b in usable if b["id"] != state["last_id"]] or usable
    bug = random.choice(pool)

    ORIG_DIR.mkdir(parents=True, exist_ok=True)
    for name, path in FILES.items():
        shutil.copy2(path, ORIG_DIR / name)

    target = FILES[bug["file"]]
    target.write_text(
        contents[bug["file"]].replace(bug["old"], bug["new"], 1), encoding="utf-8"
    )

    state["applied"] = True
    state["last_id"] = bug["id"]
    state["answer_b64"] = base64.b64encode(bug["answer"].encode("utf-8")).decode()
    save_state(state)

    print("已經埋入 1 個 bug(不告訴你是哪個)。")
    print("下一步:docker-compose up -d --build backend,然後開始計時。")


def restore():
    state = load_state()
    if not state["applied"]:
        sys.exit("目前沒有埋任何 bug,不用還原。")
    for name, path in FILES.items():
        shutil.copy2(ORIG_DIR / name, path)
    state["applied"] = False
    save_state(state)
    print("已還原 main.py 與 Dockerfile 成原本的樣子。")
    print("記得 docker-compose up -d --build backend,container 才會換回正常版本。")


def reveal():
    state = load_state()
    if not state["answer_b64"]:
        sys.exit("還沒有埋過 bug,沒有答案可以揭曉。")
    print(base64.b64decode(state["answer_b64"]).decode("utf-8"))
    if state["applied"]:
        print("\n(bug 目前還在檔案裡,收尾請用 --restore 還原。)")


def main():
    ap = argparse.ArgumentParser(description="Day 3 盲測 bug 注入器")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--restore", action="store_true", help="還原原本的檔案")
    group.add_argument("--reveal", action="store_true", help="揭曉答案")
    args = ap.parse_args()
    if args.restore:
        restore()
    elif args.reveal:
        reveal()
    else:
        apply()


# ---------------------------------------------------------------------------
# 以下是 bug 清單。想盲測就別往下看。
# ---------------------------------------------------------------------------
_APP = 'app = FastAPI(title="Chatbot Backend")'

BUGS = [
    {
        "id": "missing-module",
        "file": "main.py",
        "old": "import uuid\n",
        "new": "import uuid\nimport pandas as pd\n",
        "answer": (
            "【missing-module】main.py 多 import 了 pandas,但 requirements.txt 沒有,"
            "image 裡沒裝 → ModuleNotFoundError: No module named 'pandas'。\n"
            "uvicorn(PID 1)一啟動就死,exit code 1;因為 restart: unless-stopped,"
            "container 會一直被重新拉起來又死掉(crash loop)。\n"
            "修法:拿掉那行 import,或把 pandas 補進 requirements.txt 再 rebuild。"
        ),
    },
    {
        "id": "missing-env",
        "file": "main.py",
        "old": _APP,
        "new": 'APP_ENV = os.environ["APP_ENV"]\n' + _APP,
        "answer": (
            "【missing-env】程式啟動時用 os.environ[\"APP_ENV\"] 讀一個 .env 和 compose "
            "都沒設定的環境變數 → KeyError: 'APP_ENV'。\n"
            "exit code 1,crash loop。\n"
            "修法:把這個變數設進 .env,或改成 os.getenv(\"APP_ENV\", 預設值),或拿掉。"
        ),
    },
    {
        "id": "permission",
        "file": "main.py",
        "old": _APP,
        "new": 'open("/app/startup.marker", "w").write("started")\n' + _APP,
        "answer": (
            "【permission】啟動時想在 /app 底下寫檔,但 /app 目錄是 root 建的,"
            "appuser 沒有寫入權限 → PermissionError: [Errno 13] Permission denied。\n"
            "exit code 1,crash loop。\n"
            "修法:別寫 /app(要寫暫存檔就寫 /tmp),或在 Dockerfile 裡處理目錄權限。"
        ),
    },
    {
        "id": "syntax",
        "file": "main.py",
        "old": _APP,
        "new": 'app = FastAPI(title="Chatbot Backend"',
        "answer": (
            "【syntax】main.py 有一個括號沒關 → SyntaxError: '(' was never closed。\n"
            "log 會指出檔名與行號。uvicorn 載入 main 就失敗,exit code 1,crash loop。\n"
            "修法:把括號補上。"
        ),
    },
    {
        "id": "bind-localhost",
        "file": "Dockerfile",
        "old": '"--host", "0.0.0.0"',
        "new": '"--host", "127.0.0.1"',
        "answer": (
            "【bind-localhost】uvicorn 只綁在 container 內部的 127.0.0.1,"
            "外面轉發進來的流量連不到它。\n"
            "container 是 Up 的、log 看起來一切正常,但從 Mac curl localhost:8000 會失敗。\n"
            "線索:log 裡 Uvicorn running on 後面的位址。\n"
            "修法:Dockerfile 的 --host 改回 0.0.0.0 並 rebuild。"
        ),
    },
    {
        "id": "port-mismatch",
        "file": "Dockerfile",
        "old": '"--port", "8000"',
        "new": '"--port", "8001"',
        "answer": (
            "【port-mismatch】uvicorn 改聽 8001,但 compose 把 host 的 8000 轉到 "
            "container 的 8000,那邊沒人在聽。\n"
            "container 是 Up 的、沒有任何錯誤,但從 Mac curl localhost:8000 會失敗。\n"
            "線索:log 裡 Uvicorn running on 後面的 port。\n"
            "修法:Dockerfile 的 --port 改回 8000 並 rebuild。"
        ),
    },
]


if __name__ == "__main__":
    main()
