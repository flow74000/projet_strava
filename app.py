# Fichier: app.py (Version finale enrichie)

import os
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
        activities = list(authed_client.get_activities(limit=10))
        
        activities_json = []
        for activity in activities:
            # On construit un dictionnaire complet pour chaque activité
            activities_json.append({
                'name': activity.name,
                'type': activity.type,
                'start_date_local': activity.start_date_local.isoformat(),
                'moving_time': str(activity.moving_time),
                'distance': float(activity.distance or 0),
                'total_elevation_gain': float(activity.total_elevation_gain or 0),
                'average_speed': float(activity.average_speed or 0),
                'max_speed': float(activity.max_speed or 0),
                'has_heartrate': activity.has_heartrate,
                'average_heartrate': float(activity.average_heartrate or 0),
                'max_heartrate': float(activity.max_heartrate or 0),
                'average_watts': float(activity.average_watts or 0),
                'max_watts': float(activity.max_watts or 0),
                'average_cadence': float(activity.average_cadence or 0),
                'calories': float(activity.calories or 0),
                'map': {'summary_polyline': activity.map.summary_polyline} if activity.map else None
            })
            
        # On récupère les données du graphique pour la dernière activité
        elevation_data = None
        if activities:
            latest_activity = activities[0]
            streams = authed_client.get_activity_streams(
                latest_activity.id, 
                types=['distance', 'altitude']
            )
            if 'distance' in streams and 'altitude' in streams:
                elevation_data = {
                    'distance': streams['distance'].data,
                    'altitude': streams['altitude'].data
                }

        return jsonify({
            "activities": activities_json,
            "elevation_data": elevation_data
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500