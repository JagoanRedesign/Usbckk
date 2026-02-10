from flask import Flask, jsonify

# Create a Flask instance
app = Flask(__name__)

# Define the root endpoint
@app.route('/')
def hello():
    return jsonify({"message": "Bot is running! by Mz"})

# Define the health check endpoint
@app.route('/health')
def health_check():
    try:
        return jsonify({"status": "healthy"}), 200
    except Exception as e:
        return jsonify({"status": "unhealthy"}), 500

# Run the Flask app
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
