# Fichier: worker.py (Version finale, robuste avec gestion des erreurs)

import os
import time
import traceback
import psycopg2
from datetime import datetime, timedelta
from stravalib.client import Client

# Imports pour l'API Google Fit
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

def sync_strava_activities(conn):
    """
    Synchronise les nouvelles activités depuis Strava et les stocke dans la base de données.
    """
    print("Lancement du cycle de synchronisation Strava...")
    try:
        client = Client()
        client.refresh_access_token(
            client_id=os.environ.get("STRAVA_CLIENT_ID"),
            client_secret=os.environ.get("STRAVA_CLIENT_SECRET"),
            refresh_token=os.environ.get("STRAVA_REFRESH_TOKEN")
        )
        print("Authentification Strava réussie.")

        last_activity_date = None
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(start_date) FROM activities")
            result = cur.fetchone()
            if result and result[0]:
                last_activity_date = result[0]
                print(f"Dernière activité trouvée en base de données à la date : {last_activity_date}")

        activities_iterator = client.get_activities(after=last_activity_date)
        new_activities = list(activities_iterator)

        if not new_activities:
            print("Aucune nouvelle activité Strava à synchroniser.")
            return

        print(f"{len(new_activities)} nouvelle(s) activité(s) trouvée(s). Insertion en base...")
        with conn.cursor() as cur:
            for activity in reversed(new_activities):
                moving_time_obj = getattr(activity, 'moving_time', None)
                moving_time_seconds = int(moving_time_obj.total_seconds()) if hasattr(moving_time_obj, 'total_seconds') else 0

                cur.execute(
                    """
                    INSERT INTO activities (id, name, start_date, distance, moving_time_seconds, elevation_gain)
                    VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING
                    """,
                    (activity.id, activity.name, activity.start_date_local,
                     float(getattr(activity, 'distance', 0)) / 1000,
                     moving_time_seconds,
                     float(getattr(activity, 'total_elevation_gain', 0)))
                )
        conn.commit()
        print("Synchronisation des activités Strava terminée.")

    except Exception as e:
        print("Une erreur est survenue durant la synchronisation des activités Strava :")
        print(traceback.format_exc())

def update_monthly_stats(conn):
    """
    Calcule les totaux mensuels pour l'année en cours depuis la DB et les stocke
    dans la table monthly_stats.
    """
    print("Mise à jour des statistiques mensuelles...")
    try:
        current_year = datetime.now().year
        with conn.cursor() as cur:
            cur.execute("SELECT start_date, distance FROM activities WHERE EXTRACT(YEAR FROM start_date) = %s", (current_year,))
            activities_of_year = cur.fetchall()

            monthly_totals = [0.0] * 12
            for activity in activities_of_year:
                activity_date, distance = activity
                month_index = activity_date.month - 1
                monthly_totals[month_index] += float(distance)
            
            for i, total_distance in enumerate(monthly_totals):
                month = i + 1
                cur.execute(
                    """
                    INSERT INTO monthly_stats (year, month, distance)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (year, month) DO UPDATE SET distance = EXCLUDED.distance;
                    """,
                    (current_year, month, round(total_distance, 2))
                )
        conn.commit()
        print("Statistiques mensuelles mises à jour avec succès.")
    except Exception as e:
        print("Une erreur est survenue durant la mise à jour des statistiques :")
        print(traceback.format_exc())

def sync_google_fit_weight(conn):
    """
    Récupère les données de poids depuis Google Fit et les stocke dans la base de données.
    """
    print("Lancement du cycle de synchronisation Google Fit...")
    SCOPES = ['https://www.googleapis.com/auth/fitness.body.read']
    token_path = '/etc/secrets/token.json' if os.path.exists('/etc/secrets/token.json') else 'token.json'

    try:
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        fitness_service = build('fitness', 'v1', credentials=creds)

        end_time = datetime.utcnow()
        start_time = end_time - timedelta(days=90)
        start_time_ns = int(start_time.timestamp() * 1e9)
        end_time_ns = int(end_time.timestamp() * 1e9)
        dataset_id = f"{start_time_ns}-{end_time_ns}"

        response = fitness_service.users().dataSources().datasets().get(
            userId='me',
            dataSourceId='derived:com.google.weight:com.google.android.gms:merge_weight',
            datasetId=dataset_id
        ).execute()

        weight_points = []
        for point in response.get('point', []):
            weight_kg = point['value'][0]['fpVal']
            timestamp_s = int(point['startTimeNanos']) / 1e9
            date_str = datetime.fromtimestamp(timestamp_s).strftime('%Y-%m-%d')
            weight_points.append({'date': date_str, 'weight': round(weight_kg, 2)})
        
        if not weight_points:
            print("Aucune nouvelle donnée de poids à synchroniser depuis Google Fit.")
            return

        with conn.cursor() as cur:
            for point in weight_points:
                cur.execute(
                    """
                    INSERT INTO weight_history (measurement_date, weight_kg)
                    VALUES (%s, %s)
                    ON CONFLICT (measurement_date) DO UPDATE SET weight_kg = EXCLUDED.weight_kg;
                    """,
                    (point['date'], point['weight'])
                )
        conn.commit()
        print(f"{len(weight_points)} points de données de poids synchronisés avec succès.")

    except FileNotFoundError:
        print("Fichier token.json introuvable pour Google Fit. Synchronisation du poids impossible.")
    except Exception as e:
        print("Une erreur est survenue durant la synchronisation Google Fit :")
        print(traceback.format_exc())


if __name__ == '__main__':
    while True:
        try:
            print("\n--- DEBUT D'UN NOUVEAU CYCLE DE SYNCHRONISATION ---")
            DATABASE_URL = os.environ.get('DATABASE_URL')
            db_connection = None
            try:
                print("Connexion à la base de données...")
                db_connection = psycopg2.connect(DATABASE_URL)
                print("Connexion réussie.")
                
                # Exécution des tâches de synchronisation
                sync_strava_activities(db_connection)
                update_monthly_stats(db_connection)
                sync_google_fit_weight(db_connection)

            finally:
                if db_connection:
                    db_connection.close()
                    print("Connexion à la base de données fermée.")
            
            print("--- CYCLE TERMINE ---")

        except Exception as e:
            # Capture et affiche toute erreur imprévue
            print("!!! ERREUR CRITIQUE DANS LA BOUCLE PRINCIPALE DU WORKER !!!")
            print(traceback.format_exc())

        finally:
            # La pause de 15 minutes se fait dans tous les cas
            print(f"Prochaine exécution vers {datetime.now() + timedelta(minutes=15)}")
            time.sleep(900)