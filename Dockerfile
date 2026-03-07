FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY librariarr ./librariarr

ENTRYPOINT ["python", "-m", "librariarr.main"]
CMD ["--config", "/config/config.yaml"]
