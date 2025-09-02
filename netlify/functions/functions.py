# Fichier : netlify/functions/functions.py

import json
import os
from stravalib.client import Client

# Le décorateur @builder a été retiré, il n'est pas nécessaire
def handler(event, context):
    # On récupère les identifiants depuis les variables d'environnement de Netlify
    STRAVA_CLIENT_ID = os.environ.get("STRAVA_CLIENT_ID")
    STRAVA_CLIENT_SECRET = os.environ.get("STRAVA_CLIENT_SECRET")
    
    # On récupère le code temporaire envoyé par le front-end
    code = event['queryStringParameters'].get('code')

    if not code:
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'Code manquant'})
        }

    client = Client()
    try:
        # Échange du code contre un token
        token_response = client.exchange_code_for_token(
            client_id=STRAVA_CLIENT_ID,
            client_secret=STRAVA_CLIENT_SECRET,
            code=code
        )
        access_token = token_response['access_token']
        
        # Utilisation du token pour récupérer les activités
        authed_client = Client(access_token=access_token)
        activities = list(authed_client.get_activities(limit=10))
        
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

        # On prépare les données pour les renvoyer en format JSON
        activities_json = []
        for activity in activities:
            # Conversion des objets Quanty en float pour la sérialisation JSON
            distance_meters = float(activity.distance)
            elevation_meters = float(activity.total_elevation_gain)
            avg_speed_mps = float(activity.average_speed) if activity.average_speed else 0
            max_speed_mps = float(activity.max_speed) if activity.max_speed else 0
            
            activities_json.append({
                'name': activity.name,
                'start_date_local': activity.start_date_local.strftime('%A %d %B %Y'),
                'moving_time': str(activity.moving_time),
                'distance': distance_meters,
                'total_elevation_gain': elevation_meters,
                'average_speed': avg_speed_mps,
                'max_speed': max_speed_mps,
                'has_heartrate': activity.has_heartrate,
                'average_heartrate': activity.average_heartrate,
                'max_heartrate': activity.max_heartrate,
                'average_watts': activity.average_watts,
                'max_watts': activity.max_watts,
                'average_cadence': activity.average_cadence,
                'calories': activity.calories,
                'map': {'summary_polyline': activity.map.summary_polyline}
            })

        return {
            'statusCode': 200,
            'body': json.dumps({
                "activities": activities_json,
                "elevation_data": elevation_data
            })
        }

    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }

