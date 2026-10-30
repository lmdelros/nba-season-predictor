# Frontend image: build the React app with Node, then serve the static files with
# nginx, which also forwards /api requests to the API container (see nginx.conf).
#   docker build -t nba-predictor-web frontend

# Stage 1: build. Nothing from this stage ships except the dist/ folder.
FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# The app calls /api/... on the same address it was loaded from, so no API host or
# CORS configuration is needed.
ENV VITE_API_BASE_URL=/api
RUN npm run build

# Stage 2: serve. nginx 1.28 is the current stable branch.
FROM nginx:1.28-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
