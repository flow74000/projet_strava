import os
import time
import traceback
import psycopg2
from datetime import datetime
from stravalib.client import Client

def sync_strava_activities():
    """
    Synchronise les nouvelles activités depuis Strava vers la base de données PostgreSQL.
    """
    print("Lancement du cycle de synchronisation Strava...")
    try:
        # --- Connexion à la base de données ---
        DATABASE_URL = os.environ.get('DATABASE_URL')
        conn = psycopg2.connect(DATABASE_URL)
        
        # --- Authentification Strava via Refresh Token ---
        client = Client()
        
        # Le worker utilise le REFRESH_TOKEN pour obtenir un nouvel ACCESS_TOKEN
        # C'est la méthode d'authentification pour un script non-interactif
        refresh_response = client.refresh_access_token(
            client_id=os.environ.get("STRAVA_CLIENT_ID"),
            client_secret=os.environ.get("STRAVA_CLIENT_SECRET"),
            refresh_token=os.environ.get("STRAVA_REFRESH_TOKEN")
        )
        
        authed_client = Client(access_token=refresh_response['access_token'])
        print("Authentification Strava réussie.")

        # --- Synchronisation Intelligente ---
        last_activity_date = None
        with conn.cursor() as cur:
            # 1. Trouver la date de la dernière activité déjà en base
            cur.execute("SELECT MAX(start_date) FROM activities")
            result = cur.fetchone()
            if result and result[0]:
                last_activity_date = result[0]
                print(f"Dernière activité trouvée en base de données à la date : {last_activity_date}")

        # 2. Récupérer uniquement les activités PLUS RÉCENTES depuis Strava
        activities_iterator = authed_client.get_activities(after=last_activity_date)
        
        new_activities = []
        for activity in activities_iterator:
            new_activities.append(activity)

        if not new_activities:
            print("Aucune nouvelle activité à synchroniser.")
            conn.close()
            return

        print(f"{len(new_activities)} nouvelle(s) activité(s) trouvée(s). Insertion en base...")
        with conn.cursor() as cur:
            for activity in reversed(new_activities): # On insère les plus anciennes d'abord
                # (Le code d'insertion est le même que dans votre ancien app.py)
                moving_time_obj = getattr(activity, 'moving_time', None)
                moving_time_seconds = int(moving_time_obj.total_seconds()) if hasattr(moving_time_obj, 'total_seconds') else 0

                cur.execute(
                    """
                    INSERT INTO activities (id, name, start_date, distance, moving_time_seconds, elevation_gain)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (activity.id, activity.name, activity.start_date_local, 
                     float(getattr(activity, 'distance', 0)) / 1000, 
                     moving_time_seconds, 
                     float(getattr(activity, 'total_elevation_gain', 0)))
                )
        
        conn.commit()
        conn.close()
        print("Synchronisation terminée avec succès.")

    except Exception as e:
        print("Une erreur est survenue durant la synchronisation :")
        print(traceback.format_exc())


if __name__ == '__main__':
    while True:
        sync_strava_activities()
        # Attend 15 minutes (900 secondes) avant le prochain cycle
        print("Prochaine synchronisation dans 15 minutes...")
        time.sleep(900)