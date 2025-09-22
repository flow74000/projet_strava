# Fichier: app.py (Version avec synchronisation améliorée)

import os
import requests
import traceback
import psycopg2
import polyline
from datetime import date, timedelta, datetime
from flask import Flask, jsonify, request
from flask_cors import CORS
from stravalib.client import Client
from stravalib import exc

app = Flask(__name__)
CORS(app)

# --- La fonction get_fitness_data reste inchangée ---
def get_fitness_data():
    try:
        athlete_id_icu=os.environ.get("INTERVALS_ATHLETE_ID");api_key=os.environ.get("INTERVALS_API_KEY");pma=float(os.environ.get("PMA_WATTS",0));default_weight=float(os.environ.get("DEFAULT_WEIGHT",70));
        if not all([athlete_id_icu,api_key,pma]):return None,None
        today=date.today();history_start_date=today-timedelta(days=180);url=f"https://intervals.icu/api/v1/athlete/{athlete_id_icu}/wellness?oldest={history_start_date}&newest={today}";
        response=requests.get(url,auth=('API_KEY',api_key));response.raise_for_status();wellness_data=response.json();
        if not wellness_data:return None,None
        wellness_data.sort(key=lambda x:x['id'],reverse=True);latest_data=wellness_data[0];last_known_weight=next((entry.get('weight')for entry in wellness_data if entry.get('weight')is not None),default_weight);current_weight=latest_data.get('weight',last_known_weight);ctl,atl=latest_data.get('ctl'),latest_data.get('atl');form=ctl-atl if ctl is not None and atl is not None else None;vo2max=((0.01141*pma+0.435)/current_weight)*1000 if current_weight and current_weight>0 else None;wellness_data.sort(key=lambda x:x['id']);summary={"fitness":round(ctl)if ctl is not None else None,"fatigue":round(atl)if atl is not None else None,"form":round(form)if form is not None else None,"vo2max":round(vo2max,1)if vo2max is not None else None};return summary,wellness_data
    except Exception as e:
        print(f"Erreur API Intervals.icu: {e}");return None,None

@app.route("/api/strava")
def strava_handler():
    try:
        DATABASE_URL = os.environ.get('DATABASE_URL')
        conn = psycopg2.connect(DATABASE_URL)
        client = Client()
        token_response = client.exchange_code_for_token(client_id=os.environ.get("STRAVA_CLIENT_ID"), client_secret=os.environ.get("STRAVA_CLIENT_SECRET"), code=request.args.get('code'))
        access_token = token_response['access_token']
        authed_client = Client(access_token=access_token)
        
        # --- LOGIQUE DE SYNCHRONISATION AMÉLIORÉE ---
        print("Début de la synchronisation intelligente avec Strava...")
        new_activities_found = 0
        activities_iterator = authed_client.get_activities() # Pas de limite, on les prend une par une
        
        with conn.cursor() as cur:
            for activity in activities_iterator:
                # 1. On vérifie si l'activité est déjà dans la BDD
                cur.execute("SELECT id FROM activities WHERE id = %s", (activity.id,))
                if cur.fetchone():
                    print("Activité déjà existante trouvée. Fin de la recherche de nouvelles activités.")
                    break # On arrête la boucle, les suivantes sont forcément plus anciennes
                
                # 2. Si elle est nouvelle, on la traite et on l'ajoute
                print(f"Nouvelle activité trouvée : {activity.name} ({activity.id})")
                new_activities_found += 1
                
                streams = authed_client.get_activity_streams(activity.id, types=['latlng'])
                encoded_polyline = polyline.encode(streams['latlng'].data) if streams and 'latlng' in streams else None
                moving_time_obj = getattr(activity, 'moving_time', timedelta(seconds=0))
                moving_time_seconds = moving_time_obj.total_seconds()

                cur.execute(
                    """
                    INSERT INTO activities (id, name, start_date, distance, moving_time_seconds, elevation_gain, polyline)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (activity.id, activity.name, activity.start_date_local, 
                     float(getattr(activity, 'distance', 0)) / 1000, 
                     moving_time_seconds, 
                     float(getattr(activity, 'total_elevation_gain', 0)), 
                     encoded_polyline)
                )
        
        if new_activities_found > 0:
            conn.commit()
            print(f"{new_activities_found} activité(s) ajoutée(s).")
        else:
            print("Base de données déjà à jour.")
        # --- FIN DE LA LOGIQUE DE SYNCHRONISATION ---

        # Le reste du code qui lit depuis la BDD est inchangé
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, start_date, moving_time_seconds, distance, elevation_gain, polyline FROM activities ORDER BY start_date DESC LIMIT 10")
            activities_from_db = [
                {
                    "name": r[1], "start_date_local": r[2].isoformat(),
                    "moving_time": str(timedelta(seconds=int(r[3]))), "distance": r[4] * 1000,
                    "total_elevation_gain": r[5], "map_polyline": r[6], "elevation_data": None
                } for r in cur.fetchall()
            ]
        conn.close()

        fitness_summary, form_chart_data = get_fitness_data()
        athlete = authed_client.get_athlete(); stats = authed_client.get_athlete_stats(athlete.id); ytd_distance = float(stats.ytd_ride_totals.distance) / 1000; yearly_summary = {"current": ytd_distance, "goal": 8000};
        today = date.today(); start_of_week = today - timedelta(days=today.weekday()); weekly_distance = sum(act['distance'] / 1000 for act in activities_from_db if datetime.fromisoformat(act['start_date_local']).date() >= start_of_week); weekly_summary = {"current": weekly_distance, "goal": 200};
        
        return jsonify({
            "activities": activities_from_db,
            "goals": { "weekly": weekly_summary, "yearly": yearly_summary },
            "fitness_summary": fitness_summary,
            "form_chart_data": form_chart_data
        })

    except Exception as e:
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500