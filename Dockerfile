# Use the official Python image
FROM python:3.9

# Salin semua file ke dalam container
COPY . .

# Instal dependensi dari requirements.txt
RUN pip install -r requirements.txt

# Copy the rest of the application code
COPY . .

# Expose the port Flask runs on (adjust if needed for your app)
EXPOSE 8000

# Run the Flask app and bot
CMD ["sh", "-c", "python web.py & python main.py"]
