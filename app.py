# Fichier: app.py (Version finale, synchronisation à la demande, sans worker)

import os
import requests
import traceback
import psycopg2
import polyline
from datetime import date, timedelta, datetime
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from stravalib.client import Client
from stravalib import exc

# Imports pour l'API Google Fit
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

app = Flask(__name__)
CORS(app)

# --- Fonctions de récupération de données ---

def get_fitness_data(latest_weight=None):
    """Récupère les données de forme depuis l'API Intervals.icu."""
    try:
        athlete_id_icu = os.environ.get("INTERVALS_ATHLETE_ID")
        api_key = os.environ.get("INTERVALS_API_KEY")
        pma = float(os.environ.get("PMA_WATTS", 0))
        default_weight = float(os.environ.get("DEFAULT_WEIGHT", 70))
        
        if not all([athlete_id_icu, api_key, pma]):
            return None, None
            
        today = date.today()
        history_start_date = today - timedelta(days=180)
        url = f"https://intervals.icu/api/v1/athlete/{athlete_id_icu}/wellness?oldest={history_start_date}&newest={today}"
        
        response = requests.get(url, auth=('API_KEY', api_key))
        response.raise_for_status()
        wellness_data = response.json()
        
        if not wellness_data:
            return None, None
            
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

def get_annual_progress_by_month(client):
    """Calcule la distance Strava totale par mois pour l'année en cours via l'API."""
    try:
        today = date.today()
        start_of_year = datetime(today.year, 1, 1)
        print(f"Récupération des activités Strava pour l'année {today.year}...")
        activities = client.get_activities(after=start_of_year)
        
        monthly_distances = [0] * 12
        for activity in activities:
            month_index = activity.start_date_local.month - 1
            distance_km = float(getattr(activity, 'distance', 0)) / 1000
            monthly_distances[month_index] += distance_km
            
        monthly_distances = [round(d) for d in monthly_distances]
        print(f"Distances mensuelles Strava calculées : {monthly_distances}")
        return monthly_distances
    except Exception as e:
        print(f"Erreur lors du calcul de la progression annuelle Strava : {e}")
        return [0] * 12

def get_weight_data():
    """Récupère les données de poids des 90 derniers jours depuis l'API Google Fit."""
    print("Récupération des données de poids depuis Google Fit...")
    SCOPES = ['https://www.googleapis.com/auth/fitness.body.read']
    token_path = '/etc/secrets/token.json' if os.path.exists('/etc/secrets/token.json') else 'token.json'

    try:
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        fitness_service = build('fitness', 'v1', credentials=creds)

        end_time = datetime.utcnow()
        start_time = end_time - timedelta(days=90)
        start_time_ns = int(start_time.timestamp() * 1e9)
        end_time_ns = int(end_time.timestamp() * 1e9)
        dataset_id = f"{start_time_ns}-{end_time_ns}"

        response = fitness_service.users().dataSources().datasets().get(
            userId='me', dataSourceId='derived:com.google.weight:com.google.android.gms:merge_weight', datasetId=dataset_id
        ).execute()

        weight_points = [{'date': datetime.fromtimestamp(int(p['startTimeNanos']) / 1e9).strftime('%Y-%m-%d'), 'weight': round(p['value'][0]['fpVal'], 2)} for p in response.get('point', [])]
        weight_points.sort(key=lambda x: x['date'])
        print(f"{len(weight_points)} points de données de poids récupérés.")
        return weight_points
    except FileNotFoundError:
        print("Fichier token.json introuvable pour Google Fit.")
        return None
    except Exception as e:
        print(f"Erreur lors de la récupération des données de poids depuis Google Fit: {e}")
        return None

# --- Routes pour servir les pages HTML ---

@app.route('/')
def serve_index():
    return send_from_directory('.', 'activities.html')

@app.route('/<path:path>')
def serve_static_files(path):
    return send_from_directory('.', path)

# --- Routes API ---

@app.route("/api/weight")
def weight_api_handler():
    """Route API pour la page Nutrition, appelle directement Google Fit."""
    try:
        weight_history = get_weight_data()
        return jsonify({"weightHistory": weight_history}) if weight_history is not None else (jsonify({"error": "Impossible de récupérer les données de poids"}), 500)
    except Exception as e:
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route("/api/strava")
def strava_handler():
    """
    Route API principale qui gère TOUT : authentification, synchronisation et compilation des données.
    """
    try:
        # --- Authentification Strava ---
        client = Client()
        token_response = client.exchange_code_for_token(client_id=os.environ.get("STRAVA_CLIENT_ID"), client_secret=os.environ.get("STRAVA_CLIENT_SECRET"), code=request.args.get('code'))
        authed_client = Client(access_token=token_response['access_token'])
        
        # --- Synchronisation des activités Strava ---
        print("Début de la synchronisation intelligente avec Strava...")
        DATABASE_URL = os.environ.get('DATABASE_URL')
        conn = psycopg2.connect(DATABASE_URL)
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(start_date) FROM activities")
            result = cur.fetchone()
            last_activity_date = result[0] if result else None
            
            activities_iterator = authed_client.get_activities(after=last_activity_date)
            new_activities = list(activities_iterator)

            if new_activities:
                print(f"{len(new_activities)} nouvelle(s) activité(s) trouvée(s).")
                for activity in reversed(new_activities):
                    moving_time_obj = getattr(activity, 'moving_time', None)
                    moving_time_seconds = int(moving_time_obj.total_seconds()) if hasattr(moving_time_obj, 'total_seconds') else 0
                    cur.execute(
                        """
                        INSERT INTO activities (id, name, start_date, distance, moving_time_seconds, elevation_gain)
                        VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING
                        """,
                        (activity.id, activity.name, activity.start_date_local, float(getattr(activity, 'distance', 0)) / 1000, moving_time_seconds, float(getattr(activity, 'total_elevation_gain', 0)))
                    )
                conn.commit()
            else:
                print("Base de données Strava déjà à jour.")

        # --- Lecture des données depuis la base de données ---
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, start_date, moving_time_seconds, distance, elevation_gain FROM activities ORDER BY start_date DESC LIMIT 10")
            activities_from_db = [{"name": r[1], "id": r[0], "start_date_local": r[2].isoformat(), "moving_time": str(timedelta(seconds=int(r[3]))), "distance": r[4] * 1000, "total_elevation_gain": r[5]} for r in cur.fetchall()]
        conn.close()
        
        if activities_from_db:
            try:
                streams = authed_client.get_activity_streams(activities_from_db[0]['id'], types=['latlng', 'altitude', 'distance'])
                if streams and 'latlng' in streams: activities_from_db[0]['map_polyline'] = polyline.encode(streams['latlng'].data)
                if streams and 'distance' in streams and 'altitude' in streams: activities_from_db[0]['elevation_data'] = {'distance': streams['distance'].data, 'altitude': streams['altitude'].data}
            except exc.ObjectNotFound: pass

        # --- Compilation de toutes les données ---
        weight_history = get_weight_data()
        latest_weight = weight_history[-1]['weight'] if weight_history and len(weight_history) > 0 else None
        
        fitness_summary, form_chart_data = get_fitness_data(latest_weight=latest_weight)
        annual_progress_data = get_annual_progress_by_month(authed_client)
        
        athlete = authed_client.get_athlete()
        stats = authed_client.get_athlete_stats(athlete.id)
        ytd_distance = float(stats.ytd_ride_totals.distance) / 1000
        yearly_summary = {"current": ytd_distance, "goal": 8000}
        
        today = date.today()
        start_of_week = today - timedelta(days=today.weekday())
        weekly_distance = sum(act['distance'] / 1000 for act in activities_from_db if datetime.fromisoformat(act['start_date_local']).date() >= start_of_week)
        weekly_summary = {"current": weekly_distance, "goal": 200}

        return jsonify({
            "activities": activities_from_db,
            "goals": {"weekly": weekly_summary, "yearly": yearly_summary},
            "fitness_summary": fitness_summary,
            "form_chart_data": form_chart_data,
            "annualProgressData": annual_progress_data
        })

    except Exception as e:
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500