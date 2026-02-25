# AutoBox Frontend Dockerfile
# Build stage
FROM node:20-alpine AS build

WORKDIR /app

# Build argument for API URL (Docker환경에서는 nginx 프록시 사용)
ARG VITE_API_URL=/api/v1
ENV VITE_API_URL=$VITE_API_URL

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm install

# Copy source code (includes .env)
COPY . .

# Build the application with the env var set
RUN npm run build

# Production stage
FROM nginx:alpine

# Copy built files
COPY --from=build /app/dist /usr/share/nginx/html

# Copy nginx configuration template
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

# Expose port
EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
