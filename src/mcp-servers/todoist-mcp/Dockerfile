FROM node:22-slim

RUN npm install -g @doist/todoist-mcp

ENV HOST=0.0.0.0
ENV PORT=3001

EXPOSE 3001

CMD ["todoist-mcp-http"]
