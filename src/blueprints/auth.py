"""
Authentication Blueprint (JWT & Supabase Auth) — BioSecure AI Girls Hostel.

Routes: /login, /logout, /register
All successful logins issue a signed JWT token and direct strictly to the Girls Hostel portal.
"""

from flask import Blueprint, jsonify, make_response, redirect, render_template, request, session, url_for
from src.utils.db import supabase, supabase_admin, is_valid_email
from src.utils.auth_helpers import generate_jwt_token
from supabase import AuthApiError

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # Accept JSON or form data
        if request.is_json:
            data = request.get_json() or {}
            email = data.get('email', '').strip()
            password = data.get('password', '').strip()
        else:
            email = request.form.get('email', '').strip()
            password = request.form.get('password', '').strip()

        if not email or not password:
            if request.is_json:
                return jsonify({"error": "Email and password required"}), 400
            return render_template('login.html', error="Email and password required")

        try:
            # Authenticate with Supabase Auth
            auth_response = supabase.auth.sign_in_with_password({
                "email": email,
                "password": password
            })
            
            user = auth_response.user
            metadata = user.user_metadata or {}
            is_admin = metadata.get('is_admin', False)
            username = metadata.get('username', email.split('@')[0])
            user_id = user.id

            # Issue signed JWT token
            jwt_token = generate_jwt_token(
                user_id=user_id,
                email=email,
                username=username,
                is_admin=is_admin
            )

            # Store in session and HTTP-only cookie
            session['logged_in'] = True
            session['username'] = username
            session['is_admin'] = is_admin
            session['user_id'] = user_id
            session['jwt_token'] = jwt_token

            if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                resp = make_response(jsonify({
                    "status": "success",
                    "token": jwt_token,
                    "redirect": url_for('hostel.dashboard')
                }))
                resp.set_cookie('jwt_access_token', jwt_token, httponly=True, samesite='Lax')
                return resp, 200

            resp = make_response(redirect(url_for('hostel.dashboard')))
            resp.set_cookie('jwt_access_token', jwt_token, httponly=True, samesite='Lax')
            return resp

        except Exception as e:
            error_message = str(e)
            if "AuthApiError" in error_message or hasattr(e, 'message'):
                error_message = getattr(e, 'message', str(e))
            else:
                error_message = "Invalid email or password"

            if request.is_json:
                return jsonify({"error": error_message}), 401
            return render_template('login.html', error=error_message)

    # GET request — if already authenticated, direct directly to hostel page
    jwt_token = session.get('jwt_token') or request.cookies.get('jwt_access_token')
    if jwt_token:
        from src.utils.auth_helpers import decode_jwt_token
        payload = decode_jwt_token(jwt_token)
        if payload:
            return redirect(url_for('hostel.dashboard'))

    error = request.args.get('error')
    info = request.args.get('info')
    return render_template('login.html', error=error, info=info)


@auth_bp.route('/logout')
def logout():
    try:
        if 'access_token' in session:
            supabase.auth.sign_out()
    except Exception:
        pass
    
    session.clear()
    resp = make_response(redirect(url_for('auth.login')))
    resp.delete_cookie('jwt_access_token')
    return resp


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """Admin-only user-creation route."""
    if not session.get('is_admin'):
        return render_template('login.html', error="Admin access required to create new users")

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        email    = request.form.get('email', '').strip()

        if not username or not password or not email:
            return render_template('register.html', error="All fields are required")

        if not is_valid_email(email):
            return render_template('register.html', error="Invalid email format")

        if len(password) < 8:
            return render_template('register.html', error="Password must be at least 8 characters")

        try:
            supabase_admin.auth.admin.create_user({
                "email": email,
                "password": password,
                "email_confirm": True,
                "user_metadata": {
                    "username": username,
                    "is_admin": False
                }
            })
            
            return render_template('register.html', success=f"User {username} successfully created.")
            
        except AuthApiError as e:
            return render_template('register.html', error=str(e.message))
        except Exception as e:
            return render_template('register.html', error="An error occurred while creating the user.")

    return render_template('register.html')


@auth_bp.route('/login/oauth/<provider>')
def oauth_login(provider):
    """Initiate OAuth sign-in flow."""
    prov = 'linkedin_oidc' if provider == 'linkedin' else provider
    redirect_url = url_for('auth.callback', _external=True)
    try:
        res = supabase.auth.sign_in_with_oauth({
            "provider": prov,
            "options": {
                "redirect_to": redirect_url
            }
        })
        storage_key = getattr(supabase.auth, "_storage_key", "supabase.auth.token")
        code_verifier = supabase.auth._storage.get_item(f"{storage_key}-code-verifier")
        if code_verifier:
            session['code_verifier'] = code_verifier
        return redirect(res.url)
    except Exception as e:
        return redirect(url_for('auth.login', error=str(e)))


@auth_bp.route('/auth/callback')
def callback():
    """Handle OAuth callback and session exchange."""
    code = request.args.get('code')
    error_description = request.args.get('error_description')
    
    if error_description:
        return redirect(url_for('auth.login', error=error_description))
        
    if code:
        try:
            code_verifier = session.pop('code_verifier', None)
            exchange_params = {"auth_code": code}
            if code_verifier:
                exchange_params["code_verifier"] = code_verifier

            res = supabase.auth.exchange_code_for_session(exchange_params)
            user = res.user
            metadata = user.user_metadata or {}

            if 'username' not in metadata:
                try:
                    supabase_admin.auth.admin.delete_user(user.id)
                except Exception:
                    pass
                return redirect(url_for('auth.login', error="Access denied. Your account is not registered in this system."))

            is_admin = metadata.get('is_admin', False)
            username = metadata.get('username', user.email.split('@')[0])
            user_id = user.id

            jwt_token = generate_jwt_token(user_id=user_id, email=user.email, username=username, is_admin=is_admin)

            session['logged_in'] = True
            session['username'] = username
            session['is_admin'] = is_admin
            session['user_id'] = user_id
            session['jwt_token'] = jwt_token

            resp = make_response(redirect(url_for('hostel.dashboard')))
            resp.set_cookie('jwt_access_token', jwt_token, httponly=True, samesite='Lax')
            return resp
        except Exception as e:
            return redirect(url_for('auth.login', error=f"Auth exchange failed: {e}"))

    return redirect(url_for('auth.login', error="No authentication code received"))
