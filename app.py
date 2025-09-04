# Fichier: app.py (Version avec toutes les statistiques détaillées)

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
            # --- MODIFICATION ICI : On ajoute toutes les statistiques ---
            activities_json.append({
                'name': getattr(activity, 'name', 'Activité sans nom'),
                'start_date_local': activity.start_date_local.isoformat() if hasattr(activity, 'start_date_local') else None,
                'moving_time': str(getattr(activity, 'moving_time', '0')),
                'distance': float(getattr(activity, 'distance', 0)),
                'total_elevation_gain': float(getattr(activity, 'total_elevation_gain', 0)),
                'average_speed': float(getattr(activity.average_speed, 'num', 0)),
                'max_speed': float(getattr(activity.max_speed, 'num', 0)),
                'has_heartrate': getattr(activity, 'has_heartrate', False),
                'average_heartrate': float(getattr(activity, 'average_heartrate', 0)),
                'max_heartrate': float(getattr(activity, 'max_heartrate', 0)),
                'average_watts': float(getattr(activity, 'average_watts', 0)),
                'max_watts': float(getattr(activity, 'max_watts', 0)),
                'map': {'summary_polyline': activity.map.summary_polyline} if hasattr(activity, 'map') and activity.map.summary_polyline else None
            })
            
        latest_activity_map_polyline = activities_json[0]['map']['summary_polyline'] if activities and activities_json[0].get('map') else None
        
        elevation_data = None
        if activities:
            latest_activity_id = getattr(activities[0], 'id', None)
            if latest_activity_id:
                streams = authed_client.get_activity_streams(
                    latest_activity_id, types=['distance', 'altitude']
                )
                if streams and 'distance' in streams and 'altitude' in streams:
                    elevation_data = { 'distance': streams['distance'].data, 'altitude': streams['altitude'].data }

        return jsonify({
            "activities": activities_json,
            "latest_activity_map": latest_activity_map_polyline,
            "elevation_data": elevation_data
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500