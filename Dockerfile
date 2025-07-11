FROM python:3.12.9-slim


# Install necessary dependencies
COPY requirements.txt .
RUN pip install --force-reinstall -r requirements.txt
COPY GiNet_sdk-0.2.tar.gz .
RUN pip install GiNet_sdk-0.2.tar.gz
RUN pip install --upgrade langchain_mistralai

# Copy your application code
COPY . /app

# Copy .env file
COPY .env /app/.env

WORKDIR /app

RUN pip install gunicorn

# Expose the port
EXPOSE 2095

# Run gunicorn when the container launches
CMD ["gunicorn", "-b", ":2095", "main:app"]