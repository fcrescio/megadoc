FROM node:20-alpine AS builder

WORKDIR /app

RUN apk add --no-cache git
ARG VITE_GIT_HASH=unknown
ENV VITE_GIT_HASH=$VITE_GIT_HASH
ARG REACT_PROFILING=false
ENV REACT_PROFILING=$REACT_PROFILING

COPY package*.json ./
RUN npm install

# Swap in React profiling builds when enabled (for Chrome DevTools Profiler)
# Only react-dom has a profiling build in React 18; react and scheduler don't.
RUN if [ "$REACT_PROFILING" = "true" ]; then \
      cp node_modules/react-dom/cjs/react-dom.profiling.min.js node_modules/react-dom/cjs/react-dom.production.min.js && \
      cp node_modules/react-dom/cjs/react-dom.profiling.min.js node_modules/react-dom/cjs/react-dom.development.js; \
    fi

COPY . .
RUN npm run build

FROM nginx:alpine

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3030

CMD ["nginx", "-g", "daemon off;"]
