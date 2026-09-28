import os
import subprocess
import sys
from google.cloud import firestore

PROJECT_ID = "qwiklabs-gcp-02-82f554a728eb"

def get_firestore_client():
    try:
        db = firestore.Client(project=PROJECT_ID)
        # Test query to verify permissions
        list(db.collection("exercises").limit(1).stream())
        return db
    except Exception as e:
        print(f"Default auth note ({e}), using active gcloud token for local setup...")
        token = subprocess.check_output(["gcloud", "auth", "print-access-token"]).decode("utf-8").strip()
        import google.oauth2.credentials
        creds = google.oauth2.credentials.Credentials(token)
        return firestore.Client(project=PROJECT_ID, credentials=creds)

def seed_database():
    print(f"Connecting to Firestore for project: {PROJECT_ID}")
    db = get_firestore_client()

    # Seed Exercises Catalog
    exercises_ref = db.collection("exercises")
    sample_exercises = [
        {
            "id": "bench_press",
            "name": "Barbell Bench Press",
            "target_muscle": "Chest",
            "category": "Strength",
            "difficulty": "Intermediate",
            "default_sets": 4,
            "default_reps": 8
        },
        {
            "id": "squat",
            "name": "Barbell Back Squat",
            "target_muscle": "Legs",
            "category": "Strength",
            "difficulty": "Intermediate",
            "default_sets": 4,
            "default_reps": 10
        },
        {
            "id": "pull_up",
            "name": "Pull-Up",
            "target_muscle": "Back",
            "category": "Calisthenics",
            "difficulty": "Beginner",
            "default_sets": 3,
            "default_reps": 10
        },
        {
            "id": "deadlift",
            "name": "Barbell Deadlift",
            "target_muscle": "Full Body",
            "category": "Strength",
            "difficulty": "Advanced",
            "default_sets": 3,
            "default_reps": 5
        },
        {
            "id": "bicep_curl",
            "name": "Dumbbell Bicep Curl",
            "target_muscle": "Biceps",
            "category": "Hypertrophy",
            "difficulty": "Beginner",
            "default_sets": 3,
            "default_reps": 12
        }
    ]

    for item in sample_exercises:
        doc_id = item["id"]
        exercises_ref.document(doc_id).set(item)
        print(f"Seeded exercise: {item['name']} ({doc_id})")

    # Seed Initial Workout Sessions
    workouts_ref = db.collection("workout_sessions")
    sample_workouts = [
        {
            "session_id": "session_001",
            "date": "2026-09-25",
            "exercise_name": "Barbell Bench Press",
            "sets": 4,
            "reps": 8,
            "weight_lbs": 185,
            "notes": "Felt strong, good bar speed."
        },
        {
            "session_id": "session_002",
            "date": "2026-09-27",
            "exercise_name": "Barbell Back Squat",
            "sets": 4,
            "reps": 10,
            "weight_lbs": 225,
            "notes": "Depth was solid on all sets."
        }
    ]

    for workout in sample_workouts:
        doc_id = workout["session_id"]
        workouts_ref.document(doc_id).set(workout)
        print(f"Seeded workout session: {workout['session_id']}")

    print("Firestore seeding complete!")

if __name__ == "__main__":
    seed_database()
