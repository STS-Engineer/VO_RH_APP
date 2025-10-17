# run.py
from flask import Flask, render_template
from rh_app.routes import rh_bp
from voh_app.routes import voh_bp
from config import Config  # ✅ config globale

app = Flask(__name__)
app.config.from_object(Config)

# Enregistre les deux blueprints
app.register_blueprint(rh_bp, url_prefix="/rh")
app.register_blueprint(voh_bp, url_prefix="/voh")

@app.route('/')
def home():
    return render_template('home.html')

if __name__ == '__main__':
    app.run(debug=True)
