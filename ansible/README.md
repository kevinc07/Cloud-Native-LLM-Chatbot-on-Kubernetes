# Ansible

需要:`brew install ansible`(本專案用 core 2.21,只用內建模組,不需要額外 collection)。

| 檔案 | 用途 |
|---|---|
| `day17-idempotence.yml` | 冪等性示範:跑第二次 `changed=0`(最後一個 task 是刻意的反面教材) |
| `update-config.yml` | 更新 ConfigMap 設定:驗證輸入 → 改 `mychart/values.yaml` 的 `config:` → helm lint/template → (選用)commit+push |
| `vars/dev.yml` | 想要的設定值 |

為什麼 playbook 改 git 而不是直接 `kubectl apply`:ArgoCD 開了 selfHeal,手動改 cluster 會被改回 git 的樣子,
所以設定變更必須走 git。這個 playbook 自動化的是「安全地改 git」那一段。

```bash
cd ansible
ansible-playbook update-config.yml --check --diff   # 預覽
ansible-playbook update-config.yml -e push=true     # 寫檔並 push,之後 ArgoCD 自動部署
```

限制:沒有遠端主機,inventory 只有 localhost;Day 17 沒有在 VM 上裝 docker,只示範冪等概念。
