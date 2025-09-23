# Fichier: worker.py (Version finale et optimisée)

import os
import time
import traceback
import psycopg2
from datetime import datetime
from stravalib.client import Client

def sync_strava_activities(conn):
    """
    Synchronise les nouvelles activités depuis Strava.
    Prend une connexion à la base de données en argument.
    """
    print("Lancement du cycle de synchronisation Strava...")
    try:
        client = Client()
        
        # La méthode .refresh_access_token() met à jour l'objet "client" directement.
        # Cela évite les avertissements "Please set client.refresh_token".
        client.refresh_access_token(
            client_id=os.environ.get("STRAVA_CLIENT_ID"),
            client_secret=os.environ.get("STRAVA_CLIENT_SECRET"),
            refresh_token=os.environ.get("STRAVA_REFRESH_TOKEN")
        )
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
        activities_iterator = client.get_activities(after=last_activity_date)
        
        # On convertit l'itérateur en liste pour pouvoir le traiter
        new_activities = list(activities_iterator)

        if not new_activities:
            print("Aucune nouvelle activité à synchroniser.")
            return # On quitte la fonction si il n'y a rien à faire

        print(f"{len(new_activities)} nouvelle(s) activité(s) trouvée(s). Insertion en base...")
        with conn.cursor() as cur:
            # On insère les plus anciennes d'abord pour maintenir l'ordre chronologique
            for activity in reversed(new_activities):
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
        print("Synchronisation des activités terminée.")

    except Exception as e:
        print("Une erreur est survenue durant la synchronisation des activités :")
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
            # 1. On récupère toutes les activités de l'année depuis NOTRE base de données
            cur.execute("SELECT start_date, distance FROM activities WHERE EXTRACT(YEAR FROM start_date) = %s", (current_year,))
            activities_of_year = cur.fetchall()

            # 2. On calcule les totaux en Python
            monthly_totals = [0.0] * 12
            for activity in activities_of_year:
                activity_date, distance = activity
                month_index = activity_date.month - 1
                monthly_totals[month_index] += float(distance)
            
            # 3. On insère ou met à jour les données dans la nouvelle table (UPSERT)
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


if __name__ == '__main__':
    while True:
        DATABASE_URL = os.environ.get('DATABASE_URL')
        db_connection = None
        try:
            # On établit une seule connexion pour tout le cycle
            db_connection = psycopg2.connect(DATABASE_URL)
            sync_strava_activities(db_connection)
            update_monthly_stats(db_connection)
        except Exception as e:
            print(f"Erreur au niveau de la connexion à la base de données: {e}")
        finally:
            if db_connection:
                db_connection.close()
        
        print("Cycle terminé. Prochaine exécution dans 15 minutes...")
        # Attend 15 minutes (900 secondes) avant le prochain cycle
        time.sleep(900)