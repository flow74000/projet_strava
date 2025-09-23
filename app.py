# Fichier: app.py (Version finale, RAPIDE et optimisée)

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

def get_fitness_data():
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
        last_known_weight = next((entry.get('weight') for entry in wellness_data if entry.get('weight') is not None), default_weight)
        current_weight = latest_data.get('weight', last_known_weight)
        ctl, atl = latest_data.get('ctl'), latest_data.get('atl')
        form = ctl - atl if ctl is not None and atl is not None else None
        vo2max = ((0.01141 * pma + 0.435) / current_weight) * 1000 if current_weight and current_weight > 0 else None
        wellness_data.sort(key=lambda x: x['id'])
        summary = {"fitness": round(ctl) if ctl is not None else None, "fatigue": round(atl) if atl is not None else None, "form": round(form) if form is not None else None, "vo2max": round(vo2max, 1) if vo2max is not None else None}
        return summary, wellness_data
    except Exception as e:
        print(f"Erreur API Intervals.icu: {e}")
        return None, None

def get_annual_progress_by_month():
    """
    Lit les statistiques mensuelles pré-calculées depuis la base de données.
    C'est maintenant une fonction très rapide !
    """
    print("Lecture des statistiques mensuelles depuis la base de données...")
    try:
        DATABASE_URL = os.environ.get('DATABASE_URL')
        conn = psycopg2.connect(DATABASE_URL)
        current_year = datetime.now().year
        
        with conn.cursor() as cur:
            cur.execute("SELECT month, distance FROM monthly_stats WHERE year = %s ORDER BY month", (current_year,))
            results = cur.fetchall()
        
        conn.close()

        # Prépare un tableau de 12 mois avec des zéros
        monthly_distances = [0] * 12
        # Remplit le tableau avec les données de la DB
        for row in results:
            month_index = row[0] - 1
            monthly_distances[month_index] = int(row[1])

        print(f"Statistiques mensuelles récupérées : {monthly_distances}")
        return monthly_distances

    except Exception as e:
        print(f"Erreur lors de la lecture des statistiques mensuelles : {e}")
        return [0] * 12

def get_weight_data():
    """Récupère les données de poids des 90 derniers jours depuis l'API Google Fit."""
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
            userId='me',
            dataSourceId='derived:com.google.weight:com.google.android.gms:merge_weight',
            datasetId=dataset_id
        ).execute()

        weight_points = []
        for point in response.get('point', []):
            weight_kg = point['value'][0]['fpVal']
            timestamp_s = int(point['startTimeNanos']) / 1e9
            date_str = datetime.fromtimestamp(timestamp_s).strftime('%Y-%m-%d')
            weight_points.append({'date': date_str, 'weight': round(weight_kg, 1)})
        
        weight_points.sort(key=lambda x: x['date'])
        print(f"{len(weight_points)} points de données de poids récupérés depuis Google Fit.")
        return weight_points

    except FileNotFoundError:
        print("Fichier token.json introuvable. Veuillez lancer le script d'authentification.")
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


# --- Routes API pour les données ---

@app.route("/api/weight")
def weight_api_handler():
    try:
        weight_history = get_weight_data()
        if weight_history is not None:
            return jsonify({"weightHistory": weight_history})
        else:
            return jsonify({"error": "Impossible de récupérer les données de poids"}), 500
    except Exception as e:
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route("/api/strava")
def strava_handler():
    """
    Route API qui lit les données pré-synchronisées et les compile.
    Cette fonction est maintenant beaucoup plus rapide !
    """
    try:
        # Authentification Strava (reste nécessaire pour les stats et polylines)
        client = Client()
        token_response = client.exchange_code_for_token(client_id=os.environ.get("STRAVA_CLIENT_ID"), client_secret=os.environ.get("STRAVA_CLIENT_SECRET"), code=request.args.get('code'))
        authed_client = Client(access_token=token_response['access_token'])
        
        # --- LA SYNCHRONISATION LENTE A ÉTÉ RETIRÉE D'ICI ---
        print("Lecture des données depuis la base de données...")

        # Lecture des 10 dernières activités depuis la base de données
        DATABASE_URL = os.environ.get('DATABASE_URL')
        conn = psycopg2.connect(DATABASE_URL)
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, start_date, moving_time_seconds, distance, elevation_gain FROM activities ORDER BY start_date DESC LIMIT 10")
            activities_from_db = [
                {
                    "name": r[1], "id": r[0], "start_date_local": r[2].isoformat(),
                    "moving_time": str(timedelta(seconds=int(r[3]))), "distance": r[4] * 1000,
                    "total_elevation_gain": r[5]
                } for r in cur.fetchall()
            ]
        conn.close()
        
        # Le worker s'occupe des polylines, mais pour le détail on peut le faire ici
        if activities_from_db:
             try:
                streams = authed_client.get_activity_streams(activities_from_db[0]['id'], types=['latlng', 'altitude', 'distance'])
                if streams and 'latlng' in streams:
                    activities_from_db[0]['map_polyline'] = polyline.encode(streams['latlng'].data)
                if streams and 'distance' in streams and 'altitude' in streams:
                    activities_from_db[0]['elevation_data'] = {'distance': streams['distance'].data, 'altitude': streams['altitude'].data}
             except exc.ObjectNotFound: pass


        # Le reste du code qui compile les données est identique
        fitness_summary, form_chart_data = get_fitness_data()
        
        athlete = authed_client.get_athlete()
        stats = authed_client.get_athlete_stats(athlete.id)
        ytd_distance = float(stats.ytd_ride_totals.distance) / 1000
        yearly_summary = {"current": ytd_distance, "goal": 8000}
        
        today = date.today()
        start_of_week = today - timedelta(days=today.weekday())
        weekly_distance = sum(act['distance'] / 1000 for act in activities_from_db if datetime.fromisoformat(act['start_date_local']).date() >= start_of_week)
        weekly_summary = {"current": weekly_distance, "goal": 200}
        
        # On appelle la nouvelle fonction rapide qui ne prend plus d'argument
        annual_progress_data = get_annual_progress_by_month()

        return jsonify({
            "activities": activities_from_db,
            "goals": { "weekly": weekly_summary, "yearly": yearly_summary },
            "fitness_summary": fitness_summary,
            "form_chart_data": form_chart_data,
            "annualProgressData": annual_progress_data
        })

    except Exception as e:
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500