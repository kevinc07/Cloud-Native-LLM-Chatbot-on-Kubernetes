#!/bin/sh
# Day 9:在 cluster 內製造 CPU 負載,觸發 HPA 擴容。
# 用法:scripts/load.sh start | stop
# 在 cluster 裡面打(不經公網),打 /health 這種便宜的端點:
# /chat 的時間大多花在等 Gemini(不吃 CPU),打它很難讓 CPU 升高。
case "$1" in
  start)
    kubectl create deployment load-gen --image=busybox:1.36 --replicas=4 -- \
      sh -c 'while true; do wget -q -O- http://chatbot-backend:3030/health >/dev/null; done'
    ;;
  stop)
    kubectl delete deployment load-gen
    ;;
  *) echo "usage: $0 start|stop"; exit 1 ;;
esac
