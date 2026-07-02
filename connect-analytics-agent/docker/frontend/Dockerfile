FROM node:20-alpine
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ .
RUN chown -R node:node /app
EXPOSE 5274
USER node
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
