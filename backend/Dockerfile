FROM python:3.12-slim

WORKDIR /app

# build-essential: a couple of transitive geospatial deps (e.g. pyrosm's
# cykhash) have no prebuilt wheel for every platform/Python combo and
# fall back to compiling from source, which the slim image can't do
# without a C compiler.
# libexpat1: rasterio's wheel bundles GDAL but still dynamically links
# against the system's libexpat at runtime, which the slim image lacks.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libexpat1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY tests ./tests
COPY pytest.ini .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
