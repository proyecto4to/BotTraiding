# TradingPlatform frontend (Next.js 14) - multi-stage build.
# NEXT_PUBLIC_* vars are inlined into the client bundle at BUILD time, so the
# gateway URL is a build arg: it must be the URL the *browser* uses to reach
# the gateway (http://localhost:8000 for the local compose stack).

FROM node:20-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG NEXT_PUBLIC_GATEWAY_URL=http://localhost:8000
ENV NEXT_PUBLIC_GATEWAY_URL=${NEXT_PUBLIC_GATEWAY_URL}
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

COPY package.json package-lock.json ./
RUN npm ci --omit=dev

COPY --from=build /app/.next ./.next
COPY --from=build /app/next.config.js ./

EXPOSE 3000
CMD ["npx", "next", "start", "-p", "3000"]
