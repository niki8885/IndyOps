FROM node:22-alpine AS build

WORKDIR /app
# .npmrc carries legacy-peer-deps=true (the @codecov/vite-plugin vite-8 peer
# override) — copy it before `npm ci` so the install resolves inside the image.
COPY indyops-ui/package*.json indyops-ui/.npmrc ./
RUN npm ci
COPY indyops-ui/ .
RUN npm run build


FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80 443
