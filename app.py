# Fichier: app.py

import os
from flask import Flask, jsonify, request
from flask_cors import CORS
from stravalib.client import Client

app = Flask(__name__)
CORS(app)

@app.route("/api/strava")
def strava_handler():
    print("--- Nouvelle requête reçue ---")

    STRAVA_CLIENT_ID = os.environ.get("STRAVA_CLIENT_ID")
    STRAVA_CLIENT_SECRET = os.environ.get("STRAVA_CLIENT_SECRET")

    code = request.args.get('code')
    print(f"Code reçu de Strava : {code}")

    if not code:
        print("Erreur : le code est manquant.")
        return jsonify({'error': 'Code manquant'}), 400

    client = Client()
    try:
        print("Échange du code contre un token...")
        token_response = client.exchange_code_for_token(
            client_id=STRAVA_CLIENT_ID,
            client_secret=STRAVA_CLIENT_SECRET,
            code=code
        )

        access_token = token_response['access_token']
        print(f"Token d'accès obtenu avec succès. Début : {access_token[:10]}...")

        authed_client = Client(access_token=access_token)

        print("Récupération des activités depuis Strava...")
        activities = list(authed_client.get_activities(limit=10))

        # La ligne la plus importante pour notre débogage :
        print(f"Nombre d'activités trouvées : {len(activities)}")

        activities_json = []
        for activity in activities:
            # Votre logique de formatage...
            activities_json.append({'name': activity.name}) # Exemple simple

        print("Construction de la réponse JSON...")
        response_data = {"activities": activities_json}

        print("--- Fin de la requête ---")
        return jsonify(response_data)

    except Exception as e:
        print(f"ERREUR DANS LE BLOC TRY/EXCEPT : {e}")
        return jsonify({'error': str(e)}), 500