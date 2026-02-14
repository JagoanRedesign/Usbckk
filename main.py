from fastapi import FastAPI, HTTPException, Depends, Header, Query
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from contextlib import asynccontextmanager
import os
import sys
import traceback

# ==================== KONFIGURASI LANGSUNG ====================
MONGO_URI = "mongodb+srv://galeh:galeh@cluster0.cq2tj1u.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
DB_NAME = "quiz_bot"
COLLECTION_NAME = "players"
API_KEY = "kunci975635885rii7"
PORT = 8000
HOST = "0.0.0.0"

PORT = int(os.environ.get("PORT", PORT))

# ==================== VARIABEL GLOBAL ====================
client = None
db = None
collection = None

print(f"🐍 Python version: {sys.version}")
print(f"🔌 MongoDB URI: {MONGO_URI[:50]}...")

# ==================== LIFESPAN ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    global client, db, collection
    print(f"🚀 Starting Quiz Bot API...")
    print(f"📊 Database: {DB_NAME}")
    print(f"📦 Collection: {COLLECTION_NAME}")
    print(f"🔑 API Key: {'✅ Tersedia' if API_KEY else '❌ Tidak ada'}")

    try:
        print("🔄 Menghubungkan ke MongoDB...")
        # Gunakan pymongo 3.12.3 tanpa ServerApi
        client = MongoClient(
            MONGO_URI,
            connectTimeoutMS=30000,
            socketTimeoutMS=30000,
            serverSelectionTimeoutMS=30000
        )
        # Test koneksi dengan ping
        client.admin.command('ping')
        print("✅ Ping MongoDB berhasil!")

        db = client[DB_NAME]
        collection = db[COLLECTION_NAME]

        # Buat index dengan try-except terpisah (jika gagal, tidak menghentikan startup)
        try:
            collection.create_index("points", -1)
            print("✅ Index 'points' berhasil dibuat")
        except Exception as idx_err:
            print(f"⚠️ Gagal membuat index points: {idx_err}")

        try:
            collection.create_index("username")
            print("✅ Index 'username' berhasil dibuat")
        except Exception as idx_err:
            print(f"⚠️ Gagal membuat index username: {idx_err}")

        total_players = collection.count_documents({})
        print(f"📊 Total pemain saat ini: {total_players}")

        if total_players > 0:
            top3 = list(collection.find().sort("points", -1).limit(3))
            print("🏆 Top 3 Players:")
            for i, p in enumerate(top3, 1):
                name = p.get("username") or p.get("first_name") or f"Player {p['_id']}"
                print(f"   {i}. {name}: {p['points']} poin")

        print("✅ Koneksi MongoDB BERHASIL!")
    except Exception as e:
        print(f"❌ Gagal koneksi MongoDB: {type(e).__name__}: {e}")
        traceback.print_exc()
        client = None
        db = None
        collection = None

    yield

    print("👋 API shutting down...")
    if client:
        client.close()
        print("✅ Koneksi MongoDB ditutup")

# ==================== INISIALISASI APP ====================
app = FastAPI(
    title="Quiz Bot API",
    description="API untuk manajemen poin game kuis Telegram",
    version="1.0.0",
    lifespan=lifespan
)

# ==================== FUNGSI VERIFIKASI ====================
def verify_api_key(api_key: str = Header(...)):
    if not API_KEY:
        raise HTTPException(status_code=500, detail="Server configuration error: API_KEY not set")
    if api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Forbidden: Invalid API Key")
    return api_key

def get_collection():
    if collection is None:
        raise HTTPException(
            status_code=503, 
            detail="Database connection not available. Please check /health endpoint."
        )
    return collection

# ==================== MODEL DATA ====================
class PointUpdate(BaseModel):
    user_id: int
    points: int
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    username: Optional[str] = None
    language_code: Optional[str] = None

class PlayerResponse(BaseModel):
    user_id: int
    points: int
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    username: Optional[str] = None
    rank: Optional[int] = None
    total_games: Optional[int] = None
    correct_answers: Optional[int] = None

class HealthResponse(BaseModel):
    status: str
    database: str
    total_players: int
    timestamp: str
    mongo_uri_configured: bool
    api_key_configured: bool
    error_detail: Optional[str] = None

# ==================== ENDPOINTS ====================

@app.get("/")
async def root():
    db_status = "connected" if collection is not None else "disconnected"
    return {
        "service": "Quiz Bot API",
        "version": "1.0.0",
        "status": "running",
        "database": db_status,
        "timestamp": datetime.now().isoformat(),
        "endpoints": [
            {"method": "GET", "path": "/", "description": "Info API"},
            {"method": "GET", "path": "/health", "description": "Health check (public)"},
            {"method": "GET", "path": "/points/{user_id}", "description": "GET poin pemain"},
            {"method": "POST", "path": "/points", "description": "POST update poin"},
            {"method": "GET", "path": "/leaderboard", "description": "GET peringkat"},
            {"method": "GET", "path": "/players", "description": "GET semua pemain"},
            {"method": "DELETE", "path": "/points/{user_id}", "description": "Reset poin pemain"},
            {"method": "GET", "path": "/stats", "description": "GET statistik umum"},
            {"method": "GET", "path": "/top/{count}", "description": "GET N pemain teratas"},
            {"method": "GET", "path": "/debug/connection", "description": "Debug koneksi"}
        ]
    }

@app.get("/health", response_model=HealthResponse)
async def health_check():
    db_status = "disconnected"
    total_players = 0
    error_detail = None

    try:
        if client:
            try:
                client.admin.command('ping')
                db_status = "connected"
            except Exception as e:
                error_detail = str(e)
                db_status = "error"

            if collection and db_status == "connected":
                try:
                    total_players = collection.count_documents({})
                except Exception as count_err:
                    print(f"Error count_documents: {count_err}")
                    total_players = -1
    except Exception as e:
        print(f"Health check error: {e}")
        error_detail = str(e)

    overall_status = "healthy" if db_status == "connected" else "unhealthy"
    return {
        "status": overall_status,
        "database": db_status,
        "total_players": total_players,
        "timestamp": datetime.now().isoformat(),
        "mongo_uri_configured": bool(MONGO_URI),
        "api_key_configured": bool(API_KEY),
        "error_detail": error_detail
    }

@app.get("/debug/connection")
async def debug_connection(api_key: str = Depends(verify_api_key)):
    debug_info = {
        "python_version": sys.version,
        "client_exists": client is not None,
        "db_exists": db is not None,
        "collection_exists": collection is not None,
        "mongodb_uri": MONGO_URI[:50] + "..." if MONGO_URI else None,
        "database_name": DB_NAME,
        "collection_name": COLLECTION_NAME,
    }
    if client:
        try:
            ping_result = client.admin.command('ping')
            debug_info["ping_result"] = ping_result
            debug_info["databases"] = client.list_database_names()
            if db:
                debug_info["collections"] = db.list_collection_names()
                if collection:
                    debug_info["document_count"] = collection.count_documents({})
        except Exception as e:
            debug_info["error"] = str(e)
            debug_info["traceback"] = traceback.format_exc()
    return debug_info

@app.get("/points/{user_id}", response_model=PlayerResponse)
async def get_points(user_id: int, api_key: str = Depends(verify_api_key)):
    coll = get_collection()
    try:
        player = coll.find_one({"_id": user_id})
        if not player:
            new_player = {
                "_id": user_id,
                "points": 0,
                "first_name": None,
                "last_name": None,
                "username": None,
                "language_code": None,
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
                "total_games": 0,
                "correct_answers": 0
            }
            coll.insert_one(new_player)
            print(f"✅ Pemain baru dibuat: {user_id}")
            return {
                "user_id": user_id,
                "points": 0,
                "first_name": None,
                "last_name": None,
                "username": None,
                "rank": None,
                "total_games": 0,
                "correct_answers": 0
            }

        rank = coll.count_documents({"points": {"$gt": player["points"]}}) + 1
        print(f"📊 Poin pemain {user_id}: {player['points']} (Rank: {rank})")
        return {
            "user_id": player["_id"],
            "points": player["points"],
            "first_name": player.get("first_name"),
            "last_name": player.get("last_name"),
            "username": player.get("username"),
            "rank": rank,
            "total_games": player.get("total_games", 0),
            "correct_answers": player.get("correct_answers", 0)
        }
    except Exception as e:
        print(f"❌ Error get_points: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.post("/points", response_model=PlayerResponse)
async def update_points(update: PointUpdate, api_key: str = Depends(verify_api_key)):
    coll = get_collection()
    try:
        # Siapkan operator update secara eksplisit
        update_ops = {}
        inc_fields = {}
        if update.points != 0:
            inc_fields["points"] = update.points
            inc_fields["total_games"] = 1
            if update.points > 0:
                inc_fields["correct_answers"] = 1
        if inc_fields:
            update_ops["$inc"] = inc_fields

        set_fields = {"updated_at": datetime.now()}
        if update.first_name:
            set_fields["first_name"] = update.first_name
        if update.last_name:
            set_fields["last_name"] = update.last_name
        if update.username:
            set_fields["username"] = update.username
        if update.language_code:
            set_fields["language_code"] = update.language_code
        if set_fields:
            update_ops["$set"] = set_fields

        # $setOnInsert hanya untuk created_at (total_games & correct_answers akan di-$inc)
        update_ops["$setOnInsert"] = {"created_at": datetime.now()}

        result = coll.update_one(
            {"_id": update.user_id},
            update_ops,
            upsert=True
        )

        player = coll.find_one({"_id": update.user_id})
        rank = coll.count_documents({"points": {"$gt": player["points"]}}) + 1

        action = "ditambahkan" if result.upserted_id else "diupdate"
        print(f"✅ Poin {action} untuk {update.user_id}: {update.points} (total: {player['points']})")
        return {
            "user_id": player["_id"],
            "points": player["points"],
            "first_name": player.get("first_name"),
            "last_name": player.get("last_name"),
            "username": player.get("username"),
            "rank": rank,
            "total_games": player.get("total_games", 0),
            "correct_answers": player.get("correct_answers", 0)
        }
    except Exception as e:
        print(f"❌ Error update_points: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/leaderboard", response_model=List[PlayerResponse])
async def get_leaderboard(
    limit: int = Query(10, ge=1, le=50),
    api_key: str = Depends(verify_api_key)
):
    coll = get_collection()
    try:
        cursor = coll.find().sort("points", -1).limit(limit)
        leaderboard = []
        for rank, doc in enumerate(cursor, start=1):
            leaderboard.append({
                "user_id": doc["_id"],
                "points": doc["points"],
                "first_name": doc.get("first_name"),
                "last_name": doc.get("last_name"),
                "username": doc.get("username"),
                "rank": rank,
                "total_games": doc.get("total_games", 0),
                "correct_answers": doc.get("correct_answers", 0)
            })
        print(f"📊 Leaderboard diambil: {len(leaderboard)} pemain")
        return leaderboard
    except Exception as e:
        print(f"❌ Error leaderboard: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/players")
async def get_all_players(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    api_key: str = Depends(verify_api_key)
):
    coll = get_collection()
    try:
        filter_query = {}
        if search:
            filter_query = {
                "$or": [
                    {"username": {"$regex": search, "$options": "i"}},
                    {"first_name": {"$regex": search, "$options": "i"}}
                ]
            }
        total = coll.count_documents(filter_query)
        cursor = coll.find(filter_query).sort("points", -1).skip(skip).limit(limit)
        players = []
        for doc in cursor:
            players.append({
                "user_id": doc["_id"],
                "points": doc["points"],
                "first_name": doc.get("first_name"),
                "last_name": doc.get("last_name"),
                "username": doc.get("username"),
                "total_games": doc.get("total_games", 0),
                "correct_answers": doc.get("correct_answers", 0)
            })
        return {"total": total, "skip": skip, "limit": limit, "search": search, "players": players}
    except Exception as e:
        print(f"❌ Error get_all_players: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.delete("/points/{user_id}")
async def reset_points(user_id: int, api_key: str = Depends(verify_api_key)):
    coll = get_collection()
    try:
        player = coll.find_one({"_id": user_id})
        if not player:
            raise HTTPException(status_code=404, detail="Player not found")
        coll.update_one(
            {"_id": user_id},
            {"$set": {"points": 0, "updated_at": datetime.now()}}
        )
        print(f"🔄 Poin pemain {user_id} telah direset")
        return {"message": f"Poin pemain {user_id} telah direset ke 0", "success": True}
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error reset_points: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.post("/points/{user_id}/reset")
async def reset_points_post(user_id: int, api_key: str = Depends(verify_api_key)):
    return await reset_points(user_id, api_key)

@app.get("/stats")
async def get_stats(api_key: str = Depends(verify_api_key)):
    coll = get_collection()
    try:
        total_players = coll.count_documents({})
        pipeline = [
            {"$group": {
                "_id": None,
                "total_points": {"$sum": "$points"},
                "avg_points": {"$avg": "$points"},
                "max_points": {"$max": "$points"},
                "min_points": {"$min": "$points"},
                "total_games": {"$sum": "$total_games"},
                "total_correct": {"$sum": "$correct_answers"}
            }}
        ]
        stats_result = list(coll.aggregate(pipeline))
        stats = stats_result[0] if stats_result else {}
        top_player = coll.find_one(sort=[("points", -1)])
        most_active = coll.find_one(sort=[("total_games", -1)])
        active_players = coll.count_documents({"points": {"$gt": 0}})
        return {
            "total_players": total_players,
            "active_players": active_players,
            "total_points": stats.get("total_points", 0),
            "average_points": round(stats.get("avg_points", 0), 2),
            "max_points": stats.get("max_points", 0),
            "min_points": stats.get("min_points", 0),
            "total_games_played": stats.get("total_games", 0),
            "total_correct_answers": stats.get("total_correct", 0),
            "top_player": {
                "user_id": top_player["_id"] if top_player else None,
                "points": top_player["points"] if top_player else 0,
                "username": top_player.get("username") if top_player else None,
                "first_name": top_player.get("first_name") if top_player else None
            } if top_player else None,
            "most_active_player": {
                "user_id": most_active["_id"] if most_active else None,
                "total_games": most_active.get("total_games", 0) if most_active else 0,
                "username": most_active.get("username") if most_active else None
            } if most_active else None,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        print(f"❌ Error stats: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/top/{count}")
async def get_top_players(count: int, api_key: str = Depends(verify_api_key)):
    coll = get_collection()
    try:
        if count < 1 or count > 100:
            count = 10
        cursor = coll.find().sort("points", -1).limit(count)
        top_players = []
        for doc in cursor:
            top_players.append({
                "rank": len(top_players) + 1,
                "user_id": doc["_id"],
                "points": doc["points"],
                "name": doc.get("first_name") or doc.get("username") or f"Player {doc['_id']}",
                "username": doc.get("username"),
                "total_games": doc.get("total_games", 0)
            })
        return {"count": len(top_players), "top_players": top_players}
    except Exception as e:
        print(f"❌ Error get_top_players: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    print(f"🌐 Server akan berjalan di http://{HOST}:{PORT}")
    print(f"📚 Dokumentasi: http://{HOST}:{PORT}/docs")
    uvicorn.run("main:app", host=HOST, port=PORT, reload=False)
