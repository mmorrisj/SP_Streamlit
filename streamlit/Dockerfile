FROM python:3.11-slim

WORKDIR /app

COPY streamlit/requirements.txt .
COPY backend/scripts /app/backend/scripts
COPY backend/app.py /app/backend/app.py
COPY backend/extensions.py /app/backend/extensions.py
COPY backend/routes.py /app/backend/routes.py
COPY backend/commands.py /app/backend/commands.py
COPY backend/config.yaml /app/backend/config.yaml

COPY ./streamlit /app
RUN pip install -r requirements.txt --index-url https://pypi.org/simple

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.enableCORS=false"]
