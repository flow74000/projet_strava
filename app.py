# Fichier: app.py (Version finale)

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
            # On formate l'objet complet avec toutes les données
            activities_json.append({
                'name': activity.name,
                'start_date_local': activity.start_date_local.strftime('%A %d %B %Y'),
                'moving_time': str(activity.moving_time),
                'distance': float(activity.distance),
                'total_elevation_gain': float(activity.total_elevation_gain)
                # Vous pouvez ajouter d'autres champs ici si besoin
            })

        # On renvoie la liste complète des activités formatées
        return jsonify({
            "activities": activities_json
            # Note : la logique du graphique d'élévation a été omise pour la simplicité,
            # mais peut être rajoutée ici si nécessaire.
        })

    except Exception as e:
        # En cas d'erreur, on la renvoie pour le débogage
        return jsonify({'error': str(e)}), 500