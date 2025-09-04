import os
import json
from stravalib.client import Client

def handler(event, context):
    try:
        # --- 1. Authentification Strava ---
        # N'écrivez JAMAIS vos identifiants en dur dans le code.
        # Utilisez les variables d'environnement de Netlify.
        client_id = os.environ.get('STRAVA_CLIENT_ID')
        client_secret = os.environ.get('STRAVA_CLIENT_SECRET')
        refresh_token = os.environ.get('STRAVA_REFRESH_TOKEN')

        if not all([client_id, client_secret, refresh_token]):
            raise ValueError("Les variables d'environnement Strava ne sont pas définies.")

        client = Client()

        # Rafraîchir le token d'accès
        refresh_response = client.refresh_access_token(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token
        )
        
        # Mettre à jour le client avec le nouveau token
        client.access_token = refresh_response['access_token']

        # --- 2. Récupération des activités ---
        activities = client.get_activities(limit=20) # Récupère les 20 dernières activités

        # --- 3. Formatage des données pour le front-end ---
        data_to_return = []
        for activity in activities:
            data_to_return.append({
                "name": activity.name,
                "distance": float(activity.distance),
                "moving_time": str(activity.moving_time),
                "elapsed_time": str(activity.elapsed_time),
                "total_elevation_gain": float(activity.total_elevation_gain),
                "type": activity.type,
                "start_date_local": activity.start_date_local.isoformat()
            })

        # --- 4. Construction de la réponse HTTP ---
        # Le corps de la réponse ('body') doit être une chaîne JSON.
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*' # Permet les appels depuis n'importe quelle origine
            },
            'body': json.dumps(data_to_return)
        }

    except Exception as e:
        # En cas d'erreur, retourner une réponse d'erreur claire
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({'error': str(e)})
        }