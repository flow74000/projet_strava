# Fichier: app.py (Version avec fusion des données Strava + Intervals.icu)

import os
import requests
from datetime import date, timedelta, datetime
from flask import Flask, jsonify, request
from flask_cors import CORS
from stravalib.client import Client

app = Flask(__name__)
CORS(app)

# --- NOUVELLE FONCTION POUR LES DONNÉES DE FORME ---
def get_fitness_data():
    athlete_id = os.environ.get("INTERVALS_ATHLETE_ID")
    api_key = os.environ.get("INTERVALS_API_KEY")
    pma = float(os.environ.get("PMA_WATTS", 0))
    weight = float(os.environ.get("DEFAULT_WEIGHT", 70))

    if not all([athlete_id, api_key, pma]):
        return None

    today = date.today()
    ninety_days_ago = today - timedelta(days=90)
    
    url = f"https://intervals.icu/api/v1/athlete/{athlete_id}/wellness?oldest={ninety_days_ago}&newest={today}"
    
    try:
        response = requests.get(url, auth=('API_KEY', api_key))
        response.raise_for_status()
        wellness_data = response.json()
        
        if not wellness_data:
            return None

        latest_data = sorted(wellness_data, key=lambda x: x['id'], reverse=True)[0]
        
        ctl = latest_data.get('ctl')
        atl = latest_data.get('atl')
        form = ctl - atl if ctl is not None and atl is not None else None
        current_weight = latest_data.get('weight', weight)
        
        vo2max = ((0.01141 * pma + 0.435) / current_weight) * 1000 if current_weight > 0 else None

        return {
            "fitness": round(ctl) if ctl is not None else None,
            "fatigue": round(atl) if atl is not None else None,
            "form": round(form) if form is not None else None,
            "vo2max": round(vo2max, 1) if vo2max is not None else None
        }
    except Exception as e:
        print(f"Erreur API Intervals.icu: {e}")
        return None


@app.route("/api/strava")
def strava_handler():
    # ... (le début de la fonction avec l'authentification Strava reste identique) ...
    try:
        # --- APPEL À LA NOUVELLE FONCTION ---
        fitness_summary = get_fitness_data()
        
        # Le reste du code pour Strava est inchangé
        # ... (copiez ici le contenu du bloc try de votre version précédente) ...
        # ... (token_response, authed_client, activities, weekly_summary, etc.) ...

        token_response = Client().exchange_code_for_token(client_id=os.environ.get("STRAVA_CLIENT_ID"), client_secret=os.environ.get("STRAVA_CLIENT_SECRET"), code=request.args.get('code'))
        access_token = token_response['access_token']
        athlete_id = token_response['athlete']['id']
        authed_client = Client(access_token=access_token)
        activities = list(authed_client.get_activities(limit=50))
        today = date.today()
        start_of_week = today - timedelta(days=today.weekday())
        weekly_distance = sum(float(getattr(act, 'distance', 0)) for act in activities if act.start_date_local.date() >= start_of_week)
        weekly_summary = {"current": weekly_distance / 1000, "goal": 200}
        stats = authed_client.get_athlete_stats(athlete_id)
        ytd_distance = float(stats.ytd_ride_totals.distance)
        yearly_summary = {"current": ytd_distance / 1000, "goal": 8000}
        activities_json = [{'name': act.name, 'start_date_local': act.start_date_local.isoformat(), 'moving_time': str(getattr(act, 'moving_time', '0')), 'distance': float(getattr(act, 'distance', 0)), 'total_elevation_gain': float(getattr(act, 'total_elevation_gain', 0))} for act in activities[:10]]
        latest_activity_map_polyline, elevation_data = None, None
        if activities:
            if hasattr(activities[0], 'map') and activities[0].map.summary_polyline: latest_activity_map_polyline = activities[0].map.summary_polyline
            latest_activity_id = getattr(activities[0], 'id', None)
            if latest_activity_id:
                streams = authed_client.get_activity_streams(latest_activity_id, types=['distance', 'altitude'])
                if streams and 'distance' in streams and 'altitude' in streams: elevation_data = {'distance': streams['distance'].data, 'altitude': streams['altitude'].data}

        return jsonify({
            "activities": activities_json,
            "latest_activity_map": latest_activity_map_polyline,
            "elevation_data": elevation_data,
            "goals": { "weekly": weekly_summary, "yearly": yearly_summary },
            "fitness_summary": fitness_summary # On ajoute les nouvelles données
        })

    except Exception as e:
        # ... (gestion d'erreur identique) ...
        import traceback
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500