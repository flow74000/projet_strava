# Fichier: app.py (Version simplifiée pour lecture seule)

import os
import traceback
import psycopg2
from datetime import date, timedelta, datetime
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from stravalib.client import Client # On en a encore besoin pour les stats et polylines
from stravalib import exc

# (Les fonctions get_fitness_data, get_annual_progress_by_month, et get_weight_data restent les mêmes)
# ... collez ici vos fonctions get_fitness_data, get_annual_progress_by_month, et get_weight_data ...

app = Flask(__name__)
CORS(app)

# (Les routes pour servir les pages HTML restent les mêmes)
# ... collez ici vos routes @app.route('/') et @app.route('/<path:path>') ...

# (La route pour l'API weight reste la même)
# ... collez ici votre route @app.route("/api/weight") ...


@app.route("/api/strava")
def strava_handler():
    """
    Route API qui lit les données pré-synchronisées et les compile.
    Cette fonction est maintenant beaucoup plus rapide !
    """
    try:
        # Authentification Strava (nécessaire pour les stats et les polylines)
        client = Client()
        token_response = client.exchange_code_for_token(client_id=os.environ.get("STRAVA_CLIENT_ID"), client_secret=os.environ.get("STRAVA_CLIENT_SECRET"), code=request.args.get('code'))
        print(token_response)
        authed_client = Client(access_token=token_response['access_token'])
        
        # --- La synchronisation a été retirée ! ---

        # Lecture des 10 dernières activités depuis la base de données
        DATABASE_URL = os.environ.get('DATABASE_URL')
        conn = psycopg2.connect(DATABASE_URL)
        with conn.cursor() as cur:
            # Note: on récupère la polyline depuis la DB si elle y est
            cur.execute("SELECT id, name, start_date, moving_time_seconds, distance, elevation_gain FROM activities ORDER BY start_date DESC LIMIT 10")
            activities_from_db = [
                {
                    "name": r[1], "id": r[0], "start_date_local": r[2].isoformat(),
                    "moving_time": str(timedelta(seconds=int(r[3]))), "distance": r[4] * 1000,
                    "total_elevation_gain": r[5]
                } for r in cur.fetchall()
            ]
        conn.close()

        # Le reste du code est quasi identique, il compile les données
        fitness_summary, form_chart_data = get_fitness_data()
        
        athlete = authed_client.get_athlete()
        stats = authed_client.get_athlete_stats(athlete.id)
        ytd_distance = float(stats.ytd_ride_totals.distance) / 1000
        yearly_summary = {"current": ytd_distance, "goal": 8000}
        
        today = date.today()
        start_of_week = today - timedelta(days=today.weekday())
        weekly_distance = sum(act['distance'] / 1000 for act in activities_from_db if datetime.fromisoformat(act['start_date_local']).date() >= start_of_week)
        weekly_summary = {"current": weekly_distance, "goal": 200}
        
        annual_progress_data = get_annual_progress_by_month(authed_client)

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