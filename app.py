# Fichier: app.py (Version finale avec gestion des sessions)

import os
import requests
import traceback
import psycopg2
import polyline
from datetime import date, timedelta, datetime, timezone
from flask import Flask, jsonify, request, send_from_directory, session, redirect
from flask_cors import CORS
from stravalib.client import Client
from stravalib import exc
from collections import defaultdict
from flask_session import Session # Nouvel import

# Imports pour l'API Google Fit
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

app = Flask(__name__)

# --- CONFIGURATION DES SESSIONS ---
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY")
app.config["SESSION_TYPE"] = "filesystem" 
app.config["SESSION_PERMANENT"] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30) # La session dure 30 jours
Session(app)
# --------------------------------

cors = CORS(app, resources={
    r"/api/*": {
        "origins": "https://projet-strava.onrender.com"
    }
})

# --- Fonctions de récupération de données (inchangées) ---

def get_fitness_data(latest_weight=None):
    """Récupère les données de forme depuis l'API Intervals.icu."""
    try:
        athlete_id_icu = os.environ.get("INTERVALS_ATHLETE_ID")
        api_key = os.environ.get("INTERVALS_API_KEY")
        pma = float(os.environ.get("PMA_WATTS", 0))
        default_weight = float(os.environ.get("DEFAULT_WEIGHT", 70))
        if not all([athlete_id_icu, api_key, pma]): return None, None
        today = date.today()
        history_start_date = today - timedelta(days=180)
        url = f"https://intervals.icu/api/v1/athlete/{athlete_id_icu}/wellness?oldest={history_start_date}&newest={today}"
        response = requests.get(url, auth=('API_KEY', api_key))
        response.raise_for_status()
        wellness_data = response.json()
        if not wellness_data: return None, None
        wellness_data.sort(key=lambda x: x['id'], reverse=True)
        latest_data = wellness_data[0]
        current_weight = latest_weight if latest_weight else default_weight
        ctl, atl = latest_data.get('ctl'), latest_data.get('atl')
        form = ctl - atl if ctl is not None and atl is not None else None
        vo2max = ((0.01141 * pma + 0.435) / current_weight) * 1000 if current_weight and current_weight > 0 else None
        wellness_data.sort(key=lambda x: x['id'])
        summary = {"fitness": round(ctl) if ctl is not None else None, "fatigue": round(atl) if atl is not None else None, "form": round(form) if form is not None else None, "vo2max": round(vo2max, 1) if vo2max is not None else None}
        return summary, wellness_data
    except Exception as e:
        print(f"Erreur API Intervals.icu: {e}")
        return None, None

def get_all_years_progress(conn):
    """Calcule la distance cumulative jour par jour pour chaque année."""
    print("Calcul de la progression de toutes les années...")
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT EXTRACT(YEAR FROM start_date) as year, start_date, distance FROM activities WHERE distance > 0")
            all_activities = cur.fetchall()
        
        yearly_data = defaultdict(lambda: defaultdict(float))
        for year, start_date, distance in all_activities:
            day_of_year = start_date.timetuple().tm_yday
            yearly_data[int(year)][day_of_year] += float(distance)
            
        processed_data = {}
        for year, daily_distances in yearly_data.items():
            cumulative_distance = 0
            year_progress = [0] * 366
            for day in range(1, 367):
                cumulative_distance += daily_distances.get(day, 0)
                year_progress[day-1] = round(cumulative_distance, 2)
            processed_data[year] = year_progress
        return processed_data
    except Exception as e:
        print(f"Erreur lors du calcul de la progression multi-années : {e}")
        return {}

def get_weight_data():
    """Récupère les données de poids des 90 derniers jours depuis l'API Google Fit."""
    print("Récupération des données de poids depuis Google Fit...")
    SCOPES = ['https://www.googleapis.com/auth/fitness.body.read']
    token_path = '/etc/secrets/token.json' if os.path.exists('/etc/secrets/token.json') else 'token.json'
    try:
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        fitness_service = build('fitness', 'v1', credentials=creds)
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(days=90)
        start_time_ns = int(start_time.timestamp() * 1e9)
        end_time_ns = int(end_time.timestamp() * 1e9)
        dataset_id = f"{start_time_ns}-{end_time_ns}"
        response = fitness_service.users().dataSources().datasets().get(
            userId='me', dataSourceId='derived:com.google.weight:com.google.android.gms:merge_weight', datasetId=dataset_id
        ).execute()
        weight_points = [{'date': datetime.fromtimestamp(int(p['startTimeNanos']) / 1e9).strftime('%Y-%m-%d'), 'weight': round(p['value'][0]['fpVal'], 2)} for p in response.get('point', [])]
        weight_points.sort(key=lambda x: x['date'])
        return weight_points
    except FileNotFoundError:
        print("Fichier token.json introuvable pour Google Fit.")
        return None
    except Exception as e:
        print(f"Erreur lors de la récupération des données de poids depuis Google Fit: {e}")
        return None

# --- Routes pour servir les pages HTML ---
@app.route('/')
def serve_index(): return send_from_directory('.', 'activities.html')

@app.route('/<path:path>')
def serve_static_files(path): return send_from_directory('.', path)

# --- NOUVELLES ROUTES POUR L'AUTHENTIFICATION ---
@app.route("/api/check_auth")
def check_auth():
    """Vérifie si l'utilisateur a une session valide."""
    if 'strava_token' in session and datetime.now().timestamp() < session.get('strava_token', {}).get('expires_at', 0):
        return jsonify({"authenticated": True})
    return jsonify({"authenticated": False})

@app.route("/api/login")
def login():
    """Redirige l'utilisateur vers la page d'autorisation de Strava."""
    client = Client()
    authorize_url = client.authorization_url(
        client_id=os.environ.get("STRAVA_CLIENT_ID"),
        redirect_uri="https://projet-strava.onrender.com/activities.html",
        scope=['read', 'activity:read_all']
    )
    return redirect(authorize_url)

@app.route("/api/logout")
def logout():
    """Efface la session de l'utilisateur."""
    session.clear()
    return jsonify({"status": "logged_out"})


# --- ROUTES API POUR LES DONNÉES ---
@app.route("/api/yearly_progress")
def yearly_progress_handler():
    try:
        DATABASE_URL = os.environ.get('DATABASE_URL')
        conn = psycopg2.connect(DATABASE_URL)
        progress_data = get_all_years_progress(conn)
        conn.close()
        return jsonify(progress_data)
    except Exception as e:
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route("/api/weight")
def weight_api_handler():
    try:
        weight_history = get_weight_data()
        return jsonify({"weightHistory": weight_history}) if weight_history is not None else (jsonify({"error": "Impossible de récupérer les données de poids"}), 500)
    except Exception as e:
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route("/api/activity/<int:activity_id>")
def activity_detail_handler(activity_id):
    try:
        if 'strava_token' not in session:
            return jsonify({"error": "Non authentifié"}), 401
            
        token_response = session['strava_token']
        authed_client = Client(access_token=token_response['access_token'])

        print(f"Récupération des streams pour l'activité ID: {activity_id}")
        streams = authed_client.get_activity_streams(activity_id, types=['latlng', 'altitude', 'distance'])
        details = {}
        if streams and 'latlng' in streams:
            details['map_polyline'] = polyline.encode(streams['latlng'].data)
        if streams and 'distance' in streams and 'altitude' in streams:
            details['elevation_data'] = {'distance': streams['distance'].data, 'altitude': streams['altitude'].data}
        return jsonify(details)
    except Exception as e:
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route("/api/strava")
def strava_handler():
    try:
        authed_client = None
        code = request.args.get('code')

        if code:
            print("Nouvelle authentification via code, échange contre des tokens...")
            client = Client()
            token_response = client.exchange_code_for_token(client_id=os.environ.get("STRAVA_CLIENT_ID"), client_secret=os.environ.get("STRAVA_CLIENT_SECRET"), code=code)
            session['strava_token'] = token_response
            authed_client = Client(access_token=token_response['access_token'])
        
        elif 'strava_token' in session:
            print("Utilisateur authentifié via session.")
            token_response = session['strava_token']
            client = Client()
            
            if datetime.now().timestamp() > token_response['expires_at']:
                print("Token expiré, rafraîchissement...")
                new_token = client.refresh_access_token(client_id=os.environ.get("STRAVA_CLIENT_ID"), client_secret=os.environ.get("STRAVA_CLIENT_SECRET"), refresh_token=token_response['refresh_token'])
                session['strava_token'] = new_token
                authed_client = Client(access_token=new_token['access_token'])
                print("Token rafraîchi.")
            else:
                authed_client = Client(access_token=token_response['access_token'])
        
        if not authed_client:
            return jsonify({"error": "Utilisateur non authentifié"}), 401

        # --- Le reste de la fonction (synchronisation, etc.) est le même ---
        print("Début de la synchronisation intelligente avec Strava...")
        DATABASE_URL = os.environ.get('DATABASE_URL')
        conn = psycopg2.connect(DATABASE_URL)
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(start_date) FROM activities")
            result = cur.fetchone()
            last_activity_date = result[0] if result and result[0] is not None else None
            
            sync_start_time = None
            if last_activity_date:
                sync_start_time = last_activity_date - timedelta(minutes=5)
            
            activities_iterator = authed_client.get_activities(after=sync_start_time)
            new_activities = list(activities_iterator)

            if new_activities:
                print(f"{len(new_activities)} nouvelle(s) activité(s) trouvée(s).")
                for activity in reversed(new_activities):
                    moving_time_obj = getattr(activity, 'moving_time', None) or getattr(activity, 'elapsed_time', None)
                    duration_seconds = 0
                    if moving_time_obj:
                        if hasattr(moving_time_obj, 'total_seconds'): duration_seconds = int(moving_time_obj.total_seconds())
                        else: duration_seconds = int(moving_time_obj)
                    
                    streams = authed_client.get_activity_streams(activity.id, types=['latlng'])
                    encoded_polyline = polyline.encode(streams['latlng'].data) if streams and 'latlng' in streams else None
                    
                    cur.execute(
                        """
                        INSERT INTO activities (id, name, start_date, distance, moving_time_seconds, elevation_gain, polyline)
                        VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO UPDATE 
                        SET moving_time_seconds = EXCLUDED.moving_time_seconds, distance = EXCLUDED.distance, elevation_gain = EXCLUDED.elevation_gain, polyline = EXCLUDED.polyline;
                        """,
                        (activity.id, activity.name, activity.start_date_local, float(getattr(activity, 'distance', 0)) / 1000, duration_seconds, float(getattr(activity, 'total_elevation_gain', 0)), encoded_polyline)
                    )
                conn.commit()
            else:
                print("Base de données Strava déjà à jour.")

        with conn.cursor() as cur:
            cur.execute("SELECT id, name, start_date, moving_time_seconds, distance, elevation_gain, polyline FROM activities ORDER BY start_date DESC LIMIT 10")
            activities_from_db = [{"name": r[1], "id": r[0], "start_date_local": r[2].isoformat(), "moving_time": str(timedelta(seconds=int(r[3] or 0))), "distance": r[4] * 1000, "total_elevation_gain": r[5], "map_polyline": r[6]} for r in cur.fetchall()]
        
        if activities_from_db and not activities_from_db[0].get('map_polyline'):
            try:
                streams = authed_client.get_activity_streams(activities_from_db[0]['id'], types=['altitude', 'distance'])
                if streams and 'distance' in streams and 'altitude' in streams:
                    activities_from_db[0]['elevation_data'] = {'distance': streams['distance'].data, 'altitude': streams['altitude'].data}
            except exc.ObjectNotFound: pass

        weight_history = get_weight_data()
        latest_weight = weight_history[-1]['weight'] if weight_history and len(weight_history) > 0 else None
        
        fitness_summary, form_chart_data = get_fitness_data(latest_weight=latest_weight)
        
        athlete = authed_client.get_athlete()
        stats = authed_client.get_athlete_stats(athlete.id)
        ytd_distance = float(stats.ytd_ride_totals.distance) / 1000
        yearly_summary = {"current": ytd_distance, "goal": 8000}
        
        today = date.today()
        start_of_week = today - timedelta(days=today.weekday())
        weekly_distance = sum(act['distance'] / 1000 for act in activities_from_db if datetime.fromisoformat(act['start_date_local']).date() >= start_of_week)
        weekly_summary = {"current": weekly_distance, "goal": 200}
        
        conn.close()

        return jsonify({
            "activities": activities_from_db,
            "goals": {"weekly": weekly_summary, "yearly": yearly_summary},
            "fitness_summary": fitness_summary,
            "form_chart_data": form_chart_data,
        })

    except Exception as e:
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500