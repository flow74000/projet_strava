# Fichier: app.py (Version avec calcul de l'objectif hebdomadaire)

import os
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
        authed_client = Client(access_token=access_token)
        # On augmente la limite pour être sûr d'avoir toutes les activités de la semaine
        activities = list(authed_client.get_activities(limit=50)) 
        
        # --- AJOUT : Calcul du total hebdomadaire ---
        today = date.today()
        start_of_week = today - timedelta(days=today.weekday())
        weekly_distance = 0
        for activity in activities:
            activity_date = datetime.fromisoformat(activity.start_date_local.isoformat()).date()
            if activity_date >= start_of_week:
                weekly_distance += float(getattr(activity, 'distance', 0))
        
        weekly_summary = {
            "current": weekly_distance / 1000, # en km
            "goal": 200
        }
        # --- FIN DE L'AJOUT ---
        
        # Le reste du code est inchangé
        activities_json = []
        for activity in activities[:10]: # On ne renvoie que les 10 dernières au frontend
            activities_json.append({
                'name': activity.name,
                'start_date_local': activity.start_date_local.isoformat(),
                'moving_time': str(getattr(activity, 'moving_time', '0')),
                'distance': float(getattr(activity, 'distance', 0)),
                'total_elevation_gain': float(getattr(activity, 'total_elevation_gain', 0))
            })
        
        # ... (code pour la carte et le graphique d'élévation inchangé)
        latest_activity_map_polyline = None
        elevation_data = None
        if activities:
            if hasattr(activities[0], 'map') and activities[0].map and activities[0].map.summary_polyline:
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
            "weekly_summary": weekly_summary # Nouvelle donnée
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500