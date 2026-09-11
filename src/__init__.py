"""
BioSecure AI — Girls Hostel Application Factory.

Blueprint layout:
  blueprints/auth.py        /login  /logout  /register
  blueprints/hostel.py      /hostel (dashboard, students, logs, curfew, video_feed, api)
"""

from __future__ import annotations

import logging
import os

from flask import Flask, jsonify, redirect, render_template, session, url_for, g

from src import config
from src.utils.auth_helpers import decode_jwt_token


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def _configure_logging() -> None:
    """Configure root logger with level and format from config."""
    log_level = getattr(logging, config.LOG_LEVEL, logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


_configure_logging()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app() -> Flask:
    """Create and configure the Flask application for Girls Hostel Management."""
    app = Flask(__name__)

    # Trust reverse proxy headers (ngrok) to ensure callback redirects use the public URL scheme
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)

    secret_key = os.environ.get("FLASK_SECRET_KEY", "biosecure-girls-hostel-flask-secret")
    app.secret_key = secret_key

    # ------------------------------------------------------------------
    # Register blueprints (Girls Hostel & Auth only)
    # ------------------------------------------------------------------
    from src.blueprints.auth import auth_bp
    from src.blueprints.hostel import hostel_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(hostel_bp)

    logger.info("Girls Hostel & Auth blueprints registered successfully.")

    # Pre-load in-memory face embedding cache for instant BLAS matching (< 1ms)
    try:
        from src.utils.face_cache import reload_face_cache
        reload_face_cache()
    except Exception as e:
        logger.warning("Initial face cache pre-load skipped: %s", e)


    # ------------------------------------------------------------------
    # Global error handlers
    # ------------------------------------------------------------------

    @app.errorhandler(404)
    def not_found(error):
        if _is_api_request():
            return jsonify({"error": "Resource not found"}), 404
        return render_template("error_404.html"), 404

    @app.errorhandler(403)
    def forbidden(error):
        if _is_api_request():
            return jsonify({"error": "Forbidden"}), 403
        return render_template("error_403.html"), 403

    @app.errorhandler(500)
    def internal_error(error):
        logger.exception("Internal server error: %s", error)
        if _is_api_request():
            return jsonify({"error": "Internal server error"}), 500
        return render_template("error_500.html"), 500

    # ------------------------------------------------------------------
    # Context processors
    # ------------------------------------------------------------------

    @app.context_processor
    def inject_user_info():
        user_data = getattr(g, "user", None) or {}
        return {
            "session_username": user_data.get("username") or session.get("username"),
            "session_is_admin": user_data.get("is_admin", False) or session.get("is_admin", False),
        }

    # ------------------------------------------------------------------
    # Request hooks & JWT Protection Middleware
    # ------------------------------------------------------------------

    @app.before_request
    def require_jwt_auth():
        """Validate JWT token for all protected routes."""
        from flask import request

        public_paths = {"/login", "/favicon.ico", "/healthz", "/auth/callback"}
        if (
            request.path.startswith("/static/")
            or request.path.startswith("/login/oauth/")
            or request.path in public_paths
        ):
            return None

        # Extract JWT token from Authorization header, cookie, or session
        token = None
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1].strip()
        
        if not token:
            token = request.cookies.get("jwt_access_token")

        if not token:
            token = session.get("jwt_token")

        if token:
            payload = decode_jwt_token(token)
            if payload:
                g.user = payload
                session['logged_in'] = True
                session['username'] = payload.get('username')
                session['is_admin'] = payload.get('is_admin', False)
                return None

        # Unauthenticated request
        if _is_api_request() or request.path.startswith("/hostel/api/"):
            return jsonify({"error": "Authentication required", "message": "Valid JWT token required"}), 401

        return redirect(url_for("auth.login"))

    @app.route("/")
    def index_redirect():
        """Redirect root URL directly to Girls Hostel Warden Dashboard."""
        return redirect(url_for("hostel.dashboard"))

    # ------------------------------------------------------------------
    # Health check — used by load balancers / container orchestrators
    # ------------------------------------------------------------------

    @app.route("/healthz")
    def healthz():
        return jsonify({"status": "ok", "service": "biosecure-ai-girls-hostel"}), 200

    logger.info("BioSecure AI Girls Hostel system initialised successfully.")
    return app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_api_request() -> bool:
    """Return True if the current request is an XHR / API call."""
    from flask import request

    return (
        request.path.startswith("/api/")
        or request.path.startswith("/hostel/api/")
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in request.headers.get("Accept", "")
    )
