from flask import Flask


# blueprints
from mtango import tango

app = Flask(__name__)
app.register_blueprint(tango, url_prefix="/rest")

