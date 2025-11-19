import os
from datetime import datetime

from flask import Flask, request, jsonify
from pymongo import MongoClient, ASCENDING
from dotenv import load_dotenv

# Load env vars from .env if present
load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/dashboard_db")
DB_NAME = os.getenv("MONGO_DB_NAME", "dashboard_db")
COLLECTION_NAME = "user_dashboards"

app = Flask(__name__)

# ----- MongoDB Setup -----
client = MongoClient(MONGO_URI)
db = client[DB_NAME]
dashboards_col = db[COLLECTION_NAME]

# Ensure index { userId, dashboardId } is unique
dashboards_col.create_index(
    [("userId", ASCENDING), ("dashboardId", ASCENDING)],
    unique=True
)


# ----- Helpers -----


def get_current_user_id():
    """
    In real app, derive from JWT / session.
    For now we read it from X-User-Id header.
    """
    user_id = request.headers.get("X-User-Id")
    if not user_id:
        # For quick local testing you can default this,
        # but in prod you should return 401.
        # return None
        user_id = "demo-user"
    return user_id


def serialize_dashboard(doc):
    """Convert Mongo doc to API response shape."""
    if not doc:
        return None

    return {
        "userId": doc["userId"],
        "dashboardId": doc["dashboardId"],
        "layout": doc.get("layout", []),
        "updatedAt": doc.get("updatedAt").isoformat() + "Z"
        if doc.get("updatedAt")
        else None,
    }


# ----- Routes -----


@app.route("/api/v1/dashboard/<dashboard_id>", methods=["GET"])
def get_dashboard(dashboard_id):
    """
    GET /api/v1/dashboard/<dashboardId>
    - If exists, return it.
    - If not, create a default empty dashboard for this user and return it.
    """
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    doc = dashboards_col.find_one(
        {"userId": user_id, "dashboardId": dashboard_id}
    )

    if not doc:
        # Auto-create default dashboard TODO Put default layout
        now = datetime.utcnow()
        default_doc = {
            "userId": user_id,
            "dashboardId": dashboard_id,
            "layout": [],
            "updatedAt": now,
        }
        try:
            dashboards_col.insert_one(default_doc)
        except Exception as e:
            return jsonify({"error": f"Failed to create default dashboard: {str(e)}"}), 500

        return jsonify(serialize_dashboard(default_doc)), 200

    # Existing dashboard
    return jsonify(serialize_dashboard(doc)), 200


@app.route("/api/v1/dashboard/<dashboard_id>", methods=["PUT"])
def upsert_dashboard(dashboard_id):
    """
    PUT /api/v1/dashboard/<dashboardId>

    Request body:
    {
      "layout": [
        {
          "widgetId": "postureScore",
          "x": 0,
          "y": 0,
          "w": 4,
          "h": 3,
          "config": { ... }   // optional
        }
      ]
    }

    - Upserts document in Mongo.
    - Returns 'created' if inserted, 'updated' if existing.
    """
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    layout = data.get("layout")

    if layout is None or not isinstance(layout, list):
        return jsonify({"error": "Field 'layout' (array) is required"}), 400

    now = datetime.utcnow()

    try:
        result = dashboards_col.update_one(
            {"userId": user_id, "dashboardId": dashboard_id},
            {
                "$set": {
                    "layout": layout,
                    "updatedAt": now,
                }
            },
            upsert=True,
        )
    except Exception as e:
        return jsonify({"error": f"Failed to upsert dashboard: {str(e)}"}), 500

    status = "created" if result.upserted_id is not None else "updated"

    # Fetch the latest version to return
    doc = dashboards_col.find_one(
        {"userId": user_id, "dashboardId": dashboard_id}
    )

    return jsonify(
        {
            "status": status,
            "dashboard": serialize_dashboard(doc),
        }
    ), 201 if status == "created" else 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    # For local dev only
    app.run(host="0.0.0.0", port=8000, debug=True)
