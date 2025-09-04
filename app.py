# Fichier: app.py (à la racine de votre projet)

import os
import json
from flask import Flask, jsonify, request
from flask_cors import CORS  # Important pour autoriser les requêtes entre le front et le back
from stravalib.client import Client

# Initialisation de l'application Flask
app = Flask(__name__)
# Activation de CORS pour autoriser les appels depuis votre site statique
CORS(app)

# Définition de la route de votre API
@app.route("/api/strava")
def strava_handler():
    # On récupère les identifiants depuis les variables d'environnement
    STRAVA_CLIENT_ID = os.environ.get("STRAVA_CLIENT_ID")
    STRAVA_CLIENT_SECRET = os.environ.get("STRAVA_CLIENT_SECRET")
    
    # On récupère le code 'code' passé dans l'URL (ex: ?code=12345)
    code = request.args.get('code')

    if not code:
        return jsonify({'error': 'Code manquant'}), 400

    client = Client()
    try:
        # Échange du code contre un token
        token_response = client.exchange_code_for_token(
            client_id=STRAVA_CLIENT_ID,
            client_secret=STRAVA_CLIENT_SECRET,
            code=code
        )
        access_token = token_response['access_token']
        
        # Le reste de votre logique reste identique...
        authed_client = Client(access_token=access_token)
        activities = list(authed_client.get_activities(limit=10))
        
        # ... (toute votre logique de formatage des données)
        
        activities_json = []
        for activity in activities:
            activities_json.append({
                'name': activity.name,
                # ... etc ...
            })
        
        # On retourne une réponse JSON avec Flask
        return jsonify({
            "activities": activities_json,
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Cette partie n'est utile que pour tester en local, Render ne l'utilisera pas
if __name__ == "__main__":
    app.run(debug=True, port=5000)