# syntax=docker/dockerfile:1.7
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

# nginx sin privilegios: escucha en 8080 y corre como uid 101.
FROM nginxinc/nginx-unprivileged:1.27-alpine
LABEL org.opencontainers.image.title="meeting-transcriber-web" \
      org.opencontainers.image.description="Frontal React servido por nginx" \
      org.opencontainers.image.source="https://github.com/adrianrevilla009/meeting-transcriber"
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/healthz"]
