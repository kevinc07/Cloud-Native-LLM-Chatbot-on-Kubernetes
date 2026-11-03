# ---- build stage：裝依賴、build 出靜態檔(Vite + TypeScript + Tailwind v4)----
FROM node:20-alpine AS build
WORKDIR /app

# 先只複製 package*.json,靠 layer cache 加速之後每次 build。
# npm ci 嚴格依照 lockfile 安裝,每次 build 拿到的版本都一樣。
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# Vite 需要根目錄的 index.html 與設定檔,不只是 src/、public/
COPY index.html vite.config.ts tsconfig.json ./
COPY public ./public
COPY src ./src
# build = tsc 型別檢查 + vite build,輸出到 build/(與 CRA 時期相同,下面不用改)
RUN npm run build

# ---- runtime stage：只裝 nginx + build 好的靜態檔，非 root 執行 ----
FROM nginx:1.27-alpine

# nginx image 內建 nginx 這個 user，把預設 html 清掉、
# default.conf 拿掉(我們用自己的 nginx.conf 整份取代)，
# 並把 nginx 需要寫入的快取目錄的擁有者改成 nginx，讓非 root 也能跑
RUN rm -rf /usr/share/nginx/html/* \
    && rm -f /etc/nginx/conf.d/default.conf \
    && chown -R nginx:nginx /var/cache/nginx

COPY --from=build /app/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/nginx.conf

USER nginx
EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
