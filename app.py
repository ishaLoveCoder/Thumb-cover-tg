from flask import Flask
import logging

app = Flask(__name__)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.route('/')
def hello_world():
    return '🤖 Thumbnail Cover Changer Bot'

@app.route('/ping')
def ping():
    return 'Pong!'

@app.route('/health')
def health():
    return 'OK'

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
