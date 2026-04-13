from flask import Flask

from .db import db_init
from .routes import register_error_and_hooks
from .routes.core import bp as core_bp
from .routes.ffmpeg import bp as ffmpeg_bp
from .routes.files import bp as files_bp
from .routes.jobs import bp as jobs_bp
from .routes.presets import bp as presets_bp
from .routes.ytdlp import bp as ytdlp_bp


def create_app():
    app = Flask(__name__)
    register_error_and_hooks(app)
    app.register_blueprint(core_bp)
    app.register_blueprint(ytdlp_bp)
    app.register_blueprint(ffmpeg_bp)
    app.register_blueprint(jobs_bp)
    app.register_blueprint(files_bp)
    app.register_blueprint(presets_bp)
    db_init()
    return app
