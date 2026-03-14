FROM node:22-alpine

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install

COPY frontend /app/frontend

EXPOSE 4174

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "4174"]
