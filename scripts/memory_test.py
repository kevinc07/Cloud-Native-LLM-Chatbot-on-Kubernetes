"""Day 9:模擬「同一個 user 連續打好幾輪 /chat」,觀察多 replica 時記憶是否一致。

每一輪印出:哪個 pod 回答(X-Served-By)、它看到幾則歷史(X-History-Len)。
正常情況 history 應該是 0, 2, 4, 6...(每輪 +2)。
如果某一輪突然掉回 0 或變小,代表請求被分到另一個 pod,而那個 pod 的記憶體沒有這段對話。

用法:python scripts/memory_test.py [輪數] [base_url] [Host header]
例:python scripts/memory_test.py 12 http://172.184.203.57 api.chatbot.local
"""
import json
import sys
import urllib.request

ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 12
BASE = sys.argv[2] if len(sys.argv) > 2 else "http://api.chatbot.local"
HOST = sys.argv[3] if len(sys.argv) > 3 else BASE.split("//", 1)[1]


def chat(conversation_id, text):
    body = {"user_id": "memtest", "message": text, "conversation_id": conversation_id}
    req = urllib.request.Request(
        # 若 /etc/hosts 沒設網域,可把 BASE 換成 http://<ingress IP>,Host header 會帶對的網域
        f"{BASE}/chat",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Host": HOST},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
        return data["conversation_id"], r.headers["X-Served-By"], int(r.headers["X-History-Len"])


cid, expected, lost = None, 0, 0
print(f"{'turn':>4}  {'expected':>8}  {'seen':>4}  pod")
for i in range(1, ROUNDS + 1):
    cid, pod, seen = chat(cid, f"第 {i} 輪,請只回答「收到」")
    bad = seen != expected
    lost += bad
    print(f"{i:>4}  {expected:>8}  {seen:>4}  {pod}{'   <-- 記憶不一致!' if bad else ''}")
    expected += 2   # 每輪成功後,這段對話累積 user+bot 兩則
print(f"\n{lost}/{ROUNDS} 輪看到的歷史跟預期不同(conversation_id={cid})")
