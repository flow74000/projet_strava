# Fichier: app.py (Version stable avec résumé, carte et graphique)

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
            activities_json.append({
                'name': activity.name,
                'start_date_local': activity.start_date_local.isoformat(),
                'moving_time': str(getattr(activity, 'moving_time', '0')),
                'distance': float(getattr(activity, 'distance', 0)),
                'total_elevation_gain': float(getattr(activity, 'total_elevation_gain', 0))
            })

        latest_activity_map_polyline = None
        elevation_data = None

        if activities:
            if hasattr(activities[0], 'map') and activities[0].map and activities[0].map.summary_polyline:
                latest_activity_map_polyline = activities[0].map.summary_polyline

            latest_activity_id = getattr(activities[0], 'id', None)
            if latest_activity_id:
                streams = authed_client.get_activity_streams(
                    latest_activity_id, types=['distance', 'altitude']
                )
                if streams and 'distance' in streams and 'altitude' in streams:
                    elevation_data = {
                        'distance': streams['distance'].data,
                        'altitude': streams['altitude'].data
                    }

        return jsonify({
            "activities": activities_json,
            "latest_activity_map": latest_activity_map_polyline,
            "elevation_data": elevation_data
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500