# Ansible

Requires `brew install ansible` (tested with ansible-core 2.21; built-in modules only, no extra collections).

| File | Purpose |
|---|---|
| `day17-idempotence.yml` | Idempotence demo: the second run reports `changed=0` (the last task is a deliberate counter-example) |
| `update-config.yml` | Update ConfigMap settings: validate input → edit the `config:` block in `mychart/values.yaml` → `helm lint` / `helm template` → (optional) commit + push |
| `vars/dev.yml` | The desired settings |

Why the playbook edits git instead of running `kubectl apply`: ArgoCD has selfHeal on, so manual cluster changes are reverted to
whatever git says. Configuration changes therefore have to go through git. This playbook automates the "change git safely" part.

```bash
cd ansible
ansible-playbook update-config.yml --check --diff   # preview
ansible-playbook update-config.yml -e push=true     # write, commit and push; ArgoCD deploys it
```

Limitations: there are no remote hosts, so the inventory is localhost only. The idempotence demo does not install Docker on a VM; it only demonstrates the concept.
