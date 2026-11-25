FROM node:20-bookworm-slim
WORKDIR /broker
COPY package*.json ./
RUN npm ci --omit=dev --ignore-scripts --no-audit --no-fund
COPY server.js ./
USER node
EXPOSE 1883
CMD ["node","server.js"]
