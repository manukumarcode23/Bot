import re
from os import environ

id_pattern = re.compile(r'^.\d+$')

# Bot information
SESSION = environ.get('SESSION', 'TechVJBot')
API_ID = int(environ.get('API_ID', '25090660'))
API_HASH = environ.get('API_HASH', '58fd3b352d60d49f6d145364c6791c1b')
BOT_TOKEN = environ.get('BOT_TOKEN', "8280966934:AAGQGhI4QUzORsBpaNt56nwv4som93M9zVw")

# Bot settings
PORT = environ.get("PORT", "8080")
URL = environ.get("URL", "") # Your Koyeb App URL, e.g., https://my-app-my-org.koyeb.app

# Admins, Channels & Users
LOG_CHANNEL = int(environ.get('LOG_CHANNEL', '-1002988719658'))
ADMINS = [int(admin) if id_pattern.search(admin) else admin for admin in environ.get('ADMINS', '8391217905').split()]

# MongoDB information
DATABASE_URI = environ.get('DATABASE_URI', "")
DATABASE_NAME = environ.get('DATABASE_NAME', "techvjautobot")
