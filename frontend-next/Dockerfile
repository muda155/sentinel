FROM node:22-alpine AS build
ARG NEXT_PUBLIC_API_BASE
ARG NEXT_PUBLIC_MAP_STYLE
WORKDIR /app
COPY package*.json ./
# Cache npm downloads in the build cache so node_modules isn't re-fetched on
# every rebuild; --prefer-offline installs from cache when the network is slow.
RUN --mount=type=cache,target=/root/.npm \
    npm ci --prefer-offline
COPY . .
RUN npm run build

FROM node:22-alpine AS run
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/.next ./.next
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package.json ./package.json
COPY --from=build /app/public ./public
EXPOSE 3000
CMD ["npm", "start"]
