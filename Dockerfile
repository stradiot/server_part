FROM python:3.9-slim-buster 
MAINTAINER Martin Stradiot <xstradiotm@stuba.sk>

# Variables
ENV PYTHONUNBUFFERED=1

# Libraries
RUN apt update
RUN apt install -y gcc libpq-dev

# Code
COPY requirements.txt /requirements.txt

# Install requirements
WORKDIR /pip-packages/
RUN pip install --upgrade pip setuptools wheel
RUN pip install -r /requirements.txt

RUN mkdir -p /opt/sleep-detector
ADD src/ /opt/sleep-detector

# Start-up
ENTRYPOINT ["python","/opt/sleep-detector/main.py"]
