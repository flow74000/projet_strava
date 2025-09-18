# Fichier: app.py (Version avec gestion de la durée corrigée)

import os
import requests
import traceback
import psycopg2
import polyline
from datetime import date, timedelta, datetime
from flask import Flask, jsonify, request
from flask_cors import CORS
from stravalib.client import Client

app = Flask(__name__)
CORS(app)

# ... (La fonction get_fitness_data reste inchangée) ...
def get_fitness_data():
    # ... (code complet de la fonction get_fitness_data)
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
        
        print("Synchronisation avec Strava...")
        latest_strava_activities = list(authed_client.get_activities(limit=20))
        strava_ids = [act.id for act in latest_strava_activities]
        
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM activities WHERE id = ANY(%s::bigint[])", (strava_ids,))
            existing_ids = {row[0] for row in cur.fetchall()}
        
        new_activities_to_add = [act for act in latest_strava_activities if act.id not in existing_ids]
        
        if new_activities_to_add:
            print(f"Ajout de {len(new_activities_to_add)} nouvelle(s) activité(s)...")
            with conn.cursor() as cur:
                for activity in new_activities_to_add:
                    streams = authed_client.get_activity_streams(activity.id, types=['latlng'])
                    encoded_polyline = polyline.encode(streams['latlng'].data) if streams and 'latlng' in streams else None
                    
                    # --- CORRECTION ICI : Gestion plus sûre de la durée ---
                    moving_time_obj = getattr(activity, 'moving_time', None)
                    moving_time_seconds = moving_time_obj.total_seconds() if hasattr(moving_time_obj, 'total_seconds') else 0
                    
                    cur.execute(
                        """
                        INSERT INTO activities (id, name, start_date, distance, moving_time_seconds, elevation_gain, polyline)
                        VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING
                        """,
                        (activity.id, activity.name, activity.start_date_local, float(getattr(activity, 'distance', 0)) / 1000, moving_time_seconds, float(getattr(activity, 'total_elevation_gain', 0)), encoded_polyline)
                    )
            conn.commit()
            print("Synchronisation terminée.")
        else:
            print("Base de données déjà à jour.")

        # Le reste du fichier est inchangé
        with conn.cursor() as cur:
            cur.execute("SELECT name, start_date, moving_time_seconds, distance, elevation_gain, polyline FROM activities ORDER BY start_date DESC LIMIT 10")
            activities_from_db = [{"name": r[0], "start_date_local": r[1].isoformat(), "moving_time": str(timedelta(seconds=int(r[2]))), "distance": r[3] * 1000, "total_elevation_gain": r[4], "map_polyline": r[5], "elevation_data": None} for r in cur.fetchall()]
        conn.close()

        fitness_summary, form_chart_data = get_fitness_data()
        athlete = authed_client.get_athlete()
        stats = authed_client.get_athlete_stats(athlete.id)
        ytd_distance = float(stats.ytd_ride_totals.distance) / 1000
        yearly_summary = {"current": ytd_distance, "goal": 8000}
        
        today = date.today()
        start_of_week = today - timedelta(days=today.weekday())
        weekly_distance = sum(act['distance'] / 1000 for act in activities_from_db if datetime.fromisoformat(act['start_date_local']).date() >= start_of_week)
        weekly_summary = {"current": weekly_distance, "goal": 200}
        
        return jsonify({
            "activities": activities_from_db,
            "goals": { "weekly": weekly_summary, "yearly": yearly_summary },
            "fitness_summary": fitness_summary,
            "form_chart_data": form_chart_data
        })

    except Exception as e:
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500
