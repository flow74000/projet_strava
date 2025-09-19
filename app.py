# Fichier: app.py (Version avec graphique de progression)

import os
import requests
import traceback
import psycopg2
from datetime import date, timedelta, datetime
from flask import Flask, jsonify, request
from flask_cors import CORS
from stravalib.client import Client
from stravalib import exc

app = Flask(__name__)
CORS(app)

def get_fitness_data():
    try:
        athlete_id_icu = os.environ.get("INTERVALS_ATHLETE_ID")
        api_key = os.environ.get("INTERVALS_API_KEY")
        pma = float(os.environ.get("PMA_WATTS", 0))
        default_weight = float(os.environ.get("DEFAULT_WEIGHT", 70))
        if not all([athlete_id_icu, api_key, pma]): return None, None
        
        today = date.today()
        history_start_date = today - timedelta(days=180)
        url = f"https://intervals.icu/api/v1/athlete/{athlete_id_icu}/wellness?oldest={history_start_date}&newest={today}"
        
        response = requests.get(url, auth=('API_KEY', api_key))
        response.raise_for_status()
        wellness_data = response.json()
        
        if not wellness_data: return None, None

        wellness_data.sort(key=lambda x: x['id'], reverse=True)
        latest_data = wellness_data[0]
        last_known_weight = next((entry.get('weight') for entry in wellness_data if entry.get('weight') is not None), default_weight)
        current_weight = latest_data.get('weight', last_known_weight)
        ctl, atl = latest_data.get('ctl'), latest_data.get('atl')
        form = ctl - atl if ctl is not None and atl is not None else None
        vo2max = ((0.01141 * pma + 0.435) / current_weight) * 1000 if current_weight and current_weight > 0 else None
        wellness_data.sort(key=lambda x: x['id'])
        summary = {"fitness": round(ctl) if ctl is not None else None, "fatigue": round(atl) if atl is not None else None, "form": round(form) if form is not None else None, "vo2max": round(vo2max, 1) if vo2max is not None else None}
        return summary, wellness_data
    except Exception as e:
        print(f"Erreur API Intervals.icu: {e}")
        return None, None

def get_progression_data(conn):
    try:
        today = date.today()
        current_year = today.year
        previous_year = current_year - 1

        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    EXTRACT(YEAR FROM start_date) as year, 
                    EXTRACT(MONTH FROM start_date) as month, 
                    SUM(distance) as total_distance 
                FROM activities 
                WHERE EXTRACT(YEAR FROM start_date) IN (%s, %s) 
                GROUP BY year, month
            """, (current_year, previous_year))
            
            results = cur.fetchall()

        current_year_dist = [0] * 12
        previous_year_dist = [0] * 12

        for row in results:
            year, month, total_distance = int(row[0]), int(row[1]), float(row[2])
            if year == current_year:
                current_year_dist[month - 1] = total_distance
            elif year == previous_year:
                previous_year_dist[month - 1] = total_distance
        
        for i in range(1, 12):
            current_year_dist[i] += current_year_dist[i-1]
            previous_year_dist[i] += previous_year_dist[i-1]
        
        return {
            "current_year": [round(d) for d in current_year_dist],
            "previous_year": [round(d) for d in previous_year_dist]
        }
    except Exception as e:
        print(f"Erreur lors du calcul de la progression: {e}")
        return None

@app.route("/api/strava")
def strava_handler():
    try:
        DATABASE_URL = os.environ.get('DATABASE_URL')
        conn = psycopg2.connect(DATABASE_URL)
        
        client = Client()
        token_response = client.exchange_code_for_token(client_id=os.environ.get("STRAVA_CLIENT_ID"), client_secret=os.environ.get("STRAVA_CLIENT_SECRET"), code=request.args.get('code'))
        access_token = token_response['access_token']
        authed_client = Client(access_token=access_token)
        
        # ... (La logique de synchronisation reste inchangée) ...
        
        progression_data = get_progression_data(conn)
        
        activities_from_db = []
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, start_date, moving_time_seconds, distance, elevation_gain, polyline FROM activities ORDER BY start_date DESC LIMIT 10")
            for r in cur.fetchall():
                elevation_data = None
                try:
                    streams = authed_client.get_activity_streams(r[0], types=['distance', 'altitude'])
                    if streams and 'distance' in streams and 'altitude' in streams:
                        elevation_data = {'distance': streams['distance'].data, 'altitude': streams['altitude'].data}
                except exc.ObjectNotFound:
                    print(f"AVERTISSEMENT : Streams introuvables pour l'activité {r[0]}, elle sera ignorée.")
                    pass
                
                activities_from_db.append({
                    "name": r[1], "start_date_local": r[2].isoformat(),
                    "moving_time": str(timedelta(seconds=int(r[3]))), "distance": r[4] * 1000,
                    "total_elevation_gain": r[5], "map_polyline": r[6],
                    "elevation_data": elevation_data
                })
        conn.close()

        fitness_summary, form_chart_data = get_fitness_data()
        athlete = authed_client.get_athlete(); stats = authed_client.get_athlete_stats(athlete.id); ytd_distance = float(stats.ytd_ride_totals.distance) / 1000; yearly_summary = {"current": ytd_distance, "goal": 8000};
        today = date.today(); start_of_week = today - timedelta(days=today.weekday()); weekly_distance = sum(act['distance'] / 1000 for act in activities_from_db if datetime.fromisoformat(act['start_date_local']).date() >= start_of_week); weekly_summary = {"current": weekly_distance, "goal": 200};
        
        return jsonify({
            "activities": activities_from_db,
            "goals": { "weekly": weekly_summary, "yearly": yearly_summary },
            "fitness_summary": fitness_summary,
            "form_chart_data": form_chart_data,
            "progression_data": progression_data
        })
    except Exception as e:
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500