# Fichier: app.py (Version avec détection du monde Zwift)

import os
from datetime import date, timedelta, datetime
from flask import Flask, jsonify, request
from flask_cors import CORS
from stravalib.client import Client
import traceback

app = Flask(__name__)
CORS(app)

# --- NOUVELLE FONCTION HELPER ---
def get_zwift_world(activity_name):
    """Analyse le nom de l'activité pour trouver le monde Zwift."""
    name_lower = activity_name.lower()
    # Liste des mondes connus de Zwift (ceux supportés par zwiftmap)
    known_worlds = [
        'watopia', 'richmond', 'london', 'new york', 
        'innsbruck', 'yorkshire', 'crit city', 'france', 'paris', 'makuri islands', 'scotland'
    ]
    for world in known_worlds:
        if world in name_lower:
            # Cas spécial pour "new york" pour éviter une confusion avec "yorkshire"
            if world == 'yorkshire' and 'new york' in name_lower:
                continue
            return world.replace(' ', '') # zwiftmap n'aime pas les espaces
    return None

@app.route("/api/strava")
def strava_handler():
    try:
        # ... (début de la fonction identique : authentification, récupération des activités...)
        
        client = Client()
        token_response = client.exchange_code_for_token(client_id=os.environ.get("STRAVA_CLIENT_ID"), client_secret=os.environ.get("STRAVA_CLIENT_SECRET"), code=request.args.get('code'))
        access_token = token_response['access_token']
        authed_client = Client(access_token=access_token)
        athlete = authed_client.get_athlete()
        athlete_id = athlete.id
        activities = list(authed_client.get_activities(limit=10)) # On peut revenir à 10, le calcul annuel est plus efficace
        
        # Le reste du code est principalement inchangé, on ajoute juste 'zwift_world'
        
        activities_json = []
        for activity in activities:
            activities_json.append({
                'name': activity.name,
                'start_date_local': activity.start_date_local.isoformat(),
                'moving_time': str(getattr(activity, 'moving_time', '0')),
                'distance': float(getattr(activity, 'distance', 0)),
                'total_elevation_gain': float(getattr(activity, 'total_elevation_gain', 0))
            })
            
        latest_activity_map_polyline, elevation_data, zwift_world = None, None, None
        if activities:
            latest_activity = activities[0]
            # --- AJOUT : On détecte le monde Zwift ---
            zwift_world = get_zwift_world(latest_activity.name)

            if hasattr(latest_activity, 'map') and latest_activity.map and latest_activity.map.summary_polyline:
                latest_activity_map_polyline = latest_activity.map.summary_polyline
            
            latest_activity_id = getattr(latest_activity, 'id', None)
            if latest_activity_id:
                streams = authed_client.get_activity_streams(latest_activity_id, types=['distance', 'altitude'])
                if streams and 'distance' in streams and 'altitude' in streams:
                    elevation_data = {'distance': streams['distance'].data, 'altitude': streams['altitude'].data}

        return jsonify({
            "activities": activities_json,
            "latest_activity_map": latest_activity_map_polyline,
            "elevation_data": elevation_data,
            "zwift_world": zwift_world # Nouvelle donnée
        })

    except Exception as e:
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500