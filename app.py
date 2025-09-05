# Fichier: app.py (Version avec débogage d'erreur forcé)

import os
import traceback # <-- AJOUT POUR LE DÉBOGAGE
from datetime import date, timedelta, datetime
from flask import Flask, jsonify, request
from flask_cors import CORS
from stravalib.client import Client

app = Flask(__name__)
CORS(app)

@app.route("/api/strava")
def strava_handler():
    STRAVA_CLIENT_ID = os.environ.get("STRAVA_CLIENT_ID")
    STRAVA_CLIENT_SECRET = os.environ.get("STRAVA_CLIENT_SECRET")
    
    code = request.args.get('code')
    if not code:
        return jsonify({'error': 'Code manquant'}), 400

    client = Client()
    try:
        token_response = client.exchange_code_for_token(
            client_id=STRAVA_CLIENT_ID,
            client_secret=STRAVA_CLIENT_SECRET,
            code=code
        )
        
        access_token = token_response['access_token']
        athlete_id = token_response['athlete']['id']
        authed_client = Client(access_token=access_token)
        
        activities = list(authed_client.get_activities(limit=50))
        
        today = date.today()
        start_of_week = today - timedelta(days=today.weekday())
        weekly_distance = 0
        for activity in activities:
            # La date de l'activité est un objet datetime, on extrait juste la date
            activity_date = activity.start_date_local.date()
            if activity_date >= start_of_week:
                weekly_distance += float(getattr(activity, 'distance', 0))
        
        weekly_summary = {"current": weekly_distance / 1000, "goal": 200}

        stats = authed_client.get_athlete_stats(athlete_id)
        ytd_distance = float(stats.ytd_ride_totals.distance)
        yearly_summary = {"current": ytd_distance / 1000, "goal": 8000}

        activities_json = []
        for activity in activities[:10]:
            activities_json.append({
                'name': activity.name, 'start_date_local': activity.start_date_local.isoformat(),
                'moving_time': str(getattr(activity, 'moving_time', '0')),
                'distance': float(getattr(activity, 'distance', 0)),
                'total_elevation_gain': float(getattr(activity, 'total_elevation_gain', 0))
            })
        
        latest_activity_map_polyline, elevation_data = None, None
        if activities:
            if hasattr(activities[0], 'map') and activities[0].map.summary_polyline:
                latest_activity_map_polyline = activities[0].map.summary_polyline
            latest_activity_id = getattr(activities[0], 'id', None)
            if latest_activity_id:
                streams = authed_client.get_activity_streams(latest_activity_id, types=['distance', 'altitude'])
                if streams and 'distance' in streams and 'altitude' in streams:
                    elevation_data = {'distance': streams['distance'].data, 'altitude': streams['altitude'].data}

        return jsonify({
            "activities": activities_json,
            "latest_activity_map": latest_activity_map_polyline,
            "elevation_data": elevation_data,
            "goals": { "weekly": weekly_summary, "yearly": yearly_summary }
        })

    except Exception as e:
        # --- AJOUT CRUCIAL ICI ---
        # On imprime l'erreur complète dans les logs de Render
        print("!!! ERREUR DÉTECTÉE DANS LE BLOC TRY/EXCEPT !!!")
        print(traceback.format_exc())
        # --- FIN DE L'AJOUT ---
        return jsonify({'error': str(e)}), 500