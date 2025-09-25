# Fichier: app.py (Version finale, avec toutes les corrections, y compris CORS)

import os
import requests
import traceback
import psycopg2
import polyline
from datetime import date, timedelta, datetime, timezone
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from stravalib.client import Client
from stravalib import exc
from collections import defaultdict

# Imports pour l'API Google Fit
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

app = Flask(__name__)
# --- CONFIGURATION CORS CORRECTE ET DÉFINITIVE ---
cors = CORS(app, resources={
    r"/api/*": {
        "origins": "https://projet-strava.onrender.com"
    }
})
# -------------------------------------------------

# --- Fonctions de récupération de données ---

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

# --- Routes API ---
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

@app.route("/api/strava")
def strava_handler():
    try:
        client = Client()
        token_response = client.exchange_code_for_token(client_id=os.environ.get("STRAVA_CLIENT_ID"), client_secret=os.environ.get("STRAVA_CLIENT_SECRET"), code=request.args.get('code'))
        authed_client = Client(access_token=token_response['access_token'])
        
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
                    moving_time_obj = getattr(activity, 'moving_time', None)
                    elapsed_time_obj = getattr(activity, 'elapsed_time', None)
                    duration_seconds = 0
                    if moving_time_obj:
                        duration_seconds = int(moving_time_obj.total_seconds())
                    elif elapsed_time_obj:
                        duration_seconds = int(elapsed_time_obj.total_seconds())
                    
                    cur.execute(
                        """
                        INSERT INTO activities (id, name, start_date, distance, moving_time_seconds, elevation_gain)
                        VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO UPDATE 
                        SET moving_time_seconds = EXCLUDED.moving_time_seconds,
                            distance = EXCLUDED.distance,
                            elevation_gain = EXCLUDED.elevation_gain;
                        """,
                        (activity.id, activity.name, activity.start_date_local, float(getattr(activity, 'distance', 0)) / 1000, duration_seconds, float(getattr(activity, 'total_elevation_gain', 0)))
                    )
                conn.commit()
            else:
                print("Base de données Strava déjà à jour.")

        with conn.cursor() as cur:
            cur.execute("SELECT id, name, start_date, moving_time_seconds, distance, elevation_gain, polyline FROM activities ORDER BY start_date DESC LIMIT 10")
            activities_from_db = [{"name": r[1], "id": r[0], "start_date_local": r[2].isoformat(), "moving_time": str(timedelta(seconds=int(r[3] or 0))), "distance": r[4] * 1000, "total_elevation_gain": r[5], "map_polyline": r[6]} for r in cur.fetchall()]
        
        if activities_from_db and not activities_from_db[0].get('map_polyline'):
            try:
                streams = authed_client.get_activity_streams(activities_from_db[0]['id'], types=['latlng', 'altitude', 'distance'])
                if streams and 'latlng' in streams: activities_from_db[0]['map_polyline'] = polyline.encode(streams['latlng'].data)
                if streams and 'distance' in streams and 'altitude' in streams: activities_from_db[0]['elevation_data'] = {'distance': streams['distance'].data, 'altitude': streams['altitude'].data}
            except exc.ObjectNotFound: pass

        weight_history = get_weight_data()
        latest_weight = weight_history[-1]['weight'] if weight_history and len(weight_history) > 0 else None
        
        fitness_summary, form_chart_data = get_fitness_data(latest_weight=latest_weight)
        
        athlete = authed_client.get_athlete()
        stats = authed_client.get_athlete_stats(athlete.id)
        
        conn.close()

        return jsonify({
            "activities": activities_from_db,
            "fitness_summary": fitness_summary,
            "form_chart_data": form_chart_data,
        })

    except Exception as e:
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500