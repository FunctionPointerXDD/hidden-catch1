# 1단계: CRA 빌드
FROM node:20-alpine AS build
WORKDIR /app

# 의존성 설치
COPY front/game-app/package*.json ./
RUN npm install

# 실제 소스 복사 후 빌드
COPY front/game-app ./
RUN npm run build

# 2단계: Nginx로 정적 파일 서빙
FROM nginx:1.27-alpine

# nginx 설정 덮어쓰기
COPY infra/nginx/nginx.conf /etc/nginx/conf.d/default.conf

# CRA 빌드 결과를 nginx 기본 root로 복사
COPY --from=build /app/build /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
