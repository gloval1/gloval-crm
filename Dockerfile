FROM python:3.9-slim

WORKDIR /app

COPY server.py ./
COPY static/ ./static/
COPY crm.db ./

ENV PORT=8088
EXPOSE 8088

CMD ["python3", "server.py"]
